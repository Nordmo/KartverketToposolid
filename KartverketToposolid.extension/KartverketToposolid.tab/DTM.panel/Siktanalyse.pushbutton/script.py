#! python3
# -*- coding: utf-8 -*-
"""
Innsyn - PyRevit-knapp
======================
Sjekker om stasjonen kan ses inn i over egne vegger, fra et rutenett av
observatørpunkter i terrenget rundt (høyeste punkt per celle +
øyehøyde). Hver vegg sjekkes for seg, mot sin egen topp.

Terreng: Kartverket DTM (1 m) for hele analyseområdet, med toposolidet
lagt oppå der det finnes. DTM-høyden justeres automatisk mot
toposolidet, så høydedatum trenger ikke oppgis.

Resultat:
  - Siktlinjer (modellinjer) for de verste observatørene per vegg:
    øyepunkt -> veggtopp -> dypeste synlige punkt inne i stasjonen.
  - Innsynskart: fargede ruter på terrenget der det er innsyn.
  - Rapport i pyRevit-konsollen og CSV ved siden av modellfilen.
Ny kjøring sletter forrige resultat.

Krever samme engangsoppsett som Lag Toposolid (numpy, rasterio, pyproj i
pyRevit sin CPython-motor). Bruker ikke WebView2.
"""

import os
import sys
import json
import math
import time
import datetime
import tempfile
import importlib
import traceback

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
try:
    clr.AddReference("System.Xaml")
except Exception:
    pass

import System
from System.Collections.Generic import List
from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult
from System.Windows.Markup import XamlReader

try:
    clr.AddReference("AdWindows")
    from Autodesk.Windows import ComponentManager
    _HAR_COMPONENT_MANAGER = True
except Exception:
    _HAR_COMPONENT_MANAGER = False

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, XYZ, Line,
    Plane, SketchPlane, Transaction, ElementId, Options, ViewDetailLevel,
    Solid, GeometryInstance, PlanarFace, Wall, LocationCurve, CurveElement,
    DirectShape, TessellatedShapeBuilder, TessellatedFace,
    TessellatedShapeBuilderTarget, TessellatedShapeBuilderFallback,
    Material, Color, GraphicsStyleType,
)
from Autodesk.Revit.UI.Selection import ObjectType

try:
    from Autodesk.Revit.DB import Toposolid
    _TOPOSOLID_OK = True
except Exception:
    _TOPOSOLID_OK = False

_DIR = os.path.dirname(__file__)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import numpy as np
import innsyn_kjerne as K
import innsyn_dtm as D
# pyRevit sin CPython-motor gjenbruker tolken mellom kjøringer:
# last modulene på nytt slik at endringer i filene tar effekt.
importlib.reload(K)
importlib.reload(D)

FT = 0.3048                      # Revit intern enhet = fot
APP_ID = "KartverketToposolid.Innsyn"
LINJESTIL_SIKT = "Innsyn - siktlinje"
LINJESTIL_INNE = "Innsyn - inn i stasjon"
MATERIAL_KLASSER = [            # (navn, fra dybde m, farge)
    ("Innsyn 0-0,5 m", 0.0, (255, 230, 0)),
    ("Innsyn 0,5-1 m", 0.5, (255, 150, 0)),
    ("Innsyn 1-2 m", 1.0, (230, 40, 0)),
    ("Innsyn over 2 m", 2.0, (140, 0, 30)),
]
_INNSTILLINGER = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()),
                              "KartverketToposolid", "innsyn.json")
STANDARD = {
    "crs": "NTM23", "radius": 2000.0, "res": 1.0, "celle": 10.0, "oye": 1.6,
    "avstand": 0.0, "minavst": 0.0, "pktavst": 1.0, "linjer": 5, "sektor": 30.0,
    "krumning": True, "kart": True,
}


def logg(tekst):
    print(tekst)
    try:
        sys.stdout.flush()   # pyRevit-konsollen viser framdrift underveis
    except Exception:
        pass


def melding(tekst, tittel="Innsyn", ikon=MessageBoxImage.Information):
    logg("[{}] {}".format(tittel, tekst))
    try:
        MessageBox.Show(tekst, tittel, MessageBoxButton.OK, ikon)
    except Exception:
        pass


def spor(tekst, tittel="Innsyn"):
    r = MessageBox.Show(tekst, tittel, MessageBoxButton.YesNo, MessageBoxImage.Warning)
    return r == MessageBoxResult.Yes


def id_tall(eid):
    try:
        return int(eid.Value)          # Revit 2024+
    except Exception:
        return int(eid.IntegerValue)


def les_innstillinger():
    s = dict(STANDARD)
    try:
        with open(_INNSTILLINGER, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    return s


def lagre_innstillinger(s):
    try:
        os.makedirs(os.path.dirname(_INNSTILLINGER), exist_ok=True)
        with open(_INNSTILLINGER, "w", encoding="utf-8") as f:
            json.dump({k: s[k] for k in STANDARD if k in s}, f, indent=2)
    except Exception:
        pass


# ======================================================================
#  Lese modellen
# ======================================================================

def hent_base_point(doc):
    """Samme logikk som Lag Toposolid: E/W, N/S-parametrene er nullpunkt,
    Position er punktets faktiske interne plassering."""
    bp = (FilteredElementCollector(doc)
          .OfCategory(BuiltInCategory.OST_ProjectBasePoint)
          .WhereElementIsNotElementType().FirstElement())
    if bp is None:
        raise Exception("Fant ikke Project Base Point i modellen.")
    e = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
    n = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
    e_m = e.AsDouble() * FT if e else 0.0
    n_m = n.AsDouble() * FT if n else 0.0
    p = bp.Position
    return e_m, n_m, (p.X * FT, p.Y * FT, p.Z * FT)


def _solider(geom):
    for g in geom:
        if isinstance(g, Solid):
            if g.Faces.Size > 0:
                yield g
        elif isinstance(g, GeometryInstance):
            for s in _solider(g.GetInstanceGeometry()):
                yield s


def _batch(topo):
    """Felles merke for toposolider laget i samme kjøring av Lag Toposolid
    (fliser), hentet fra Kommentarer: 'Kartverket-toposolid <tid> (flis k/n)'."""
    try:
        p = topo.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        t = (p.AsString() or "") if p else ""
    except Exception:
        t = ""
    if not t.startswith("Kartverket-toposolid"):
        return None
    return t.split(" (flis")[0]


def alle_toposolider(doc):
    try:
        return list(FilteredElementCollector(doc).OfClass(Toposolid).WhereElementIsNotElementType())
    except Exception:
        return [e for e in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Toposolid)
                .WhereElementIsNotElementType() if isinstance(e, Toposolid)]


def med_sosken(doc, valgte):
    """Legger til de andre flisene fra samme kjøring av Lag Toposolid."""
    batcher = set(b for b in (_batch(t) for t in valgte) if b)
    ut = dict((id_tall(t.Id), t) for t in valgte)
    if batcher:
        for t in alle_toposolider(doc):
            if _batch(t) in batcher:
                ut[id_tall(t.Id)] = t
    return list(ut.values())


def toposolid_trekanter(toposolider):
    if not isinstance(toposolider, (list, tuple)):
        toposolider = [toposolider]
    deler = [_toposolid_trekanter(t) for t in toposolider]
    return np.concatenate(deler, axis=0)


def _toposolid_trekanter(topo):
    """Triangulerer toposolidets flater (unntatt plane flater som vender
    ned/til siden). Returnerer (T,3,3) i meter, intern."""
    opts = Options()
    opts.DetailLevel = ViewDetailLevel.Fine
    tri = []
    for solid in _solider(topo.get_Geometry(opts)):
        for face in solid.Faces:
            if isinstance(face, PlanarFace) and face.FaceNormal.Z < 0.01:
                continue
            mesh = face.Triangulate()
            v = np.array([(p.X, p.Y, p.Z) for p in mesh.Vertices], dtype=float) * FT
            nt = mesh.NumTriangles
            idx = np.empty((nt, 3), dtype=np.int64)
            for t in range(nt):
                mt = mesh.get_Triangle(t)
                idx[t, 0] = mt.get_Index(0)
                idx[t, 1] = mt.get_Index(1)
                idx[t, 2] = mt.get_Index(2)
            if nt:
                tri.append(v[idx])
    if not tri:
        raise Exception("Fant ingen geometri i toposolidet.")
    return np.concatenate(tri, axis=0)


def _navn(el):
    try:
        mrk = el.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mrk and mrk.AsString():
            return "{} (merke {})".format(id_tall(el.Id), mrk.AsString())
    except Exception:
        pass
    return str(id_tall(el.Id))


def element_linjedata(el):
    """Senterlinje (polylinje, m), bredde (m), topp/bunn (m) for en vegg
    eller et linjebasert element. Returnerer (data, advarsel)."""
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None, "Element {} har ingen geometri - hoppet over.".format(id_tall(el.Id))
    topp, bunn = bb.Max.Z * FT, bb.Min.Z * FT
    advarsel = None
    loc = el.Location
    if isinstance(loc, LocationCurve):
        kurve = loc.Curve
        pts = np.array([(p.X * FT, p.Y * FT) for p in kurve.Tessellate()])
        bredde = 0.0
        if isinstance(el, Wall):
            bredde = el.Width * FT
            # Lokasjonslinjen er ikke alltid senterlinjen. Forskyv til senter.
            # 0/1 = (kjerne)senter, 2/4 = utvendig flate, 3/5 = innvendig flate.
            # Kjerneflater tilnærmes som ferdige flater.
            try:
                ref = el.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM).AsInteger()
            except Exception:
                ref = 0
            faktor = {2: -0.5, 4: -0.5, 3: 0.5, 5: 0.5}.get(ref, 0.0)
            if faktor and isinstance(kurve, Line):
                o = el.Orientation
                pts = pts + np.array([o.X, o.Y]) * faktor * bredde
            elif faktor:
                advarsel = ("Vegg {}: buet vegg med lokasjonslinje på flate - ikke "
                            "forskjøvet til senter (avvik <= halv tykkelse).".format(id_tall(el.Id)))
    else:
        # Fallback: aksejustert omriss av bounding box
        x0, y0, x1, y1 = bb.Min.X * FT, bb.Min.Y * FT, bb.Max.X * FT, bb.Max.Y * FT
        pts = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
        bredde = 0.0
        advarsel = ("Element {} er ikke linjebasert - bruker bounding box som "
                    "skjerm (grovt).".format(id_tall(el.Id)))
    return {"id": id_tall(el.Id), "navn": _navn(el), "polyline": pts,
            "bredde": bredde, "topp": topp, "bunn": bunn}, advarsel


# ======================================================================
#  Dialog
# ======================================================================

_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Innsyn - siktanalyse" Width="520" SizeToContent="Height"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        FontFamily="Segoe UI" FontSize="12">
  <StackPanel Margin="14">
    <TextBlock FontWeight="Bold" FontSize="13" Margin="0,0,0,6">1. Utvalg i modellen</TextBlock>
    <TextBlock x:Name="txtUtvalg" TextWrapping="Wrap" Margin="0,0,0,6"/>
    <WrapPanel Margin="0,0,0,10">
      <Button x:Name="btnTopo" Content="Velg toposolid" Padding="8,3" Margin="0,0,6,0"/>
      <Button x:Name="btnVegger" Content="Velg vegger å sjekke" Padding="8,3" Margin="0,0,6,0"/>
      <Button x:Name="btnSkjerm" Content="Velg ekstra skjerming" Padding="8,3" Margin="0,0,6,0"/>
      <Button x:Name="btnNullSkjerm" Content="Fjern skjerming" Padding="8,3"/>
    </WrapPanel>

    <TextBlock FontWeight="Bold" FontSize="13" Margin="0,0,0,6">2. Koordinater (som i Lag Toposolid)</TextBlock>
    <Grid Margin="0,0,0,10">
      <Grid.ColumnDefinitions><ColumnDefinition Width="220"/><ColumnDefinition/></Grid.ColumnDefinitions>
      <Grid.RowDefinitions><RowDefinition/><RowDefinition/><RowDefinition/></Grid.RowDefinitions>
      <TextBlock Grid.Row="0" Text="Koordinatsystem" VerticalAlignment="Center"/>
      <ComboBox Grid.Row="0" Grid.Column="1" x:Name="cbCrs" Margin="0,2"/>
      <TextBlock Grid.Row="1" Text="Nullpunkt E (Project Base Point)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="1" Grid.Column="1" x:Name="tbNullE" Margin="0,2"/>
      <TextBlock Grid.Row="2" Text="Nullpunkt N (Project Base Point)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="2" Grid.Column="1" x:Name="tbNullN" Margin="0,2"/>
    </Grid>

    <TextBlock FontWeight="Bold" FontSize="13" Margin="0,0,0,6">3. Analyse</TextBlock>
    <Grid Margin="0,0,0,6">
      <Grid.ColumnDefinitions><ColumnDefinition Width="320"/><ColumnDefinition/></Grid.ColumnDefinitions>
      <Grid.RowDefinitions>
        <RowDefinition/><RowDefinition/><RowDefinition/><RowDefinition/><RowDefinition/>
        <RowDefinition/><RowDefinition/><RowDefinition/><RowDefinition/>
      </Grid.RowDefinitions>
      <TextBlock Grid.Row="0" Text="Øyehøyde over terreng (m)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="0" Grid.Column="1" x:Name="tbOye" Margin="0,2"/>
      <TextBlock Grid.Row="1" Text="Tillatt innsyn under veggtopp (m)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="1" Grid.Column="1" x:Name="tbAvstand" Margin="0,2"/>
      <TextBlock Grid.Row="2" Text="Analyseradius fra stasjonen (m)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="2" Grid.Column="1" x:Name="tbRadius" Margin="0,2"/>
      <TextBlock Grid.Row="3" Text="Observatørrutenett (m)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="3" Grid.Column="1" x:Name="tbCelle" Margin="0,2"/>
      <TextBlock Grid.Row="4" Text="Terrengoppløsning (m, 1 = full DTM1)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="4" Grid.Column="1" x:Name="tbRes" Margin="0,2"/>
      <TextBlock Grid.Row="5" Text="Minsteavstand observatør - stasjon (m)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="5" Grid.Column="1" x:Name="tbMinAvst" Margin="0,2"/>
      <TextBlock Grid.Row="6" Text="Punktavstand langs veggtopp (m)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="6" Grid.Column="1" x:Name="tbPktAvst" Margin="0,2"/>
      <TextBlock Grid.Row="7" Text="Antall siktlinjer per vegg (verste)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="7" Grid.Column="1" x:Name="tbLinjer" Margin="0,2"/>
      <TextBlock Grid.Row="8" Text="Min. vinkel mellom siktlinjer (grader)" VerticalAlignment="Center"/>
      <TextBox Grid.Row="8" Grid.Column="1" x:Name="tbSektor" Margin="0,2"/>
    </Grid>
    <CheckBox x:Name="chkKrumning" Content="Jordkrumning og refraksjon (k = 0,13)" Margin="0,2"/>
    <CheckBox x:Name="chkKart" Content="Lag innsynskart (fargede ruter i terrenget)" Margin="0,2,0,10"/>
    <TextBlock TextWrapping="Wrap" Foreground="#666" Margin="0,0,0,10">
      Terreng: Kartverket DTM (bart terreng, uten vegetasjon og bygg), med toposolidet lagt oppå.
      Sjekker om innerflaten på de valgte veggene kan ses lavere enn «tillatt innsyn» under toppen,
      over de andre veggene i stasjonen. Resten av stasjonen finnes automatisk.
      Åpninger/porter vurderes ikke. Forrige resultat slettes ved ny kjøring.
    </TextBlock>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btnKjor" Content="Kjør analyse" Padding="14,4" Margin="0,0,8,0" IsDefault="True"/>
      <Button x:Name="btnAvbryt" Content="Avbryt" Padding="14,4" IsCancel="True"/>
    </StackPanel>
  </StackPanel>
</Window>
"""

_FELT = [("tbOye", "oye"), ("tbAvstand", "avstand"), ("tbRadius", "radius"),
         ("tbCelle", "celle"), ("tbRes", "res"), ("tbMinAvst", "minavst"),
         ("tbPktAvst", "pktavst"), ("tbLinjer", "linjer"), ("tbSektor", "sektor"),
         ("tbNullE", "null_e"), ("tbNullN", "null_n")]


def _tekst_tall(v):
    if isinstance(v, float):
        return ("%.4f" % v).rstrip("0").rstrip(".") if abs(v) < 1e5 else "%.4f" % v
    return str(v)


def vis_dialog(state):
    w = XamlReader.Parse(_XAML)
    if _HAR_COMPONENT_MANAGER:
        try:
            import System.Windows.Interop as _interop
            _interop.WindowInteropHelper(w).Owner = ComponentManager.ApplicationWindow
        except Exception:
            pass
    f = lambda navn: w.FindName(navn)

    topo = state.get("topo") or []
    linjer = ["Toposolid: {}".format(
                  "IKKE VALGT" if not topo else
                  "id {}".format(id_tall(topo[0].Id)) if len(topo) == 1 else
                  "{} fliser fra Lag Toposolid".format(len(topo))),
              "Vegger som sjekkes for innsyn: {}".format(len(state["vegger"]) or "INGEN VALGT"),
              "Ekstra skjerming: {}".format(len(state["skjerm"]))]
    f("txtUtvalg").Text = "\n".join(linjer)

    cb = f("cbCrs")
    for kode, _, navn in D.KOORDINATSYSTEMER:
        cb.Items.Add("{} - {}".format(kode, navn))
    koder = [k for k, _, _ in D.KOORDINATSYSTEMER]
    cb.SelectedIndex = koder.index(state["crs"]) if state["crs"] in koder else koder.index("NTM23")
    for tb, nokkel in _FELT:
        f(tb).Text = _tekst_tall(state[nokkel])
    f("chkKrumning").IsChecked = bool(state["krumning"])
    f("chkKart").IsChecked = bool(state["kart"])

    resultat = {"handling": "avbryt"}

    def les_inn():
        state["crs"] = koder[cb.SelectedIndex] if cb.SelectedIndex >= 0 else "NTM23"
        for tb, nokkel in _FELT:
            state["_tekst_" + nokkel] = f(tb).Text
        state["krumning"] = bool(f("chkKrumning").IsChecked)
        state["kart"] = bool(f("chkKart").IsChecked)

    def lag_handler(handling):
        def h(sender, args):
            les_inn()
            resultat["handling"] = handling
            w.Close()
        return h

    for knapp, handling in [("btnTopo", "topo"), ("btnVegger", "vegger"),
                            ("btnSkjerm", "skjerm"), ("btnNullSkjerm", "nullskjerm"),
                            ("btnKjor", "kjor")]:
        f(knapp).Click += lag_handler(handling)
    w.ShowDialog()
    return resultat["handling"]


def tolk_tall(state):
    """Gjør om tekstfeltene til tall. Returnerer liste med feil."""
    feil = []
    for _, nokkel in _FELT:
        tekst = state.pop("_tekst_" + nokkel, None)
        if tekst is None:
            continue
        try:
            v = float(tekst.strip().replace(" ", "").replace(",", "."))
            state[nokkel] = int(round(v)) if nokkel == "linjer" else v
        except Exception:
            feil.append("Ugyldig tall i feltet '{}': {}".format(nokkel, tekst))
    regler = [("oye", 0, 100), ("avstand", 0, 50), ("radius", 50, 10000), ("celle", 1, 200),
              ("res", 0.5, 20), ("minavst", 0, 5000), ("pktavst", 0.1, 20), ("linjer", 0, 100),
              ("sektor", 1, 360)]
    etikett = {"oye": "Øyehøyde", "avstand": "Tillatt innsyn under veggtopp",
               "radius": "Analyseradius", "celle": "Observatørrutenett",
               "res": "Terrengoppløsning", "minavst": "Minsteavstand",
               "pktavst": "Punktavstand langs veggtopp", "linjer": "Antall siktlinjer",
               "sektor": "Min. vinkel mellom siktlinjer"}
    for n, lo, hi in regler:
        if not (lo <= state[n] <= hi):
            feil.append("{} må være mellom {} og {}.".format(etikett[n], lo, hi))
    if not feil and state["celle"] < state["res"]:
        feil.append("Observatørrutenettet kan ikke være finere enn terrengoppløsningen.")
    if not feil and (state["radius"] * 2 / state["res"]) ** 2 > 60e6:
        feil.append("For stort rutenett ({:.0f} mill. celler). Øk terrengoppløsningen "
                    "eller reduser radius.".format((state["radius"] * 2 / state["res"]) ** 2 / 1e6))
    return feil


def plukk(uidoc, melding_tekst, flere=True):
    try:
        if flere:
            refs = uidoc.Selection.PickObjects(ObjectType.Element, melding_tekst)
            return [uidoc.Document.GetElement(r.ElementId) for r in refs]
        r = uidoc.Selection.PickObject(ObjectType.Element, melding_tekst)
        return [uidoc.Document.GetElement(r.ElementId)]
    except Exception as ex:
        if "OperationCanceled" in "{} {}".format(type(ex).__name__, ex):
            return None
        raise


# ======================================================================
#  Analyse
# ======================================================================

def kjor_analyse(doc, state, bp):
    t0 = time.time()
    null_e, null_n = state["null_e"], state["null_n"]
    bpx, bpy, bpz = bp
    res, R, celle = state["res"], state["radius"], state["celle"]

    def intern_til_crs(x, y):
        return null_e + (x - bpx), null_n + (y - bpy)

    advarsler = []
    vegger = []
    for el in state["vegger"]:
        d, adv = element_linjedata(el)
        if adv:
            advarsler.append(adv)
        if d:
            vegger.append(d)
    if not vegger:
        raise Exception("Ingen gyldige stasjonsvegger.")
    skjerm = []
    for el in state["skjerm"]:
        d, adv = element_linjedata(el)
        if adv:
            advarsler.append(adv)
        if d:
            skjerm.append(d)

    # Alle vegger i området: de er fysiske hindringer, og de som henger
    # sammen med de valgte veggene utgjør stasjonen (avgjør hva som er inne).
    valgt_senter = np.vstack([v["polyline"] for v in vegger]).mean(axis=0)
    valgte_ids = set(v["id"] for v in vegger)
    alle_vegger = list(vegger)
    for el in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        if id_tall(el.Id) in valgte_ids:
            continue
        try:
            d, _ = element_linjedata(el)
        except Exception:
            d = None
        if d is None or not isinstance(el.Location, LocationCurve):
            continue
        if np.hypot(*(d["polyline"] - valgt_senter).T).min() <= R + 100.0:
            alle_vegger.append(d)
    nett_ids = K.finn_stasjonsnett(alle_vegger, valgte_ids)
    nettvegger = [v for v in alle_vegger if v["id"] in nett_ids]
    logg("Stasjon: {} valgte vegger, {} vegger i stasjonen totalt (funnet via hjørner/T-koblinger), "
         "{} vegger i området".format(len(vegger), len(nettvegger), len(alle_vegger)))

    # Utsiden av hver valgt vegg. Innervegger og frittstående vegger hoppes over.
    sjekkes = []
    for v in vegger:
        v["lag"] = K.lagvegger(v, nettvegger)
        normal, status, andeler = K.utside_normal(v, nettvegger, lag_ids=v["lag"])
        logg("Vegg {}: {} lagvegg(er) i samme linje (fundament/vanger), innelukket {:.0%} / {:.0%} "
             "på hver side -> {}".format(v["navn"], len(v["lag"]), andeler[0], andeler[1],
                                          "utside funnet" if normal is not None else status))
        if normal is None:
            hva = {"innervegg": "er en innervegg (innelukket på begge sider)",
                   "ikke innelukket": "omslutter ikke noe (åpen på begge sider) - "
                                      "velg vegger som henger sammen med resten av stasjonen"}.get(status, status)
            advarsler.append("Vegg {} {} og ble ikke sjekket.".format(v["navn"], hva))
            continue
        v["utside"] = normal
        sjekkes.append(v)
    if not sjekkes:
        raise Exception("Ingen av de valgte veggene er yttervegger i en innelukket stasjon.\n\n"
                        + "\n".join(advarsler))

    hull = K.konveks_hull(np.vstack([v["polyline"] for v in nettvegger]))
    senter = hull.mean(axis=0)
    rn = K.Rutenett.rundt(senter[0], senter[1], R + 100.0, res)
    logg("Analyseområde: radius {:.0f} m, rutenett {} x {} ({:.1f} mill. celler)".format(
        R, rn.nrad, rn.nkol, rn.nrad * rn.nkol / 1e6))

    logg("Leser toposolid ...")
    t = time.time()
    tri = toposolid_trekanter(state["topo"])
    Ztopo = K.rasteriser_i_utsnitt(rn, tri)
    logg("  {} trekanter, {:.1f} s".format(len(tri), time.time() - t))

    logg("Henter terreng fra Kartverket ({}) ...".format(state["crs"]))
    epsg = dict((k, e) for k, e, _ in D.KOORDINATSYSTEMER)[state["crs"]]
    Zdtm = D.terreng_til_rutenett(rn, intern_til_crs, D.crs_til_utm33_funksjon(epsg),
                                  res_dtm=res, logg=logg)

    try:
        H, gyldig, dz, mad, n_over = K.bygg_terreng(Ztopo, Zdtm)
    except ValueError:
        raise Exception("Toposolidet overlapper ikke terrenget fra Kartverket. Sjekk "
                        "koordinatsystem og nullpunkt (skal være de samme som da "
                        "toposolidet ble laget).")
    logg("Høydetilpasning mot toposolid: dz = {:+.3f} m, spredning (MAD) {:.3f} m, {} celler".format(
        dz, mad, n_over))
    if mad > 1.0:
        if not spor("Toposolidet og Kartverket-terrenget stemmer dårlig overens "
                    "(median avvik {:.2f} m etter høydetilpasning).\n\nDet tyder på feil "
                    "koordinatsystem/nullpunkt, eller et kraftig bearbeidet toposolid.\n\n"
                    "Fortsette likevel?".format(mad)):
            return None
    elif mad > 0.3:
        advarsler.append("Toposolid og DTM avviker en del (MAD {:.2f} m) - sjekk at "
                         "toposolidet er laget med samme koordinater.".format(mad))
    del Ztopo, Zdtm

    obs = K.lag_observatorer(rn, H, gyldig, celle, senter, R, hull,
                             state["minavst"], state["oye"])
    logg("Observatørpunkter: {}".format(obs["x"].size))

    A, B, T, E = [], [], [], []
    for v in alle_vegger:
        a, b, tt, e = K.fotavtrykk_segmenter(v["polyline"], v["bredde"], v["topp"], v["id"])
        A += a; B += b; T += tt; E += e
    for s in skjerm:
        a, b, tt, e = K.fotavtrykk_segmenter(s["polyline"], s["bredde"], s["topp"], "skjerm_{}".format(s["id"]))
        A += a; B += b; T += tt; E += e
    hind = {"A": np.array(A).reshape(-1, 2), "B": np.array(B).reshape(-1, 2),
            "topp": np.array(T), "eier": E}

    n_str = K.antall_straaler(R, celle)
    # Målpunktene på innerflaten starter et stykke inn fra endene, slik at
    # de ligger på selve veggen og ikke i hjørnet mot naboveggen.
    innfelling = max(0.5, 0.5 * max(v["bredde"] for v in nettvegger) + 0.1)
    etter_id = dict((w["id"], w) for w in nettvegger)
    resultater = []
    for i, v in enumerate(sjekkes):
        logg("Vegg {}/{}: {} (topp {:.2f}) ...".format(i + 1, len(sjekkes), v["navn"], v["topp"] - bpz))
        t = time.time()
        innside = (-v["utside"][0], -v["utside"][1])
        flate = K.innerflate_avstand(v, [etter_id[l] for l in v["lag"] if l in etter_id], innside)
        r = K.analyser_vegg(rn, H, v, hind, obs, res, n_str, state["pktavst"],
                            innside, state["avstand"], nett_ids=nett_ids, lag_ids=v["lag"],
                            flate_avstand=flate, krumning_paa=state["krumning"],
                            innfelling=innfelling, logg=logg)
        dg = r["diagnose"]
        logg("  {} målpunkter på innerflaten. Observatører som står slik at de kan se innerflaten: {}, "
             "som ser den {:.2f} m under toppen: {}, med innsyn: {}".format(
                 r["n_punkter"], dg["paa_innsiden"], state["avstand"], dg["ser_kontrollhoyden"], dg["innsyn"]))
        r["vegg"] = v
        resultater.append(r)
        logg("  ferdig på {:.1f} s".format(time.time() - t))

    logg("Beregning ferdig på {:.0f} s".format(time.time() - t0))
    return {"obs": obs, "res": resultater, "advarsler": advarsler, "dz": dz, "mad": mad,
            "hull": hull, "intern_til_crs": intern_til_crs, "bpz": bpz,
            "n_nett": len(nettvegger), "n_omraade": len(alle_vegger)}


# ======================================================================
#  Skrive resultat til modellen
# ======================================================================

def _xyz(p):
    return XYZ(p[0] / FT, p[1] / FT, p[2] / FT)


def slett_forrige(doc):
    ids = List[ElementId]()
    plan = set()
    for ds in FilteredElementCollector(doc).OfClass(DirectShape):
        try:
            if ds.ApplicationId == APP_ID:
                ids.Add(ds.Id)
        except Exception:
            pass
    for ce in FilteredElementCollector(doc).OfClass(CurveElement):
        try:
            if ce.LineStyle is not None and ce.LineStyle.Name in (LINJESTIL_SIKT, LINJESTIL_INNE):
                ids.Add(ce.Id)
                if ce.SketchPlane is not None:
                    plan.add(id_tall(ce.SketchPlane.Id))
        except Exception:
            pass
    n = ids.Count
    if n:
        doc.Delete(ids)
    for p in plan:          # arbeidsplanene vi laget - ufarlig hvis de er i bruk
        try:
            doc.Delete(ElementId(p))
        except Exception:
            pass
    return n


def linjestil(doc, navn, farge, tykkelse):
    cats = doc.Settings.Categories
    linjer = cats.get_Item(BuiltInCategory.OST_Lines)
    sub = None
    for c in linjer.SubCategories:
        if c.Name == navn:
            sub = c
            break
    if sub is None:
        sub = cats.NewSubcategory(linjer, navn)
        sub.LineColor = Color(*farge)
        sub.SetLineWeight(tykkelse, GraphicsStyleType.Projection)
    return sub.GetGraphicsStyle(GraphicsStyleType.Projection)


def material(doc, navn, farge):
    for m in FilteredElementCollector(doc).OfClass(Material):
        if m.Name == navn:
            return m.Id
    mid = Material.Create(doc, navn)
    m = doc.GetElement(mid)
    m.Color = Color(*farge)
    try:
        m.UseRenderAppearanceForShading = False
    except Exception:
        pass
    return mid


def modell_linje(doc, p1, p2, stil, kommentar):
    a, b = _xyz(p1), _xyz(p2)
    if a.DistanceTo(b) < 0.01:
        return
    d = b.Subtract(a).Normalize()
    n = d.CrossProduct(XYZ.BasisZ)
    if n.GetLength() < 1e-6:
        n = XYZ.BasisX
    sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(n.Normalize(), a))
    mc = doc.Create.NewModelCurve(Line.CreateBound(a, b), sp)
    mc.LineStyle = stil
    p = mc.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and not p.IsReadOnly:
        p.Set(kommentar)


def innsynskart(doc, obs, dybde, terskel):
    """En DirectShape per fargeklasse med en flat rute per observatørcelle."""
    halv = obs["celle"] * 0.45
    teller = 0
    for k, (navn, fra, farge) in enumerate(MATERIAL_KLASSER):
        til = MATERIAL_KLASSER[k + 1][1] if k + 1 < len(MATERIAL_KLASSER) else 1e9
        idx = np.nonzero((dybde > terskel) & (dybde > fra) & (dybde <= til))[0]
        if idx.size == 0:
            continue
        mid = material(doc, navn, farge)
        b = TessellatedShapeBuilder()
        for i in idx:
            cx, cy, z = obs["cx"][i], obs["cy"][i], obs["zbakke"][i] + 0.3
            pts = List[XYZ]()
            for dx, dy in ((-halv, -halv), (halv, -halv), (halv, halv), (-halv, halv)):
                pts.Add(_xyz((cx + dx, cy + dy, z)))
            b.OpenConnectedFaceSet(False)
            b.AddFace(TessellatedFace(pts, mid))
            b.CloseConnectedFaceSet()
        b.Target = TessellatedShapeBuilderTarget.Mesh
        b.Fallback = TessellatedShapeBuilderFallback.Salvage
        b.Build()
        ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
        ds.ApplicationId = APP_ID
        ds.ApplicationDataId = "innsynskart"
        ds.SetShape(b.GetBuildResult().GetGeometricalObjects())
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p is not None:
            p.Set("Innsynskart: {}".format(navn))
        teller += idx.size
    return teller


def skriv_resultat(doc, state, an):
    obs, terskel, bpz = an["obs"], state["avstand"], an["bpz"]
    til_crs = an["intern_til_crs"]
    t = Transaction(doc, "Innsynsanalyse")
    t.Start()
    try:
        slettet = slett_forrige(doc)
        stil_sikt = linjestil(doc, LINJESTIL_SIKT, (220, 0, 0), 5)
        stil_inne = linjestil(doc, LINJESTIL_INNE, (140, 0, 140), 7)
        n_linjer = 0
        for r in an["res"]:
            v = r["vegg"]
            verst = K.velg_siktlinjer(obs, r, terskel, state["linjer"], state.get("sektor", 30.0))
            for i in verst:
                O, P, T = K.siktlinje(obs, r, i)
                avst = math.hypot(T[0] - O[0], T[1] - O[1])
                e, n = til_crs(O[0], O[1])
                kom = "Innsyn mot vegg {}: ser {:.2f} m under topp, avstand {:.0f} m, obs E {:.1f} N {:.1f}".format(
                    v["navn"], r["dybde"][i], avst, e, n)
                modell_linje(doc, O, P, stil_sikt, kom)
                modell_linje(doc, P, T, stil_inne, kom)
                n_linjer += 1
        n_ruter = 0
        if state["kart"]:
            dmax = np.max(np.vstack([r["dybde"] for r in an["res"]]), axis=0)
            n_ruter = innsynskart(doc, obs, dmax, terskel)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return slettet, n_linjer, n_ruter


def rapport(doc, state, an, slettet, n_linjer, n_ruter):
    obs, terskel, bpz = an["obs"], state["avstand"], an["bpz"]
    til_crs = an["intern_til_crs"]
    logg("")
    logg("=" * 78)
    logg("INNSYNSANALYSE  {}".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    logg("Koordinatsystem {}, øyehøyde {:.2f} m, tillatt innsyn under topp {:.2f} m".format(
        state["crs"], state["oye"], terskel))
    logg("Radius {:.0f} m, observatørrutenett {:.0f} m, terreng {:.1f} m, krumning {}".format(
        state["radius"], state["celle"], state["res"], "på" if state["krumning"] else "av"))
    logg("Observatørpunkter: {}. DTM justert {:+.3f} m mot toposolidet.".format(obs["x"].size, an["dz"]))
    logg("Stasjonen: {} vegger (valgte + tilkoblede). Alle {} vegger i området er med som hindringer.".format(
        an["n_nett"], an["n_omraade"]))
    logg("Terreng = DTM + toposolid. Vegetasjon og bygg som ikke er modellert som vegger, er ikke med.")
    logg("-" * 78)
    tabell = []
    for r in an["res"]:
        v = r["vegg"]
        d = r["dybde"]
        i = int(np.argmax(d))
        n_inn = int((d > terskel).sum())
        rad = {"vegg": v["navn"], "topp": v["topp"] - bpz, "maks": float(d[i]), "n": n_inn}
        if d[i] > 0:
            O, _, T = K.siktlinje(obs, r, i)
            e, n = til_crs(O[0], O[1])
            rad.update({"e": e, "n_": n, "z": O[2] - bpz, "avst": math.hypot(T[0] - O[0], T[1] - O[1])})
        tabell.append(rad)
        status = "INNSYN" if n_inn else "ok"
        tekst = "Vegg {:<22} topp {:8.2f}  {:6}  ser ned til {:5.2f} m under topp".format(
            v["navn"], rad["topp"], status, rad["maks"])
        if "e" in rad:
            tekst += "  fra E {:.1f} N {:.1f} kote {:.1f} ({:.0f} m)  celler: {}".format(
                rad["e"], rad["n_"], rad["z"], rad["avst"], n_inn)
        logg(tekst)
    logg("-" * 78)
    logg("Slettet {} elementer fra forrige kjøring. Tegnet {} siktlinjer, {} ruter i innsynskart.".format(
        slettet, n_linjer, n_ruter))
    logg("Siktlinjer: de som ser lengst ned, minst {:.0f} grader fra hverandre i retning, maks {} per vegg.".format(
        state.get("sektor", 30.0), state["linjer"]))
    logg("Innsynskart: rute i hver observatørcelle som ser lenger ned enn {:.2f} m under toppen på minst én "
         "valgt vegg. Farge = hvor langt ned (verste vegg): gul 0-0,5 m, oransje 0,5-1 m, rød 1-2 m, "
         "mørkerød over 2 m.".format(terskel))
    for a in an["advarsler"]:
        logg("ADVARSEL: " + a)

    # CSV (semikolon + desimalkomma for norsk Excel)
    mappe = os.path.dirname(doc.PathName) if doc.PathName else tempfile.gettempdir()
    sti = os.path.join(mappe, "Innsyn_{}.csv".format(datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
    kom = lambda x: ("%.3f" % x).replace(".", ",")
    try:
        with open(sti, "w", encoding="utf-8-sig") as f:
            f.write("vegg;veggtopp_kote;obs_E;obs_N;øye_kote;bakke_kote;avstand_m;dybde_under_topp_m\n")
            for r in an["res"]:
                v = r["vegg"]
                for i in np.nonzero(r["dybde"] > terskel)[0]:
                    e, n = til_crs(obs["x"][i], obs["y"][i])
                    avst = math.hypot(r["px"][i] - obs["x"][i], r["py"][i] - obs["y"][i])
                    f.write(";".join([v["navn"], kom(v["topp"] - bpz), kom(e), kom(n),
                                      kom(obs["z"][i] - bpz), kom(obs["zbakke"][i] - bpz),
                                      kom(avst), kom(r["dybde"][i])]) + "\n")
        logg("CSV: {}".format(sti))
    except Exception as ex:
        logg("Kunne ikke skrive CSV ({}): {}".format(sti, ex))
        sti = None
    return tabell, sti


# ======================================================================
#  Hovedflyt
# ======================================================================

def main():
    uidoc = __revit__.ActiveUIDocument
    doc = uidoc.Document
    if not _TOPOSOLID_OK:
        melding("Toposolid finnes ikke i denne Revit-versjonen (krever 2024+).", ikon=MessageBoxImage.Error)
        return
    null_e, null_n, bp = hent_base_point(doc)
    state = les_innstillinger()
    state.update({"null_e": null_e, "null_n": null_n, "topo": [], "vegger": [], "skjerm": []})

    # Forhåndsvalg: toposolid(er) + vegger merket før knappen ble trykket
    for eid in uidoc.Selection.GetElementIds():
        el = doc.GetElement(eid)
        if isinstance(el, Toposolid):
            state["topo"].append(el)
        elif isinstance(el, Wall):
            state["vegger"].append(el)
    if state["topo"]:
        state["topo"] = med_sosken(doc, state["topo"])
    else:
        # Automatisk: ett toposolid, eller alle fliser fra én kjøring
        alle = alle_toposolider(doc)
        batcher = set(_batch(t) for t in alle)
        if len(alle) == 1 or (len(batcher) == 1 and None not in batcher):
            state["topo"] = alle

    while True:
        handling = vis_dialog(state)
        if handling == "avbryt":
            return
        if handling == "topo":
            el = plukk(uidoc, "Velg toposolidet (én flis holder - resten fra samme kjøring tas med) og trykk Finish")
            if el is not None:
                topo = [e for e in el if isinstance(e, Toposolid)]
                if topo:
                    state["topo"] = med_sosken(doc, topo)
                else:
                    melding("Ingen av de valgte elementene er toposolider.")
        elif handling == "vegger":
            el = plukk(uidoc, "Velg veggene du vil sjekke for innsyn og trykk Finish (Fullfør)")
            if el is not None:
                vegger = [e for e in el if isinstance(e, Wall)]
                if len(vegger) < len(el):
                    melding("{} av de valgte elementene er ikke vegger og ble utelatt.".format(len(el) - len(vegger)))
                state["vegger"] = vegger
        elif handling == "skjerm":
            el = plukk(uidoc, "Velg ekstra skjerming (gjerder, skjermvegger) og trykk Finish")
            if el is not None:
                ids = set(id_tall(v.Id) for v in state["vegger"])
                state["skjerm"] = [e for e in el if id_tall(e.Id) not in ids]
        elif handling == "nullskjerm":
            state["skjerm"] = []
        if handling != "kjor":
            tolk_tall(state)
            continue
        feil = tolk_tall(state)
        if not state["topo"]:
            feil.append("Velg et toposolid.")
        if len(state["vegger"]) < 2:
            feil.append("Velg minst to stasjonsvegger (som danner innhegningen).")
        if feil:
            melding("\n".join(feil), ikon=MessageBoxImage.Warning)
            continue
        break

    lagre_innstillinger(state)
    an = kjor_analyse(doc, state, bp)
    if an is None:
        return
    slettet, n_linjer, n_ruter = skriv_resultat(doc, state, an)
    tabell, sti = rapport(doc, state, an, slettet, n_linjer, n_ruter)

    linjer = []
    for rad in tabell:
        linjer.append("Vegg {}: {}".format(
            rad["vegg"], "INNSYN, {:.2f} m under topp ({} celler)".format(rad["maks"], rad["n"])
            if rad["n"] else "ikke innsyn (maks {:.2f} m)".format(rad["maks"])))
    melding("\n".join(linjer) + "\n\nSe pyRevit-konsollen for detaljer." +
            ("\nCSV: {}".format(sti) if sti else ""), "Innsyn - resultat")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logg(traceback.format_exc())
        melding("Innsynsanalysen feilet:\n\n{}\n\nSe pyRevit-konsollen for full traceback.".format(e),
                "Innsyn - feil", MessageBoxImage.Error)
