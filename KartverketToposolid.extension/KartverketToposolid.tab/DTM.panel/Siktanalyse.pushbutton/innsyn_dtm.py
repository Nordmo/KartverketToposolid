# -*- coding: utf-8 -*-
"""
Innsyn - terrenghenting fra Kartverket
======================================
Henter DTM (wcs.hoyde-dtm_somlos) flislagt i UTM33 og resampler til et
lokalt rutenett i Revit-internkoordinater (meter).

Koordinatoppsettet er bevisst IDENTISK med Lag Toposolid (ingen
rotasjon, kun translasjon via Project Base Point):
    E = nullpunkt_E + (X_intern_m - BasePoint.X_m)
    N = nullpunkt_N + (Y_intern_m - BasePoint.Y_m)
HPCS-transformasjonen er kopiert uendret fra LagToposolid/script.py, slik
at terrenget treffer toposolider laget med den knappen.
Høyde justeres ikke her - det gjøres mot toposolidet i script.py.
"""

import re
import json
import math
import urllib.request
import urllib.parse
import urllib.error

import numpy as np

# --- Kopiert uendret fra LagToposolid/script.py --------------------------

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


KOORDINATSYSTEMER = [("NTM{:02d}".format(z), 5100 + z, "NTM sone {}".format(z)) for z in range(5, 31)]
KOORDINATSYSTEMER += [
    ("UTM32", 25832, "UTM sone 32"),
    ("UTM33", 25833, "UTM sone 33"),
    ("UTM35", 25835, "UTM sone 35"),
    ("HPCS", "hpcs", "HPCS - Melkøya (Hammerfest LNG)"),
]

WCS_URL = "https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm_somlos"
_coverage_cache = None


class _EnkelHttpRespons(object):
    def __init__(self, content, status_code):
        self.content = content
        self.status_code = status_code

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP-feil {}".format(self.status_code))


def _http_get(url, params=None, timeout=15):
    full_url = url
    if params:
        full_url = "{}?{}".format(url, urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(full_url, timeout=timeout) as resp:
            return _EnkelHttpRespons(resp.read(), resp.getcode())
    except urllib.error.HTTPError as e:
        return _EnkelHttpRespons(e.read(), e.code)


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

# --- Slutt på kopiert kode ----------------------------------------------


def crs_til_utm33_funksjon(epsg):
    """Returnerer f(E, N) -> (E33, N33) for numpy-arrays."""
    from pyproj import Transformer
    if str(epsg).lower() == "hpcs":
        t = Transformer.from_crs("EPSG:25834", "EPSG:25833", always_xy=True)

        def f(e, n):
            e34, n34 = hpcs_til_utm34(np.asarray(e, float), np.asarray(n, float))
            return t.transform(e34, n34)
        return f
    if int(epsg) == 25833:
        return lambda e, n: (np.asarray(e, float), np.asarray(n, float))
    t = Transformer.from_crs("EPSG:{}".format(int(epsg)), "EPSG:25833", always_xy=True)
    return lambda e, n: t.transform(np.asarray(e, float), np.asarray(n, float))


def _les_geotiff(innhold):
    from rasterio.io import MemoryFile
    with MemoryFile(innhold) as mf:
        with mf.open() as ds:
            data = ds.read(1).astype(np.float32)
            nodata = ds.nodata
    if nodata is not None:
        data[data == nodata] = np.nan
    data[(data < -100) | (data > 3000)] = np.nan
    return data


def hent_dtm_utm33(minx, miny, maxx, maxy, res, flis_px=1000, logg=None, http_get=None):
    """Henter DTM flislagt. Returnerer (data[rad, kol], x_venstre, y_topp, res)
    der pikselsenter (r, c) ligger i (x_venstre + (c+0.5)res, y_topp - (r+0.5)res).
    NaN der Kartverket ikke har data (sjø, utenfor dekning)."""
    http_get = http_get or _http_get
    minx = math.floor(minx / res) * res
    miny = math.floor(miny / res) * res
    maxx = math.ceil(maxx / res) * res
    maxy = math.ceil(maxy / res) * res
    nk = int(round((maxx - minx) / res))
    nr = int(round((maxy - miny) / res))
    mosaikk = np.full((nr, nk), np.nan, dtype=np.float32)
    coverage = hent_coverage_navn()[0] if http_get is _http_get else "test"
    fliser = [(r0, c0) for r0 in range(0, nr, flis_px) for c0 in range(0, nk, flis_px)]
    for i, (r0, c0) in enumerate(fliser):
        h = min(flis_px, nr - r0)
        w = min(flis_px, nk - c0)
        fx0 = minx + c0 * res
        fy1 = maxy - r0 * res
        params = {
            "SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCoverage",
            "COVERAGE": coverage, "CRS": "EPSG:25833",
            "BBOX": "{},{},{},{}".format(fx0, fy1 - h * res, fx0 + w * res, fy1),
            "WIDTH": w, "HEIGHT": h, "FORMAT": "GeoTIFF",
        }
        if logg:
            logg("  Henter terrengflis {}/{} ({} x {} m)".format(i + 1, len(fliser), w * res, h * res))
        siste_feil = None
        for forsok in range(3):
            try:
                r = http_get(WCS_URL, params=params, timeout=60)
                if r.content[:1] == b"<":
                    raise Exception("WCS-feil: {}".format(r.content[:300]))
                data = _les_geotiff(r.content)
                break
            except Exception as ex:
                siste_feil = ex
                data = None
        if data is None:
            raise Exception("Kunne ikke hente terrengflis {}/{}: {}".format(i + 1, len(fliser), siste_feil))
        if data.shape != (h, w):
            raise Exception("Uventet flisstørrelse {} (forventet {})".format(data.shape, (h, w)))
        mosaikk[r0:r0 + h, c0:c0 + w] = data
    return mosaikk, minx, maxy, res


def _bilineaer_nan(data, x_venstre, y_topp, res, xs, ys):
    fc = (xs - x_venstre) / res - 0.5
    fr = (y_topp - ys) / res - 0.5
    c0 = np.floor(fc).astype(np.int64)
    r0 = np.floor(fr).astype(np.int64)
    nr, nk = data.shape
    ok = (c0 >= 0) & (r0 >= 0) & (c0 < nk - 1) & (r0 < nr - 1)
    c0 = np.clip(c0, 0, nk - 2)
    r0 = np.clip(r0, 0, nr - 2)
    tx = fc - c0
    ty = fr - r0
    v = (data[r0, c0] * (1 - tx) * (1 - ty) + data[r0, c0 + 1] * tx * (1 - ty)
         + data[r0 + 1, c0] * (1 - tx) * ty + data[r0 + 1, c0 + 1] * tx * ty)
    return np.where(ok, v, np.nan)


def terreng_til_rutenett(rn, intern_til_crs, crs_til_utm33, res_dtm=None, logg=None, http_get=None):
    """Henter DTM og resampler til rutenettet rn (Revit-intern meter).
    intern_til_crs(x, y) -> (E, N) i prosjektets koordinatsystem.
    Avbildningen intern -> UTM33 regnes eksakt i et kontrollnett hver ~50 m
    og interpoleres bilineaert mellom (feil << 1 mm over 50 m)."""
    res_dtm = res_dtm or rn.res
    ks = max(rn.res, 50.0)
    ncx = int(math.ceil((rn.nkol - 1) * rn.res / ks)) + 1
    ncy = int(math.ceil((rn.nrad - 1) * rn.res / ks)) + 1
    cx = rn.x0 + np.arange(ncx) * ks
    cy = rn.y0 + np.arange(ncy) * ks
    CX, CY = np.meshgrid(cx, cy)
    e, n = intern_til_crs(CX, CY)
    E33, N33 = crs_til_utm33(e, n)
    E33 = np.asarray(E33, float).reshape(CX.shape)
    N33 = np.asarray(N33, float).reshape(CX.shape)

    margin = 3 * res_dtm
    data, xv, yt, r = hent_dtm_utm33(E33.min() - margin, N33.min() - margin,
                                     E33.max() + margin, N33.max() + margin,
                                     res_dtm, logg=logg, http_get=http_get)
    if np.all(np.isnan(data)):
        raise Exception("Kartverket returnerte ingen gyldige høyder. Sjekk koordinatsystem og nullpunkt.")

    Z = np.empty(rn.form, dtype=np.float32)
    kol_x = rn.kolonne_x()
    fj = (kol_x - rn.x0) / ks
    j0 = np.clip(np.floor(fj).astype(np.int64), 0, ncx - 2)
    tx = fj - j0
    bunt = 256
    for i0 in range(0, rn.nrad, bunt):
        rad_y = rn.y0 + np.arange(i0, min(i0 + bunt, rn.nrad)) * rn.res
        fi = (rad_y - rn.y0) / ks
        ii = np.clip(np.floor(fi).astype(np.int64), 0, ncy - 2)
        ty = (fi - ii)[:, None]
        a, b = ii[:, None], j0[None, :]
        txb = tx[None, :]

        def interp(G):
            return (G[a, b] * (1 - txb) * (1 - ty) + G[a, b + 1] * txb * (1 - ty)
                    + G[a + 1, b] * (1 - txb) * ty + G[a + 1, b + 1] * txb * ty)
        xs = interp(E33)
        ys = interp(N33)
        Z[i0:i0 + len(rad_y)] = _bilineaer_nan(data, xv, yt, r, xs, ys)
    return Z
