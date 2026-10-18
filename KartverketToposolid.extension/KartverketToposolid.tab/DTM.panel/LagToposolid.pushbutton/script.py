#! python3
# -*- coding: utf-8 -*-
"""
Lag Toposolid — PyRevit-knapp
==============================
Henter høydedata fra Kartverket og oppretter Toposolid direkte i den
åpne Revit-modellen. Project Base Point leses automatisk og vises som
nullpunkt i vinduet — brukeren trenger kun å sette midtpunkt, radius
og punkttetthet, og trykke "Lag Toposolid".

ENGANGSOPPSETT (se README.md i denne mappen for full oppskrift):
  1. Installer pakker i pyRevit sin CPython-motor:
       pip install rasterio numpy pyproj
  2. Last ned WebView2 (NuGet-pakken "Microsoft.Web.WebView2") og legg
     følgende filer i SAMME mappe som dette scriptet:
       - Microsoft.Web.WebView2.Core.dll
       - Microsoft.Web.WebView2.Wpf.dll
       - WebView2Loader.dll  (x64)
  3. Sørg for at "WebView2 Runtime" er installert på maskinen
     (følger normalt med Windows 10/11 + Edge, men kan lastes ned
     separat fra Microsoft ved behov).

VIKTIG — TING SOM MÅ VERIFISERES PÅ DIN MASKIN:
  Dette scriptet er skrevet etter beste kunnskap om Revit API, men er
  IKKE testet mot en ekte Revit-installasjon. Seksjonen som kaller
  Toposolid.Create(...) er den mest usikre delen — se kommentarer
  nede i opprett_toposolid() for hva som bør sjekkes med RevitLookup
  eller Revit 2026 SDK-dokumentasjonen hvis noe feiler.
"""

import os
import re
import json
import math
import time
import traceback

# VIKTIG: pyrevit.forms er IKKE stottet under pyRevit sin CPython-motor
# (feiler med PyRevitCPythonNotSupported allerede ved import). Vi bruker
# derfor ren WPF (System.Windows.MessageBox) for aa vise feilmeldinger,
# og __revit__-globalen (som pyRevit alltid injiserer, uansett motor)
# for aa hente dokumentet - ingen avhengighet til pyrevitlib i det hele
# tatt.
import clr
clr.AddReference("PresentationFramework")
from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage


def _vis_feilmelding(tittel, tekst):
    print("[{}] {}".format(tittel, tekst))  # havner i pyRevit sin Output-konsoll
    try:
        MessageBox.Show(tekst, tittel, MessageBoxButton.OK, MessageBoxImage.Error)
    except Exception:
        pass  # hvis selv MessageBox feiler, er print() over uansett siste utvei


def _feil_og_avslutt(steg, ex):
    """Viser en presis feilmelding med stedsnavn + full traceback, i
    stedet for aa la Revit vise sin egen generiske 'Object reference
    not set...'-dialog uten noen som helst kontekst."""
    detalj = traceback.format_exc()
    _vis_feilmelding(
        "Oppstartsfeil",
        "Kartverket -> Revit Toposolid: feilet under oppstart.\n\n"
        "STEG: {}\n\n"
        "FEIL: {}\n\n"
        "Se ogsaa pyRevit sin Output-konsoll for full traceback.".format(steg, ex),
    )
    raise


# ------------------------------------------------------------------
#  .NET-referanser (hvert steg feiler synlig med praesis stedsangivelse
#  i stedet for en anonym NullReferenceException fra Revit)
# ------------------------------------------------------------------
try:
    import clr
except Exception as ex:
    _feil_og_avslutt("import clr (pythonnet mangler i CPython-miljoeet)", ex)

try:
    clr.AddReference("RevitAPI")
    clr.AddReference("RevitAPIUI")
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
except Exception as ex:
    _feil_og_avslutt("clr.AddReference paa kjerne-.NET/Revit-sammenstillinger", ex)

# AdWindows gir tilgang til Revit sitt hovedvindu-handtak, slik at vi
# kan gjore vaart eget vindu til et ekte Windows-nivaa modalt vindu
# (se vis_vindu). Uten dette kan Revit "fryse" paa en usikker maate
# hvis brukeren proever aa samhandle med modellen mens vinduet vaart
# staar aapent.
try:
    clr.AddReference("AdWindows")
    from Autodesk.Windows import ComponentManager
    _HAR_COMPONENT_MANAGER = True
except Exception:
    _HAR_COMPONENT_MANAGER = False

import System


def _garantert_referanse(dll_path, enkelt_navn):
    """Legger til en .NET-sammenstilling - men gjenbruker en allerede
    lastet versjon (f.eks. lastet av pyRevit selv, eller av et tidligere
    knappetrykk i samme Revit-oekt) i stedet for aa proeve aa laste inn
    vaar egen kopi paa nytt, som feiler med 'Assembly with same name is
    already loaded'."""
    for asm in System.AppDomain.CurrentDomain.GetAssemblies():
        try:
            if asm.GetName().Name == enkelt_navn:
                return asm
        except Exception:
            continue
    return clr.AddReference(dll_path)


try:
    _ADDIN_DIR = os.path.dirname(__file__)
    _dll_core = os.path.join(_ADDIN_DIR, "Microsoft.Web.WebView2.Core.dll")
    _dll_wpf = os.path.join(_ADDIN_DIR, "Microsoft.Web.WebView2.Wpf.dll")
    _dll_loader = os.path.join(_ADDIN_DIR, "WebView2Loader.dll")
    for _p in (_dll_core, _dll_wpf, _dll_loader):
        if not os.path.isfile(_p):
            raise Exception("Filen mangler: {}".format(_p))
    _garantert_referanse(_dll_core, "Microsoft.Web.WebView2.Core")
    _garantert_referanse(_dll_wpf, "Microsoft.Web.WebView2.Wpf")
except Exception as ex:
    _feil_og_avslutt(
        "Laste inn WebView2-DLL-ene (sjekk at alle tre filer ligger i "
        "pushbutton-mappen, og at de er hentet fra riktig mappe i "
        "NuGet-pakken - se README.md)",
        ex,
    )

try:
    from System.Collections.Generic import List
    from System.Windows import Window, WindowStartupLocation, SizeToContent
    from Microsoft.Web.WebView2.Wpf import WebView2
except Exception as ex:
    _feil_og_avslutt("Importere WPF/WebView2-typer etter AddReference", ex)

try:
    from Autodesk.Revit.DB import (
        FilteredElementCollector, BuiltInCategory, BuiltInParameter,
        UnitUtils, XYZ, Transaction, ElementId, Level,
    )
except Exception as ex:
    _feil_og_avslutt("Importere grunnleggende Autodesk.Revit.DB-typer", ex)

try:
    from Autodesk.Revit.DB import UnitTypeId
    _METER = UnitTypeId.Meters
except Exception:
    try:
        from Autodesk.Revit.DB import DisplayUnitType
        _METER = DisplayUnitType.DUT_METERS
    except Exception as ex:
        _feil_og_avslutt("Finne enhetstype for meter (UnitTypeId/DisplayUnitType)", ex)

try:
    from Autodesk.Revit.DB import Toposolid, ToposolidType
    _TOPOSOLID_OK = True
except Exception:
    _TOPOSOLID_OK = False  # haandteres med tydelig norsk feilmelding senere, ikke her

# ------------------------------------------------------------------
#  Nettverk / geodata-avhengigheter (krever engangsoppsett, se README)
# ------------------------------------------------------------------
# NB: requests/urllib3 er bevisst UNNGAATT her. pyRevit sitt CPython-
# miljoe ser ut til aa ha en egen (eldre/annen) kopi av urllib3
# bundlet fra foer, som kolliderer med en fersk pip-installert versjon
# (samme problemklasse som WebView2-DLL-konflikten lenger opp). Vi
# bruker derfor Python sitt innebygde urllib i stedet, som aldri kan
# kollidere siden det ikke er en separat installert pakke.
import urllib.request
import urllib.parse
import urllib.error


class _EnkelHttpRespons(object):
    """Minimal stand-in for requests sitt Response-objekt - kun det vi
    faktisk bruker (content/text/json()/raise_for_status())."""

    def __init__(self, content, status_code):
        self.content = content
        self.status_code = status_code

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP-feil {}".format(self.status_code))


def _http_get(url, params=None, timeout=15, fremdrift=None):
    """fremdrift(lest_bytes, total_bytes_eller_None) kalles underveis i
    nedlastingen hvis den er gitt."""
    full_url = url
    if params:
        full_url = "{}?{}".format(url, urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(full_url, timeout=timeout) as resp:
            if fremdrift is None:
                return _EnkelHttpRespons(resp.read(), resp.getcode())
            try:
                total = int(resp.headers.get("Content-Length") or 0) or None
            except Exception:
                total = None
            deler = []
            lest = 0
            while True:
                bit = resp.read(65536)
                if not bit:
                    break
                deler.append(bit)
                lest += len(bit)
                fremdrift(lest, total)
            return _EnkelHttpRespons(b"".join(deler), resp.getcode())
    except urllib.error.HTTPError as e:
        return _EnkelHttpRespons(e.read(), e.code)


try:
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from pyproj import Transformer
    import pyproj
except Exception as ex:
    _feil_og_avslutt(
        "Importere numpy/rasterio/pyproj - disse maa vaere "
        "pip-installert i SAMME python.exe som pyRevit sin CPython-motor "
        "bruker (se README.md steg 6)",
        ex,
    )


# ====================================================================
#  BACKEND-LOGIKK — portert direkte fra kartverket_til_revit_ui.py
#  (samme Helmert-transformasjon, NN54-korreksjon og WCS-henting som
#  i den frittstående nettapp-versjonen, uendret virkemåte)
# ====================================================================

HPCS_A = 0.7986185641
HPCS_B = -0.6018365771
HPCS_C = -5193109.9654
HPCS_D = -5904368.2281
HPCS_DET = HPCS_A * HPCS_A + HPCS_B * HPCS_B


def utm34_til_hpcs(e, n):
    return HPCS_A * e - HPCS_B * n + HPCS_C, HPCS_B * e + HPCS_A * n + HPCS_D


def hpcs_til_utm34(x, y):
    xc, yd = x - HPCS_C, y - HPCS_D
    e = (HPCS_A * xc + HPCS_B * yd) / HPCS_DET
    n = (-HPCS_B * xc + HPCS_A * yd) / HPCS_DET
    return e, n


def er_hpcs(epsg_inn):
    return str(epsg_inn).lower() == "hpcs"


def _hpcs_til_wgs84(mx, my):
    e34, n34 = hpcs_til_utm34(mx, my)
    t = Transformer.from_crs("EPSG:25834", "EPSG:4326", always_xy=True)
    lon, lat = t.transform(e34, n34)
    return lon, lat


def _nn54_offset_api(lon, lat, ref_h=60.0):
    url = "https://ws.geonorge.no/transformering/v1/transformer"
    params = {"x": lon, "y": lat, "z": ref_h, "fra": 5942, "til": 6144}
    r = _http_get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    z54 = data.get("z", data.get("Z"))
    if z54 is None:
        raise RuntimeError("uventet API-svar: {}".format(str(data)[:120]))
    off = float(z54) - ref_h
    if not math.isfinite(off):
        raise RuntimeError("API ga ugyldig høyde")
    return off


def _nn54_offset_proj(lon, lat, ref_h=60.0):
    pyproj.network.set_network_enabled(True)
    vt = Transformer.from_crs("EPSG:5941", "EPSG:5776", always_xy=True, allow_ballpark=False)
    _, _, z54 = vt.transform(lon, lat, ref_h)
    off = z54 - ref_h
    if not math.isfinite(off):
        raise RuntimeError("NNTrans-grid ikke tilgjengelig")
    return off


def nn2000_til_nn54_offset(lon, lat, ref_h=60.0):
    try:
        return _nn54_offset_api(lon, lat, ref_h)
    except Exception as api_err:
        try:
            return _nn54_offset_proj(lon, lat, ref_h)
        except Exception as proj_err:
            raise RuntimeError(
                "API feilet ({}); PROJ-grid feilet ({})".format(
                    str(api_err)[:50], str(proj_err)[:50]
                )
            )


KOORDINATSYSTEMER = {
    "NTM05": {"epsg": 5105, "navn": "NTM sone 5"},
    "NTM06": {"epsg": 5106, "navn": "NTM sone 6"},
    "NTM07": {"epsg": 5107, "navn": "NTM sone 7"},
    "NTM08": {"epsg": 5108, "navn": "NTM sone 8"},
    "NTM09": {"epsg": 5109, "navn": "NTM sone 9"},
    "NTM10": {"epsg": 5110, "navn": "NTM sone 10"},
    "NTM11": {"epsg": 5111, "navn": "NTM sone 11"},
    "NTM12": {"epsg": 5112, "navn": "NTM sone 12"},
    "NTM13": {"epsg": 5113, "navn": "NTM sone 13"},
    "NTM14": {"epsg": 5114, "navn": "NTM sone 14"},
    "NTM15": {"epsg": 5115, "navn": "NTM sone 15"},
    "NTM16": {"epsg": 5116, "navn": "NTM sone 16"},
    "NTM17": {"epsg": 5117, "navn": "NTM sone 17"},
    "NTM18": {"epsg": 5118, "navn": "NTM sone 18"},
    "NTM19": {"epsg": 5119, "navn": "NTM sone 19"},
    "NTM20": {"epsg": 5120, "navn": "NTM sone 20"},
    "NTM21": {"epsg": 5121, "navn": "NTM sone 21"},
    "NTM22": {"epsg": 5122, "navn": "NTM sone 22"},
    "NTM23": {"epsg": 5123, "navn": "NTM sone 23"},
    "NTM24": {"epsg": 5124, "navn": "NTM sone 24"},
    "NTM25": {"epsg": 5125, "navn": "NTM sone 25"},
    "NTM26": {"epsg": 5126, "navn": "NTM sone 26"},
    "NTM27": {"epsg": 5127, "navn": "NTM sone 27"},
    "NTM28": {"epsg": 5128, "navn": "NTM sone 28"},
    "NTM29": {"epsg": 5129, "navn": "NTM sone 29"},
    "NTM30": {"epsg": 5130, "navn": "NTM sone 30"},
    "UTM32": {"epsg": 25832, "navn": "UTM sone 32"},
    "UTM33": {"epsg": 25833, "navn": "UTM sone 33"},
    "UTM35": {"epsg": 25835, "navn": "UTM sone 35"},
}

WCS_URL = "https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm_somlos"
_coverage_cache = None


def hent_coverage_navn():
    global _coverage_cache
    if _coverage_cache:
        return _coverage_cache
    r = _http_get(
        WCS_URL,
        params={"SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCapabilities"},
        timeout=15,
    )
    navn = re.findall(r"<n>([^<]+)</n>", r.text)
    if not navn:
        navn = re.findall(r"<name>([^<]+)</name>", r.text)
    if not navn:
        navn = re.findall(r"<ows:Identifier>([^<]+)</ows:Identifier>", r.text)
    navn = [n.strip() for n in navn if len(n.strip()) > 3 and " " not in n.strip()]
    if not navn:
        navn = ["las_dtm_somlos"]
    _coverage_cache = navn
    return navn


def generer_punkter(epsg_inn, midtpunkt_e, midtpunkt_n, radius, tetthet,
                     nullpunkt_e, nullpunkt_n, relativ_z, vert_offset=0.0,
                     utsnitt_form="kvadrat", fremdrift=None):
    """fremdrift(andel 0-1, detaljtekst) kalles under nedlastingen."""
    if er_hpcs(epsg_inn):
        _u34_q = Transformer.from_crs("EPSG:25834", "EPSG:25833", always_xy=True)
        _q_u34 = Transformer.from_crs("EPSG:25833", "EPSG:25834", always_xy=True)

        def til_utm33_fn(x, y):
            e34, n34 = hpcs_til_utm34(x, y)
            return _u34_q.transform(e34, n34)

        def fra_utm33_fn(qe, qn):
            e34, n34 = _q_u34.transform(qe, qn)
            return utm34_til_hpcs(e34, n34)
    else:
        _t1 = Transformer.from_crs("EPSG:{}".format(epsg_inn), "EPSG:25833", always_xy=True)
        _t2 = Transformer.from_crs("EPSG:25833", "EPSG:{}".format(epsg_inn), always_xy=True)
        til_utm33_fn = lambda e, n: _t1.transform(e, n)
        fra_utm33_fn = lambda qe, qn: _t2.transform(qe, qn)

    utm_e, utm_n = til_utm33_fn(midtpunkt_e, midtpunkt_n)
    minx, miny = utm_e - radius, utm_n - radius
    maxx, maxy = utm_e + radius, utm_n + radius

    # Terrenget hentes direkte med punkttettheten som oppløsning (5 m
    # tetthet = 5 m piksler), slik at store utsnitt ikke laster ned mer
    # enn noedvendig. Med tetthet 1 m er dette identisk med tidligere.
    steg = max(1, int(tetthet))
    res = float(steg)
    px = max(1, int(round(2 * radius / res)))

    anslag = px * px * (math.pi / 4.0 if utsnitt_form == "sirkel" else 1.0)
    if anslag > MAKS_PUNKTER:
        raise Exception(
            "For mange punkter: ca. {:,.0f} (grense {:,.0f}). Øk punkttettheten "
            "eller reduser radius. Med {:.0f} m radius gir {:.0f} m tetthet ca. "
            "{:,.0f} punkter.".format(
                anslag, MAKS_PUNKTER, radius, _foreslaa_tetthet(radius, utsnitt_form),
                (2 * radius / _foreslaa_tetthet(radius, utsnitt_form)) ** 2
                * (math.pi / 4.0 if utsnitt_form == "sirkel" else 1.0),
            ).replace(",", " ")
        )

    data = _hent_dtm_flislagt(minx, maxy, res, px, px, fremdrift=fremdrift)

    if np.all(np.isnan(data)):
        raise Exception("Ingen gyldige høydeverdier. Sjekk koordinater og koordinatsystem.")

    # Pikselsentre (vektorisert - raskt ogsaa for flere hundre tusen punkter)
    rows, cols = data.shape
    rr, cc = np.nonzero(~np.isnan(data))
    h = data[rr, cc]
    ue = minx + (cc + 0.5) * res
    un = maxy - (rr + 0.5) * res
    pe, pn = fra_utm33_fn(ue, un)
    pe = np.asarray(pe, dtype=float)
    pn = np.asarray(pn, dtype=float)
    if utsnitt_form == "sirkel":
        inne = np.hypot(pe - midtpunkt_e, pn - midtpunkt_n) <= radius
        pe, pn, h = pe[inne], pn[inne], h[inne]

    if h.size == 0:
        raise Exception("Ingen punkter innenfor valgt utsnitt. Prøv større radius.")

    z_ref = float(h.min()) if relativ_z else 0.0
    voff = 0.0 if relativ_z else vert_offset
    x = np.round(pe - nullpunkt_e, 4)
    y = np.round(pn - nullpunkt_n, 4)
    z = np.round(h - z_ref + voff, 3)
    punkter = list(zip(x.tolist(), y.tolist(), z.tolist()))

    return punkter


# Grense for antall punkter i ett toposolid. Satt for aa unngaa at Revit
# henger paa enorme punktmengder - juster hvis Revit viser seg aa takle mer.
MAKS_PUNKTER = 1000000

# Kartverket sin WCS avviser for store enkeltforespoersler (ArcGIS-feilside).
# 1000 x 1000 piksler per flis er kjent aa fungere.
FLIS_PX = 1000


def _foreslaa_tetthet(radius, utsnitt_form):
    faktor = math.pi / 4.0 if utsnitt_form == "sirkel" else 1.0
    t = 1
    while (2 * radius / t) ** 2 * faktor > MAKS_PUNKTER:
        t += 1
    return t


def _wcs_feiltekst(innhold):
    tekst = innhold.decode("utf-8", errors="replace")
    m = re.search(r"<title>([^<]*)</title>", tekst, re.I)
    m2 = re.search(r"<ServiceException[^>]*>([^<]*)<", tekst)
    detalj = (m2.group(1).strip() if m2 else "") or (m.group(1).strip() if m else "")
    return "Kartverket avviste forespørselen{}".format(": " + detalj if detalj else "")


def _hent_dtm_flislagt(minx, maxy, res, bredde_px, hoyde_px, fremdrift=None):
    """Henter DTM i fliser paa maks FLIS_PX x FLIS_PX piksler og setter dem
    sammen. Piksel (r, c) har senter i (minx + (c+0.5)res, maxy - (r+0.5)res).
    NaN der Kartverket ikke har data."""
    coverage = hent_coverage_navn()[0]
    data = np.full((hoyde_px, bredde_px), np.nan)
    fliser = [(r0, c0) for r0 in range(0, hoyde_px, FLIS_PX) for c0 in range(0, bredde_px, FLIS_PX)]
    # Fremdrift vektes etter antall piksler, siden kantflisene kan vaere smaa
    tot_px = float(bredde_px * hoyde_px)
    ferdig_px = 0.0
    for i, (r0, c0) in enumerate(fliser):
        h = min(FLIS_PX, hoyde_px - r0)
        w = min(FLIS_PX, bredde_px - c0)
        fx0 = minx + c0 * res
        fy1 = maxy - r0 * res
        params = {
            "SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCoverage",
            "COVERAGE": coverage, "CRS": "EPSG:25833",
            "BBOX": "{},{},{},{}".format(fx0, fy1 - h * res, fx0 + w * res, fy1),
            "WIDTH": w, "HEIGHT": h, "FORMAT": "GeoTIFF",
        }
        flis = None
        feil = None
        # Forventet stoerrelse (float32 GeoTIFF) brukes hvis serveren ikke
        # oppgir Content-Length.
        forventet = 4.0 * w * h

        def _bytes(lest, total, _i=i, _ferdig=ferdig_px, _px=w * h):
            if fremdrift is None:
                return
            delandel = min(1.0, lest / float(total or forventet))
            fremdrift((_ferdig + delandel * _px) / tot_px,
                      "Flis {}/{} - {:.1f} MB lastet ned".format(_i + 1, len(fliser), lest / 1e6))

        for _forsok in range(3):
            try:
                r = _http_get(WCS_URL, params=params, timeout=60, fremdrift=_bytes)
                if r.content[:1] == b"<":
                    raise Exception(_wcs_feiltekst(r.content))
                with MemoryFile(r.content) as mf:
                    with mf.open() as ds:
                        flis = ds.read(1).astype(float)
                        nodata = ds.nodata
                break
            except Exception as ex:
                feil = ex
        if flis is None:
            raise Exception("Kunne ikke hente terrengflis {}/{}: {}".format(i + 1, len(fliser), feil))
        if flis.shape != (h, w):
            raise Exception("Uventet flisstørrelse {} fra Kartverket (forventet {}).".format(flis.shape, (h, w)))
        if nodata is not None:
            flis[flis == nodata] = np.nan
        flis[flis < -100] = np.nan
        flis[flis > 3000] = np.nan
        data[r0:r0 + h, c0:c0 + w] = flis
        ferdig_px += w * h
        if fremdrift is not None:
            fremdrift(ferdig_px / tot_px, "Flis {}/{} ferdig".format(i + 1, len(fliser)))
    return data


# ====================================================================
#  REVIT-SPESIFIKT
# ====================================================================

def hent_base_point(doc):
    """Leser Project Base Point.

    To ulike ting leses, siden de kan avvike fra hverandre:
      - E/W, N/S-PARAMETRENE: de tallene brukeren faktisk har skrevet
        inn i Manage > Coordinates (brukes til aa forhaandsutfylle
        nullpunkt i appen).
      - Position: punktets FAKTISKE geometriske plassering i Revit sitt
        interne koordinatsystem (brukes som offset naar ny geometri
        opprettes). Denne kan vaere (0,0,0) selv om E/W,N/S-parametrene
        viser store tall, hvis punktets ikon aldri er fysisk flyttet
        i modellen - de to henger ikke alltid sammen.

    NB: bruker OST_ProjectBasePoint (ikke Survey Point)."""
    collector = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_ProjectBasePoint)
        .WhereElementIsNotElementType()
    )
    bp = collector.FirstElement()
    if bp is None:
        raise Exception("Fant ikke Project Base Point i den åpne modellen.")

    e_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
    n_param = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
    e_ft = e_param.AsDouble() if e_param else 0.0
    n_ft = n_param.AsDouble() if n_param else 0.0
    e_m = UnitUtils.ConvertFromInternalUnits(e_ft, _METER)
    n_m = UnitUtils.ConvertFromInternalUnits(n_ft, _METER)

    pos = bp.Position  # XYZ, internal units (fot) - kun til geometri-offset

    return e_m, n_m, pos


def _unikt_levelnavn(doc, basisnavn):
    """Garanterer et unikt Level-navn - Revit tillater ikke to nivaaer
    med identisk navn. Legger paa (2), (3) osv. ved kollisjon."""
    eksisterende = set(lvl.Name for lvl in FilteredElementCollector(doc).OfClass(Level))
    if basisnavn not in eksisterende:
        return basisnavn
    i = 2
    while "{} ({})".format(basisnavn, i) in eksisterende:
        i += 1
    return "{} ({})".format(basisnavn, i)


_TIDSFIL = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "KartverketToposolid", "lag_toposolid_tid.json")


def _estimer_revit_tid(n_punkter):
    """Estimert tid (s) for Toposolid.Create + Commit, ut fra maalt tid per
    punkt i tidligere kjoeringer. None hvis ingen historikk finnes."""
    try:
        with open(_TIDSFIL, "r", encoding="utf-8") as f:
            d = json.load(f)
        return max(1.0, d["fast_s"] + d["s_per_punkt"] * n_punkter)
    except Exception:
        return None


def _lagre_revit_tid(n_punkter, sekunder):
    """Oppdaterer estimatet med glidende snitt (nyeste maaling teller 50 %)."""
    try:
        try:
            with open(_TIDSFIL, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = None
        fast = 1.0
        ny = max(0.0, sekunder - fast) / max(1, n_punkter)
        if d:
            ny = 0.5 * d["s_per_punkt"] + 0.5 * ny
        os.makedirs(os.path.dirname(_TIDSFIL), exist_ok=True)
        with open(_TIDSFIL, "w", encoding="utf-8") as f:
            json.dump({"fast_s": fast, "s_per_punkt": ny}, f)
    except Exception:
        pass


def opprett_toposolid(doc, punkter, base_pos, meld=None):
    """Oppretter Toposolid fra punktliste (x, y, z i meter, RELATIVT
    til Project Base Point). Punktene forskyves med Base Point sin
    egen interne posisjon før de brukes som XYZ, slik at resultatet
    blir korrekt uansett hvor Revit sitt interne origo ligger i
    forhold til Base Point.

    !! USIKKERT / MÅ VERIFISERES !!
    Toposolid.Create sin eksakte signatur er skrevet etter beste
    kunnskap om Revit 2024-2026 API, men IKKE testet mot en ekte
    installasjon. Hvis dette feiler:
      1. Åpne RevitLookup eller Revit API-dokumentasjonen for
         Autodesk.Revit.DB.Toposolid i din Revit 2026 SDK.
      2. Sjekk om metoden heter noe annet, tar andre parametre,
         eller krever en IList<CurveLoop> i tillegg til punktene.
      3. Juster kallet nedenfor deretter.
    """
    if not _TOPOSOLID_OK:
        raise Exception(
            "Fant ikke Toposolid/ToposolidType i Autodesk.Revit.DB. "
            "Toposolid krever Revit 2024 eller nyere."
        )

    meld = meld or (lambda *a, **k: None)
    # Omregningsfaktor hentes én gang (i stedet for tre API-kall per punkt)
    m_til_ft = UnitUtils.ConvertToInternalUnits(1.0, _METER)
    bx, by, bz = base_pos.X, base_pos.Y, base_pos.Z
    n = len(punkter)
    hvert = max(1, n // 50)
    xyz_punkter = List[XYZ]()
    z_verdier_ft = []
    for i, (x_rel, y_rel, z_rel) in enumerate(punkter):
        z_ft = z_rel * m_til_ft + bz
        xyz_punkter.Add(XYZ(x_rel * m_til_ft + bx, y_rel * m_til_ft + by, z_ft))
        z_verdier_ft.append(z_ft)
        if i % hvert == 0:
            meld(2, i / float(n), "{:,} av {:,} punkter klargjort".format(i, n).replace(",", " "))
    meld(2, 1.0, "{:,} punkter klargjort".format(n).replace(",", " "))

    toposolid_type_id = FilteredElementCollector(doc).OfClass(ToposolidType).FirstElementId()
    if toposolid_type_id == ElementId.InvalidElementId:
        raise Exception("Fant ingen ToposolidType i prosjektet.")

    # Toposolid.Create bygger et volum ned til det gitte Level, ikke en
    # tynn skive - vi trenger derfor et Level plassert like under
    # laveste terrengpunkt (samme virkemaate som nettapp-CSV-importen
    # ga, ca. 1 m under laveste kote), i stedet for prosjektets
    # eksisterende laveste niva (som typisk ligger paa kote 0).
    TYKKELSE_UNDER_LAVESTE_M = 1.0
    z_min_ft = min(z_verdier_ft)
    onsket_niva_ft = z_min_ft - UnitUtils.ConvertToInternalUnits(TYKKELSE_UNDER_LAVESTE_M, _METER)
    TOLERANSE_FT = UnitUtils.ConvertToInternalUnits(0.05, _METER)  # 5 cm

    t = Transaction(doc, "Lag Toposolid fra Kartverket-data")
    t.Start()
    try:
        level = None
        for lvl in FilteredElementCollector(doc).OfClass(Level):
            if abs(lvl.Elevation - onsket_niva_ft) < TOLERANSE_FT:
                level = lvl
                break
        if level is None:
            level = Level.Create(doc, onsket_niva_ft)
            onsket_niva_m = UnitUtils.ConvertFromInternalUnits(onsket_niva_ft, _METER)
            basisnavn = "Terreng - Kartverket import (kote {:.2f})".format(onsket_niva_m)
            level.Name = _unikt_levelnavn(doc, basisnavn)

        # Revit gir ingen fremdrift fra Toposolid.Create/Commit. Grensesnittet
        # viser derfor et estimat basert paa maalt tid fra tidligere kjoeringer.
        estimat = _estimer_revit_tid(n)
        meld(3, None, "Revit bygger toposolidet ({:,} punkter)".format(n).replace(",", " "),
             estimat_s=estimat)
        t0 = time.time()
        Toposolid.Create(doc, xyz_punkter, toposolid_type_id, level.Id)
        t.Commit()
        brukt = time.time() - t0
        _lagre_revit_tid(n, brukt)
        return brukt
    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise Exception(
            "Kunne ikke opprette Toposolid — se kommentar i opprett_toposolid() "
            "i script.py for hva som bør sjekkes. Detalj: {}".format(ex)
        )


# ====================================================================
#  HTML-BYGGING (erstatter Jinja2-malen fra Flask-versjonen)
# ====================================================================

def _options(prefix, verdi_er_epsg):
    linjer = []
    for key, val in KOORDINATSYSTEMER.items():
        if not key.startswith(prefix):
            continue
        verdi = val["epsg"] if verdi_er_epsg else key
        selected = " selected" if (verdi_er_epsg and key == "NTM23") else ""
        linjer.append('<option value="{}"{}>{} — {}</option>'.format(verdi, selected, key, val["navn"]))
    return "\n".join(linjer)


def bygg_html(null_e, null_n):
    html_path = os.path.join(_ADDIN_DIR, "ui.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("__NULL_E__", "{:.4f}".format(null_e))
    html = html.replace("__NULL_N__", "{:.4f}".format(null_n))
    html = html.replace("__NTM_OPTIONS__", _options("NTM", verdi_er_epsg=True))
    html = html.replace("__UTM_OPTIONS__", _options("UTM", verdi_er_epsg=True))
    html = html.replace("__NTM_SONE_OPTIONS__", _options("NTM", verdi_er_epsg=False))
    html = html.replace("__UTM_SONE_OPTIONS__", _options("UTM", verdi_er_epsg=False))
    return html


# ====================================================================
#  MELDINGSHÅNDTERING (JS <-> Python via WebView2)
# ====================================================================

def do_convert_wgs84(payload):
    epsg = payload["epsg"]
    lat = payload["lat"]
    lng = payload["lng"]
    if er_hpcs(epsg):
        t = Transformer.from_crs("EPSG:4326", "EPSG:25834", always_xy=True)
        e34, n34 = t.transform(lng, lat)
        e, n = utm34_til_hpcs(e34, n34)
    else:
        t = Transformer.from_crs("EPSG:4326", "EPSG:{}".format(epsg), always_xy=True)
        e, n = t.transform(lng, lat)
    return {"e": e, "n": n}


def do_convert_to_wgs84(payload):
    epsg = payload["epsg"]
    e = payload["e"]
    n = payload["n"]
    if er_hpcs(epsg):
        e34, n34 = hpcs_til_utm34(e, n)
        t = Transformer.from_crs("EPSG:25834", "EPSG:4326", always_xy=True)
        lng, lat = t.transform(e34, n34)
    else:
        t = Transformer.from_crs("EPSG:{}".format(epsg), "EPSG:4326", always_xy=True)
        lng, lat = t.transform(e, n)
    return {"lat": lat, "lng": lng}


def do_lag_toposolid(doc, base_pos, payload, meld=None):
    epsg = payload["epsg"]
    vert = payload.get("vert", 0.0) or 0.0
    nn54_korr = payload.get("nn54_korr", False)
    mid_e = payload["mid_e"]
    mid_n = payload["mid_n"]
    null_e = payload["null_e"]
    null_n = payload["null_n"]
    radius = payload["radius"]
    tetthet = payload["tetthet"]
    relativ_z = payload["relativ_z"]
    utsnitt_form = payload.get("utsnitt_form", "kvadrat")

    nn54_offset = None
    warning = None
    if nn54_korr and er_hpcs(epsg):
        try:
            lon, lat = _hpcs_til_wgs84(mid_e, mid_n)
            nn54_offset = nn2000_til_nn54_offset(lon, lat)
            vert = vert + nn54_offset
        except Exception as ge:
            warning = "NN54-korreksjon kunne ikke beregnes: {}".format(str(ge)[:100])

    meld = meld or (lambda *a, **k: None)
    t_start = time.time()
    meld(1, 0.0, "Kobler til Kartverket ...")
    punkter = generer_punkter(
        epsg_inn=epsg, midtpunkt_e=mid_e, midtpunkt_n=mid_n,
        radius=radius, tetthet=tetthet,
        nullpunkt_e=null_e, nullpunkt_n=null_n, relativ_z=relativ_z,
        vert_offset=vert, utsnitt_form=utsnitt_form,
        fremdrift=lambda andel, detalj: meld(1, andel, detalj),
    )
    t_terreng = time.time() - t_start

    t_punkter_start = time.time()
    t_revit = opprett_toposolid(doc, punkter, base_pos, meld=meld)
    t_punkter = time.time() - t_punkter_start - (t_revit or 0.0)

    z_vals = [p[2] for p in punkter]
    resultat = {"antall": len(punkter), "min_z": min(z_vals), "max_z": max(z_vals),
                "tider": {"terreng": round(t_terreng, 1), "punkter": round(t_punkter, 1),
                          "revit": round(t_revit or 0.0, 1)}}
    if nn54_offset is not None:
        resultat["nn54_offset"] = round(nn54_offset, 4)
    if warning:
        resultat["warning"] = warning
    return resultat


# ====================================================================
#  VINDU (WPF + WebView2)
# ====================================================================

def _pump_ui():
    """Lar WPF/WebView2 behandle ventende meldinger (som DoEvents), slik at
    fremdriftsmeldingene faktisk vises mens arbeidet paagaar."""
    try:
        from System import Action
        from System.Windows.Threading import Dispatcher, DispatcherPriority
        Dispatcher.CurrentDispatcher.Invoke(DispatcherPriority.Background, Action(lambda: None))
    except Exception:
        pass


def vis_vindu(doc):
    null_e, null_n, base_pos = hent_base_point(doc)
    html = bygg_html(null_e, null_n)

    window = Window()
    window.Title = "Kartverket → Revit Toposolid"
    window.Width = 1400
    window.Height = 900
    window.WindowStartupLocation = WindowStartupLocation.CenterScreen

    # Gjoer vinduet til et EKTE Windows-modalt vindu, eid av Revit sitt
    # hovedvindu. Uten dette blokkerer ShowDialog() kun vaar egen traad,
    # mens Revit sitt vindu fortsatt kan motta klikk fra brukeren - noe
    # som gir en usikker/inkonsistent tilstand (og i praksis krasj) hvis
    # brukeren samhandler med modellen foer vinduet vaart er lukket.
    if _HAR_COMPONENT_MANAGER:
        try:
            import System.Windows.Interop as _interop
            _helper = _interop.WindowInteropHelper(window)
            _helper.Owner = ComponentManager.ApplicationWindow
        except Exception:
            pass  # faller tilbake til vanlig (svakere) modalitet under

    webview = WebView2()

    # WebView2 prover som standard aa lagre brukerdata ved siden av
    # verts-EXE-en (her: Revit.exe i Program Files), som normalt ikke
    # er skrivbar uten admin. I stedet for aa bruke
    # CoreWebView2CreationProperties (som krever en type fra
    # Microsoft.Web.WebView2.Core - og pyRevit kan ha en annen versjon
    # av DENNE DLL-en allerede lastet, med annen API-overflate), setter
    # vi miljovariabelen WEBVIEW2_USER_DATA_FOLDER, som den native
    # WebView2Loader.dll leser direkte, uavhengig av .NET-typeversjon.
    # MAA settes foer EnsureCoreWebView2Async kalles.
    import tempfile
    _user_data_dir = os.path.join(tempfile.gettempdir(), "KartverketToposolidWebView2")
    try:
        os.makedirs(_user_data_dir, exist_ok=True)
    except Exception:
        pass
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = _user_data_dir
    window.Content = webview

    _tilstand = {"opptatt": False, "sist": 0.0}

    def meld_fremdrift(steg, andel, detalj, estimat_s=None):
        """Sender fremdrift til grensesnittet. Begrenset til ca. 10 per
        sekund, men steg-skifter og estimater sendes alltid."""
        naa = time.time()
        viktig = estimat_s is not None or andel is None or andel in (0.0, 1.0)
        if not viktig and naa - _tilstand["sist"] < 0.1:
            return
        _tilstand["sist"] = naa
        try:
            webview.CoreWebView2.PostWebMessageAsString(json.dumps({
                "type": "fremdrift", "steg": steg, "antall_steg": 3,
                "andel": andel, "detalj": detalj, "estimat_s": estimat_s,
            }))
            _pump_ui()
        except Exception:
            pass  # fremdrift er aldri kritisk

    def on_closing(sender, e):
        # Ikke la vinduet lukkes midt i en kjoering (fremdriften pumper
        # meldingskoeen, saa lukkeknappen er klikkbar underveis).
        if _tilstand["opptatt"]:
            e.Cancel = True

    window.Closing += on_closing

    def on_web_message(sender, args):
        call_id = None
        try:
            raw = args.TryGetWebMessageAsString()
            msg = json.loads(raw)
            call_id = msg.get("id")
            action = msg.get("action")
            payload = msg.get("payload") or {}

            if action == "convert_wgs84":
                result = do_convert_wgs84(payload)
            elif action == "convert_to_wgs84":
                result = do_convert_to_wgs84(payload)
            elif action == "lag_toposolid":
                if _tilstand["opptatt"]:
                    raise Exception("En toposolid lages allerede - vent til den er ferdig.")
                _tilstand["opptatt"] = True
                try:
                    result = do_lag_toposolid(doc, base_pos, payload, meld=meld_fremdrift)
                finally:
                    _tilstand["opptatt"] = False
            else:
                result = {"error": "Ukjent handling: {}".format(action)}
        except Exception as ex:
            result = {"error": str(ex)}

        svar = json.dumps({"id": call_id, "result": result})
        try:
            webview.CoreWebView2.PostWebMessageAsString(svar)
        except Exception:
            pass  # vinduet er lukket

    def on_init(sender, args):
        if args.IsSuccess:
            webview.CoreWebView2.WebMessageReceived += on_web_message
            webview.CoreWebView2.NavigateToString(html)
        else:
            _vis_feilmelding(
                "WebView2-feil",
                "WebView2 kunne ikke initialiseres. Sjekk at WebView2 Runtime "
                "er installert, og at DLL-ene ligger i pushbutton-mappen.\n\n{}"
                .format(args.InitializationException),
            )

    webview.CoreWebView2InitializationCompleted += on_init
    webview.EnsureCoreWebView2Async(None)

    window.ShowDialog()


# ====================================================================
#  ENTRY POINT
# ====================================================================

if __name__ == "__main__":
    # __revit__ injiseres alltid av pyRevit sin kjerne-loader, uansett
    # motor (IronPython/CPython) - trygg erstatning for pyrevit.revit.doc.
    doc = __revit__.ActiveUIDocument.Document
    try:
        vis_vindu(doc)
    except Exception as e:
        _vis_feilmelding("Feil", "Kunne ikke åpne Kartverket → Revit Toposolid:\n\n{}".format(e))
