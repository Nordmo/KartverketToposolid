# -*- coding: utf-8 -*-
"""
Innsyn - beregningskjerne
=========================
Ren numpy, ingen Revit-avhengigheter, slik at den kan testes utenfor Revit.

Alle koordinater er i meter i Revit sitt interne koordinatsystem
(intern fot * 0.3048). Z er intern Z i meter.

Metode (per stasjonsvegg, hver vegg for seg):
  1. Punkter P legges langs veggens topp (lokasjonslinje, kote = veggtopp).
  2. Fra hvert P regnes en radiell horisont utover: terrengvinkel langs
     hver stråle (bilineaer sampling av hoyderutenettet), pluss
     analytiske hindringer (vegger/skjermer som linjesegmenter med
     topphoyde), med løpende maksimum.
  3. En observatør O ser P hvis vinkelen fra P til O er minst like stor
     som horisonten foran O på strålen.
  4. Siktlinjen O -> P fortsetter inn i innhegningen med samme fall.
     Dybden under veggtopp der linjen når motsatt side er
         dybde = L * fall,   L = indre lengde fra P langs linjen
     begrenset til veggens hoyde (gulv). Innsyn hvis dybde > valgt
     avstand under veggtopp.
"""

import math
import numpy as np

JORDRADIUS = 6371000.0
K_REFRAKSJON = 0.13


# ----------------------------------------------------------------------
#  Rutenett
# ----------------------------------------------------------------------

class Rutenett(object):
    """Regulaert rutenett. Node (i, j): x = x0 + j*res, y = y0 + i*res."""

    def __init__(self, x0, y0, res, nrad, nkol):
        self.x0 = float(x0)
        self.y0 = float(y0)
        self.res = float(res)
        self.nrad = int(nrad)
        self.nkol = int(nkol)

    @classmethod
    def rundt(cls, senter_x, senter_y, halvbredde, res):
        n = int(math.ceil(2.0 * halvbredde / res)) + 1
        x0 = math.floor((senter_x - halvbredde) / res) * res
        y0 = math.floor((senter_y - halvbredde) / res) * res
        return cls(x0, y0, res, n, n)

    @property
    def form(self):
        return (self.nrad, self.nkol)

    def kolonne_x(self):
        return self.x0 + np.arange(self.nkol) * self.res

    def rad_y(self):
        return self.y0 + np.arange(self.nrad) * self.res


def bilineaer(Z, rn, xs, ys):
    """Bilineaer sampling av Z (uten NaN). Utenfor rutenettet: -inf."""
    fx = (xs - rn.x0) / rn.res
    fy = (ys - rn.y0) / rn.res
    j0 = np.floor(fx).astype(np.int64)
    i0 = np.floor(fy).astype(np.int64)
    innenfor = (j0 >= 0) & (i0 >= 0) & (j0 < rn.nkol - 1) & (i0 < rn.nrad - 1)
    j0 = np.clip(j0, 0, rn.nkol - 2)
    i0 = np.clip(i0, 0, rn.nrad - 2)
    tx = fx - j0
    ty = fy - i0
    v = (Z[i0, j0] * (1 - tx) * (1 - ty) + Z[i0, j0 + 1] * tx * (1 - ty)
         + Z[i0 + 1, j0] * (1 - tx) * ty + Z[i0 + 1, j0 + 1] * tx * ty)
    v = np.where(innenfor, v, -np.inf)
    return v


def rasteriser_trekanter_max(rn, tri, budsjett=3000000):
    """Rasteriserer trekanter (T,3,3) til rutenettet. Hver node får
    høyeste Z blant trekantene den ligger i (= toppflaten). Noder uten
    trekant blir NaN. Vertikale/degenererte trekanter hoppes over."""
    Z = np.full(rn.form, -np.inf)
    tri = np.asarray(tri, dtype=float)
    if tri.size == 0:
        return np.full(rn.form, np.nan)
    x = tri[:, :, 0]
    y = tri[:, :, 1]
    z = tri[:, :, 2]
    d = (y[:, 1] - y[:, 2]) * (x[:, 0] - x[:, 2]) + (x[:, 2] - x[:, 1]) * (y[:, 0] - y[:, 2])
    jmin = np.ceil((x.min(1) - rn.x0) / rn.res - 1e-9).astype(np.int64)
    jmax = np.floor((x.max(1) - rn.x0) / rn.res + 1e-9).astype(np.int64)
    imin = np.ceil((y.min(1) - rn.y0) / rn.res - 1e-9).astype(np.int64)
    imax = np.floor((y.max(1) - rn.y0) / rn.res + 1e-9).astype(np.int64)
    jmin = np.maximum(jmin, 0)
    imin = np.maximum(imin, 0)
    jmax = np.minimum(jmax, rn.nkol - 1)
    imax = np.minimum(imax, rn.nrad - 1)
    nj = jmax - jmin + 1
    ni = imax - imin + 1
    behold = (np.abs(d) > 1e-12) & (nj > 0) & (ni > 0)
    idx = np.nonzero(behold)[0]
    if idx.size == 0:
        return np.full(rn.form, np.nan)
    storrelse = (ni * nj)[idx]
    idx = idx[np.argsort(storrelse, kind="stable")]

    start = 0
    while start < idx.size:
        # voks bunken så lenge antall * største_storrelse < budsjett
        slutt = start + 1
        while slutt < idx.size:
            neste = slutt + min(4096, idx.size - slutt)
            s_max = int((ni[idx[neste - 1]]) * (nj[idx[neste - 1]]))
            if (neste - start) * max(s_max, 1) > budsjett:
                break
            slutt = neste
        b = idx[start:slutt]
        start = slutt
        NI = int(ni[b].max())
        NJ = int(nj[b].max())
        di = np.arange(NI)[None, :, None]
        dj = np.arange(NJ)[None, None, :]
        I = imin[b][:, None, None] + di
        J = jmin[b][:, None, None] + dj
        gyldig = (di < ni[b][:, None, None]) & (dj < nj[b][:, None, None])
        px = rn.x0 + J * rn.res
        py = rn.y0 + I * rn.res
        x0_, x1_, x2_ = [x[b, k][:, None, None] for k in range(3)]
        y0_, y1_, y2_ = [y[b, k][:, None, None] for k in range(3)]
        z0_, z1_, z2_ = [z[b, k][:, None, None] for k in range(3)]
        db = d[b][:, None, None]
        l1 = ((y1_ - y2_) * (px - x2_) + (x2_ - x1_) * (py - y2_)) / db
        l2 = ((y2_ - y0_) * (px - x2_) + (x0_ - x2_) * (py - y2_)) / db
        l3 = 1.0 - l1 - l2
        inne = gyldig & (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        zz = l1 * z0_ + l2 * z1_ + l3 * z2_
        I = np.broadcast_to(I, inne.shape)[inne]
        J = np.broadcast_to(J, inne.shape)[inne]
        np.maximum.at(Z, (I, J), zz[inne])
    Z[~np.isfinite(Z)] = np.nan
    return Z


def rasteriser_i_utsnitt(rn, tri):
    """Som rasteriser_trekanter_max, men regner kun i trekantenes bbox
    (sparer minne når toposolidet er lite i forhold til analyseområdet)."""
    tri = np.asarray(tri, dtype=float)
    Z = np.full(rn.form, np.nan, dtype=np.float32)
    if tri.size == 0:
        return Z
    j0 = max(0, int(math.floor((tri[:, :, 0].min() - rn.x0) / rn.res)))
    j1 = min(rn.nkol - 1, int(math.ceil((tri[:, :, 0].max() - rn.x0) / rn.res)))
    i0 = max(0, int(math.floor((tri[:, :, 1].min() - rn.y0) / rn.res)))
    i1 = min(rn.nrad - 1, int(math.ceil((tri[:, :, 1].max() - rn.y0) / rn.res)))
    if j1 < j0 or i1 < i0:
        return Z
    sub = Rutenett(rn.x0 + j0 * rn.res, rn.y0 + i0 * rn.res, rn.res, i1 - i0 + 1, j1 - j0 + 1)
    Z[i0:i1 + 1, j0:j1 + 1] = rasteriser_trekanter_max(sub, tri)
    return Z


def bygg_terreng(Ztopo, Zdtm):
    """Slaar sammen toposolid og Kartverket-DTM.
    - DTM forskyves vertikalt med medianavviket mot toposolidet (dz), slik
      at høydedatum (NN2000/NN54/+95 m/relativ Z) alltid matcher modellen.
    - Innenfor toposolidet brukes toposolidet (inkl. modellerte voller o.l.).
    - Der DTM mangler (sjø) brukes kote 0 + dz til blokkering, men cellene
      får ingen observatør.
    Returnerer (H float32, gyldig bool, dz, mad, n_overlapp)."""
    har_topo = np.isfinite(Ztopo)
    har_dtm = np.isfinite(Zdtm)
    begge = har_topo & har_dtm
    n = int(begge.sum())
    if n == 0:
        raise ValueError("Toposolidet overlapper ikke Kartverket-terrenget.")
    diff = (Ztopo[begge] - Zdtm[begge]).astype(float)
    dz = float(np.median(diff))
    mad = float(np.median(np.abs(diff - dz)))
    H = np.where(har_topo, Ztopo, np.where(har_dtm, Zdtm, 0.0) + dz).astype(np.float32)
    gyldig = har_topo | har_dtm
    return H, gyldig, dz, mad, n


# ----------------------------------------------------------------------
#  Polygon-hjelpere
# ----------------------------------------------------------------------

def _kryss(ax, ay, bx, by):
    return ax * by - ay * bx


def konveks_hull(pts):
    """Monotone chain. Returnerer (M,2) mot klokka, uten gjentatt startpunkt."""
    p = np.unique(np.round(np.asarray(pts, dtype=float), 6), axis=0)
    if len(p) < 3:
        raise ValueError("For få punkter til å danne en innhegning.")
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def bygg(rekke):
        h = []
        for q in rekke:
            while len(h) >= 2 and _kryss(h[-1][0] - h[-2][0], h[-1][1] - h[-2][1],
                                         q[0] - h[-2][0], q[1] - h[-2][1]) <= 1e-9:
                h.pop()
            h.append(q)
        return h

    nedre = bygg(p)
    ovre = bygg(p[::-1])
    hull = np.array(nedre[:-1] + ovre[:-1])
    if len(hull) < 3:
        raise ValueError("Veggene ligger på en rett linje - ingen innhegning.")
    return hull


def avstand_utenfor_hull(hull, xs, ys):
    """Avstand fra punkt til hull for punkter utenfor; 0 for punkter inni."""
    A = hull
    B = np.roll(hull, -1, axis=0)
    inne = np.ones(xs.shape, dtype=bool)
    dmin = np.full(xs.shape, np.inf)
    for (ax, ay), (bx, by) in zip(A, B):
        ex, ey = bx - ax, by - ay
        # hull er mot klokka -> innsiden er til venstre for kanten
        inne &= _kryss(ex, ey, xs - ax, ys - ay) >= -1e-9
        L2 = ex * ex + ey * ey
        t = np.clip(((xs - ax) * ex + (ys - ay) * ey) / L2, 0.0, 1.0)
        dx = xs - (ax + t * ex)
        dy = ys - (ay + t * ey)
        dmin = np.minimum(dmin, np.hypot(dx, dy))
    return np.where(inne, 0.0, dmin)


def straale_segment_t(px, py, ux, uy, A, B, tmin=1e-6):
    """Avstand t langs strålene (px,py)+t*(ux,uy) til segmentene A->B.
    ux, uy: (n,) ; A, B: (m,2). Returnerer (n,m) med inf der ingen treff."""
    ex = (B[:, 0] - A[:, 0])[None, :]
    ey = (B[:, 1] - A[:, 1])[None, :]
    ux = np.asarray(ux)[:, None]
    uy = np.asarray(uy)[:, None]
    px = np.asarray(px)
    py = np.asarray(py)
    if px.ndim:
        px = px[:, None]
        py = py[:, None]
    apx = A[:, 0][None, :] - px
    apy = A[:, 1][None, :] - py
    nevner = _kryss(ux, uy, ex, ey)
    med = np.abs(nevner) > 1e-12
    trygg = np.where(med, nevner, 1.0)
    t = _kryss(apx, apy, ex, ey) / trygg
    s = _kryss(apx, apy, ux, uy) / trygg
    ok = med & (t > tmin) & (s >= -1e-9) & (s <= 1 + 1e-9)
    return np.where(ok, t, np.inf)


def indre_lengde(hull, px, py, wx, wy):
    """Lengde fra P langs retning w til der linjen forlater hullet."""
    A = hull
    B = np.roll(hull, -1, axis=0)
    t = straale_segment_t(px, py, wx, wy, A, B, tmin=1e-6)
    t = np.where(np.isfinite(t), t, -np.inf)
    L = t.max(axis=1)
    return np.where(np.isfinite(L), L, 0.0)


def fotavtrykk_segmenter(polyline, bredde, topp, eier):
    """Hindringssegmenter for en vegg/skjerm: omriss av et rektangel rundt
    hvert delsegment av senterlinjen, forlenget med halv bredde i hver
    ende (tilnærmer at vegger er skjøtt i hjørnene). Bredde 0 gir
    bare senterlinjen. Returnerer (A, B, topp, eier) som lister."""
    pl = np.asarray(polyline, dtype=float)[:, :2]
    A, B = [], []
    h = 0.5 * float(bredde)
    for a, b in zip(pl[:-1], pl[1:]):
        v = b - a
        L = float(np.hypot(v[0], v[1]))
        if L < 1e-6:
            continue
        t = v / L
        n = np.array([-t[1], t[0]])
        if h <= 1e-6:
            A.append(a)
            B.append(b)
            continue
        a2 = a - t * h
        b2 = b + t * h
        hj = [a2 + n * h, b2 + n * h, b2 - n * h, a2 - n * h]
        for k in range(4):
            A.append(hj[k])
            B.append(hj[(k + 1) % 4])
    m = len(A)
    return A, B, [float(topp)] * m, [eier] * m


def punkter_langs(polyline, avstand):
    """Punkter langs en polylinje med maks 'avstand' mellom, inkl. endepunkter.
    Returnerer (pkt (n,2), tangent (n,2))."""
    pl = np.asarray(polyline, dtype=float)[:, :2]
    pkt = []
    tan = []
    for a, b in zip(pl[:-1], pl[1:]):
        v = b - a
        L = float(np.hypot(v[0], v[1]))
        if L < 1e-6:
            continue
        n = max(1, int(math.ceil(L / avstand)))
        for k in range(n + 1):
            if pkt and k == 0:
                continue
            pkt.append(a + v * (k / float(n)))
            tan.append(v / L)
    return np.array(pkt), np.array(tan)


# ----------------------------------------------------------------------
#  Observatoerer
# ----------------------------------------------------------------------

def lag_observatorer(rn, H, gyldig, celle, senter, radius, hull, min_avstand, oyehoyde):
    """Ett observatørpunkt per celle (celle x celle m): høyeste
    terrengpunkt i cellen, i sin faktiske posisjon, + øyehøyde.
    Celler inne i innhegningen (eller nærmere enn min_avstand) fjernes."""
    k = max(1, int(round(celle / rn.res)))
    nbi = rn.nrad // k
    nbj = rn.nkol // k
    Hm = np.where(gyldig, H, -np.inf)[: nbi * k, : nbj * k]
    blokk = Hm.reshape(nbi, k, nbj, k).transpose(0, 2, 1, 3).reshape(nbi, nbj, k * k)
    arg = blokk.argmax(axis=2)
    zmax = np.take_along_axis(blokk, arg[:, :, None], axis=2)[:, :, 0]
    bi, bj = np.meshgrid(np.arange(nbi), np.arange(nbj), indexing="ij")
    ii = bi * k + arg // k
    jj = bj * k + arg % k
    x = rn.x0 + jj * rn.res
    y = rn.y0 + ii * rn.res
    cx = rn.x0 + (bj * k + (k - 1) / 2.0) * rn.res
    cy = rn.y0 + (bi * k + (k - 1) / 2.0) * rn.res
    ok = np.isfinite(zmax)
    ok &= np.hypot(x - senter[0], y - senter[1]) <= radius
    x, y, zb, cx, cy = x[ok], y[ok], zmax[ok], cx[ok], cy[ok]
    d = avstand_utenfor_hull(hull, x, y)
    ute = d > max(min_avstand, 1e-6)
    return {
        "x": x[ute].astype(float),
        "y": y[ute].astype(float),
        "zbakke": zb[ute].astype(float),
        "z": (zb[ute] + oyehoyde).astype(float),
        "cx": cx[ute].astype(float),
        "cy": cy[ute].astype(float),
        "celle": k * rn.res,
    }


# ----------------------------------------------------------------------
#  Hovedberegning per vegg
# ----------------------------------------------------------------------

def krumning(s, paa):
    if not paa:
        return np.zeros_like(s, dtype=float)
    return s * s * (1.0 - K_REFRAKSJON) / (2.0 * JORDRADIUS)


def _endepunkter(pl):
    pl = np.asarray(pl, dtype=float)[:, :2]
    return pl[[0, -1]]


def _segmenter(pl):
    pl = np.asarray(pl, dtype=float)[:, :2]
    return pl[:-1], pl[1:]


def _avstand_punkter_segmenter(P, A, B):
    """Minste avstand fra hvert punkt i P (n,2) til segmentene A->B (m,2)."""
    P = np.asarray(P, dtype=float)[:, None, :]
    A = np.asarray(A, dtype=float)[None, :, :]
    B = np.asarray(B, dtype=float)[None, :, :]
    e = B - A
    L2 = np.maximum((e * e).sum(-1), 1e-12)
    t = np.clip(((P - A) * e).sum(-1) / L2, 0.0, 1.0)
    d = P - (A + t[..., None] * e)
    return np.sqrt((d * d).sum(-1)).min(axis=1)


def finn_stasjonsnett(vegger, valgte_ids, tol=0.6, maks_utstrekning=300.0):
    """Finner alle vegger som henger sammen med de valgte: deler hjørne
    eller T-kobling (endepunkt innenfor tol fra en annen veggs
    senterlinje). Brukes til å avgjøre hva som er innsiden av stasjonen.
    vegger: liste med {"id", "polyline"}. Returnerer set med id-er."""
    etter_id = dict((v["id"], v) for v in vegger)
    nett = set(i for i in valgte_ids if i in etter_id)
    if not nett:
        return nett
    senter = np.vstack([_endepunkter(etter_id[i]["polyline"]) for i in nett]).mean(axis=0)
    kandidater = []
    for v in vegger:
        if v["id"] in nett:
            continue
        ep = _endepunkter(v["polyline"])
        if np.hypot(ep[:, 0] - senter[0], ep[:, 1] - senter[1]).min() <= maks_utstrekning:
            kandidater.append(v)
    endret = True
    while endret and kandidater:
        endret = False
        nA = np.vstack([_segmenter(etter_id[i]["polyline"])[0] for i in nett])
        nB = np.vstack([_segmenter(etter_id[i]["polyline"])[1] for i in nett])
        nE = np.vstack([_endepunkter(etter_id[i]["polyline"]) for i in nett])
        rest = []
        for v in kandidater:
            vA, vB = _segmenter(v["polyline"])
            kobla = (_avstand_punkter_segmenter(_endepunkter(v["polyline"]), nA, nB).min() <= tol
                     or _avstand_punkter_segmenter(nE, vA, vB).min() <= tol)
            if kobla:
                nett.add(v["id"])
                endret = True
            else:
                rest.append(v)
        kandidater = rest
    return nett


def _andel_innelukket(px, py, A, B, n=24, maks=1000.0):
    """Andel av n stråler fra (px,py) som treffer et av segmentene."""
    th = np.arange(n) * 2.0 * math.pi / n
    t = straale_segment_t(np.full(n, px), np.full(n, py), np.cos(th), np.sin(th), A, B, tmin=1e-3)
    return float((t.min(axis=1) <= maks).mean())


def utside_normal(vegg, nettvegger, terskel=0.75):
    """Finner hvilken side av veggen som er utsiden. Et punkt like ved
    veggen er 'innelukket' hvis minst 75 % av stråler i alle retninger
    treffer en vegg i stasjonen (inkludert veggen selv). Innsiden er
    innelukket, utsiden ikke.
    Returnerer ((nx, ny) eller None, status, (andel_side1, andel_side2))."""
    pl = np.asarray(vegg["polyline"], dtype=float)[:, :2]
    A, B = _segmenter(pl)
    lengder = np.hypot(*(B - A).T)
    k = int(np.argmax(lengder))
    if lengder[k] < 1e-6:
        return None, "for kort", (0.0, 0.0)
    t = (B[k] - A[k]) / lengder[k]
    n = np.array([t[1], -t[0]])
    midt = 0.5 * (A[k] + B[k])
    off = 0.5 * float(vegg.get("bredde", 0.0)) + 0.3
    alleA = np.vstack([_segmenter(v["polyline"])[0] for v in nettvegger])
    alleB = np.vstack([_segmenter(v["polyline"])[1] for v in nettvegger])
    a1 = _andel_innelukket(*(midt + n * off), alleA, alleB)
    a2 = _andel_innelukket(*(midt - n * off), alleA, alleB)
    if a1 >= terskel and a2 < terskel:
        return (-n[0], -n[1]), "ok", (a1, a2)
    if a2 >= terskel and a1 < terskel:
        return (n[0], n[1]), "ok", (a1, a2)
    if a1 >= terskel and a2 >= terskel:
        return None, "innervegg", (a1, a2)
    return None, "ikke innelukket", (a1, a2)


def punkter_langs_innfelt(polyline, avstand, innfelling):
    """Som punkter_langs, men starter/slutter 'innfelling' m fra endene,
    slik at punktene ligger på selve veggen og ikke i hjørnet der den
    møter naboveggen."""
    pl = np.asarray(polyline, dtype=float)[:, :2]
    seg = np.diff(pl, axis=0)
    L = np.hypot(seg[:, 0], seg[:, 1])
    tot = float(L.sum())
    if tot <= 2 * innfelling + 0.1:
        # kort vegg: bare midtpunktet
        s_liste = [tot / 2.0]
    else:
        lengde = tot - 2 * innfelling
        n = max(1, int(math.ceil(lengde / avstand)))
        s_liste = [innfelling + lengde * k / float(n) for k in range(n + 1)]
    kum = np.concatenate([[0.0], np.cumsum(L)])
    pkt, tan = [], []
    for sv in s_liste:
        i = int(np.clip(np.searchsorted(kum, sv, side="right") - 1, 0, len(L) - 1))
        if L[i] < 1e-9:
            continue
        u = seg[i] / L[i]
        pkt.append(pl[i] + u * (sv - kum[i]))
        tan.append(u)
    return np.array(pkt), np.array(tan)


def analyser_vegg(rn, H, vegg, hindringer, obs, steg, n_straaler, punktavstand,
                  nett_ids, utside, krumning_paa=True, innfelling=0.5,
                  straale_bunt=192, logg=None):
    """
    vegg: {"id", "polyline", "topp", "bunn"} - veggen som sjekkes
    hindringer: {"A", "B", "topp", "eier"} - fotavtrykk for ALLE vegger i
        området + skjerming. Veggens egne segmenter (eier == id) utelates.
    nett_ids: id-ene til veggene som utgjør stasjonen (finn_stasjonsnett)
    utside: (nx, ny) - normal som peker ut av stasjonen (utside_normal)

    En siktlinje O -> P regnes for denne veggen bare hvis den går inn over
    nettopp denne veggen: O ligger på utsiden, og linjen krysser ingen
    annen stasjonsvegg før P. Inne i stasjonen fortsetter linjen med samme
    fall til den treffer en stasjonsvegg som er høy nok til å stoppe den,
    eller forlater stasjonen over motsatt vegg. Dybden er hvor langt under
    veggtoppen linjen er der, begrenset til veggens høyde (gulvet).
    """
    ox, oy, oz = obs["x"], obs["y"], obs["z"]
    n_obs = ox.size
    beste = np.zeros(n_obs)
    beste_px = np.full(n_obs, np.nan)
    beste_py = np.full(n_obs, np.nan)
    beste_fall = np.zeros(n_obs)
    synlig_noen = np.zeros(n_obs, dtype=bool)

    topp = float(vegg["topp"])
    hoyde = max(0.0, topp - float(vegg["bunn"]))
    zP = topp + 0.01   # P løftes 1 cm for å ikke skjermes av egen vegg
    P, T = punkter_langs_innfelt(vegg["polyline"], punktavstand, innfelling)
    dtheta = 2.0 * math.pi / n_straaler

    eier = np.asarray(hindringer["eier"], dtype=object)
    HA_alle = np.asarray(hindringer["A"], dtype=float).reshape(-1, 2)
    HB_alle = np.asarray(hindringer["B"], dtype=float).reshape(-1, 2)
    Ht_alle = np.asarray(hindringer["topp"], dtype=float)
    egen = np.array([e == vegg["id"] for e in eier], dtype=bool)
    i_nett = np.array([e in nett_ids for e in eier], dtype=bool)
    HA, HB, Htopp = HA_alle[~egen], HB_alle[~egen], Ht_alle[~egen]
    NA, NB, Ntopp = HA_alle[i_nett & ~egen], HB_alle[i_nett & ~egen], Ht_alle[i_nett & ~egen]

    for ip in range(len(P)):
        px, py = float(P[ip, 0]), float(P[ip, 1])
        nx, ny = T[ip, 1], -T[ip, 0]
        if nx * utside[0] + ny * utside[1] < 0:
            nx, ny = -nx, -ny
        dx = ox - px
        dy = oy - py
        D = np.maximum(np.hypot(dx, dy), 1e-6)
        a_obs = (oz - krumning(D, krumning_paa) - zP) / D
        kand = np.nonzero(((dx * nx + dy * ny) > 0.02 * D) & (a_obs > 0))[0]
        if kand.size == 0:
            continue
        Dk = D[kand]
        theta = np.arctan2(dy[kand], dx[kand])
        k = np.mod(np.round(theta / dtheta).astype(np.int64), n_straaler)
        straaler, inv = np.unique(k, return_inverse=True)
        n_s = int(math.ceil(Dk.max() / steg)) + 1
        s = steg * np.arange(1, n_s + 1)
        c_s = krumning(s, krumning_paa)
        M = np.empty((straaler.size, n_s), dtype=np.float32)
        for b0 in range(0, straaler.size, straale_bunt):
            kk = straaler[b0:b0 + straale_bunt]
            ux = np.cos(kk * dtheta)
            uy = np.sin(kk * dtheta)
            xs = px + ux[:, None] * s[None, :]
            ys = py + uy[:, None] * s[None, :]
            h = bilineaer(H, rn, xs, ys)
            A = (h - c_s[None, :] - zP) / s[None, :]
            if HA.size:
                t = straale_segment_t(np.full(kk.size, px), np.full(kk.size, py),
                                      ux, uy, HA, HB, tmin=0.01)
                treff = np.isfinite(t)
                if treff.any():
                    ri, si = np.nonzero(treff)
                    tt = t[ri, si]
                    ang = (Htopp[si] - krumning(tt, krumning_paa) - zP) / tt
                    jt = np.clip(np.ceil(tt / steg).astype(np.int64) - 1, 0, n_s - 1)
                    np.maximum.at(A, (ri, jt), ang)
            M[b0:b0 + straale_bunt] = np.maximum.accumulate(A, axis=1)
        utelat = Dk * dtheta / 2.0 + steg
        jO = np.floor((Dk - utelat) / steg).astype(np.int64) - 1
        hor = np.where(jO >= 0, M[inv, np.clip(jO, 0, n_s - 1)], -np.inf)
        synlig = a_obs[kand] >= hor - 1e-9
        if not synlig.any():
            continue
        vi = kand[synlig]
        Dv = D[vi]
        ux = dx[vi] / Dv
        uy = dy[vi] / Dv

        # Må gå inn over DENNE veggen: ingen annen stasjonsvegg mellom O og P
        if NA.size:
            t_ut = straale_segment_t(np.full(vi.size, px), np.full(vi.size, py), ux, uy, NA, NB, tmin=1e-3)
            inn_her = ~(t_ut < Dv[:, None]).any(axis=1)
            vi, Dv, ux, uy = vi[inn_her], Dv[inn_her], ux[inn_her], uy[inn_her]
            if vi.size == 0:
                continue
        synlig_noen[vi] = True

        fall = (oz[vi] - krumning(Dv, krumning_paa) - topp) / Dv
        # Videre inn i stasjonen (retning -u), synkende med 'fall'
        t_slutt = np.full(vi.size, np.inf)
        if NA.size:
            t_inn = straale_segment_t(np.full(vi.size, px), np.full(vi.size, py), -ux, -uy, NA, NB, tmin=1e-3)
            kryss = np.isfinite(t_inn)
            z_linje = topp - fall[:, None] * np.where(kryss, t_inn, 0.0)
            stopper = kryss & (Ntopp[None, :] >= z_linje - 1e-6)
            t_stopp = np.where(stopper, t_inn, np.inf).min(axis=1)
            t_ut_av = np.where(kryss, t_inn, -np.inf).max(axis=1)   # forlater stasjonen
            t_ut_av = np.where(np.isfinite(t_ut_av), t_ut_av, np.inf)
            t_slutt = np.minimum(t_stopp, t_ut_av)
        dyb = np.minimum(t_slutt * fall, hoyde)
        dyb = np.where(np.isfinite(dyb), dyb, hoyde)
        bedre = dyb > beste[vi]
        if bedre.any():
            vb = vi[bedre]
            beste[vb] = dyb[bedre]
            beste_px[vb] = px
            beste_py[vb] = py
            beste_fall[vb] = fall[bedre]
        if logg and (ip % 20 == 0 or ip == len(P) - 1):
            logg("    punkt {}/{} langs veggen".format(ip + 1, len(P)))

    return {
        "dybde": beste,
        "px": beste_px,
        "py": beste_py,
        "fall": beste_fall,
        "ser_toppen": synlig_noen,
        "n_punkter": len(P),
        "topp": topp,
        "hoyde": hoyde,
    }


def siktlinje(obs, res_vegg, i):
    """Endepunkter for siktlinjen til observatør i:
    O (øyepunkt) -> P (på veggtopp) -> T (dypeste punkt inne)."""
    O = (obs["x"][i], obs["y"][i], obs["z"][i])
    px, py = res_vegg["px"][i], res_vegg["py"][i]
    topp = res_vegg["topp"]
    dyb = res_vegg["dybde"][i]
    fall = res_vegg["fall"][i]
    wx, wy = px - O[0], py - O[1]
    n = math.hypot(wx, wy)
    wx, wy = wx / n, wy / n
    lengde = dyb / fall if fall > 0 else 0.0
    T = (px + wx * lengde, py + wy * lengde, topp - dyb)
    return O, (px, py, topp), T


def antall_straaler(radius, celle):
    """Så mange straaler at sideavviket ved ytterkanten er <= celle/4."""
    return int(max(720, math.ceil(2.0 * math.pi * radius / (celle / 2.0))))
