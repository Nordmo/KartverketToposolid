# Innsyn (siktanalyse)

Knapp i DTM-panelet, ved siden av **Lag Toposolid**. Sjekker om man kan se
inn i en stasjon over dens egne vegger fra terrenget rundt.

Krever samme engangsoppsett som Lag Toposolid (numpy, rasterio, pyproj i
pyRevit sin CPython-motor). Bruker ikke WebView2. Revit 2024 eller nyere.

## Bruk

1. Lag toposolid med **Lag Toposolid** (eller bruk et eksisterende).
2. Trykk **Innsyn**. Har du merket toposolidet og veggene på forhånd, er de
   allerede valgt. Ellers bruker du knappene i dialogen:
   - **Velg toposolid** (velges automatisk hvis det bare finnes ett)
   - **Velg vegger å sjekke**: veggene du vil vite om man kan se inn på.
     Resten av stasjonen finnes automatisk via hjørner og T-koblinger
   - **Velg ekstra skjerming** (valgfritt): gjerder, skjermvegger o.l.
3. Sett koordinatsystem og nullpunkt **likt som da toposolidet ble laget**.
   Nullpunkt fylles inn fra Project Base Point.
4. Sett øyehøyde, tillatt innsyn under veggtopp, radius osv. og trykk
   **Kjør analyse**.

Innstillingene huskes til neste gang (`%APPDATA%\KartverketToposolid\innsyn.json`).

## Hva den regner

**Spørsmålet:** kan man utenfra se **innerflaten** på de valgte veggene
lavere enn «Tillatt innsyn under veggtopp»? Siktlinjen går typisk inn
over en av de *andre* veggene i stasjonen og treffer den valgte veggen på
innsiden.

- **Stasjonen:** de valgte veggene pluss alle vegger som henger sammen med
  dem (felles hjørne eller T-kobling). Innsiden av en valgt vegg er den
  siden som er omsluttet av stasjonen. Fundament- og vangvegger i samme
  linje som veggen regnes som del av den.
- **Observatører:** rutenett (standard 10 x 10 m) innenfor radius. I hver
  celle brukes det høyeste terrengpunktet pluss øyehøyde. Celler inne i
  stasjonen fjernes.
- **Terreng:** Kartverket DTM1 for hele radiusen, med toposolidet lagt
  oppå. DTM-høyden justeres automatisk mot toposolidet.
- **Hindringer:** terreng, alle vegger i modellen innenfor radius (også de
  andre stasjonsveggene, som er det som normalt stopper innsynet) og
  valgt ekstra skjerming.
- **Målpunkter** langs innerflaten av hver valgt vegg (standard hver 1 m),
  litt inn fra hjørnene. For hvert målpunkt sjekkes hvilke observatører
  som ser det i høyden *topp − tillatt innsyn*. For dem regnes det
  **laveste synlige punktet** på innerflaten eksakt, begrenset av gulvet.
- **Innsyn** = man ser innerflaten lavere enn tillatt. Rapporten viser
  hvor langt ned under toppen man ser.
- **Jordkrumning og refraksjon** (k = 0,13) er med som standard.

## Resultat

- **Siktlinjer** for de verste observatørene per valgt vegg: rød linje fra
  øyepunktet til der linjen går inn over stasjonsveggen (linjestil
  «Innsyn - siktlinje»), og lilla linje videre til det laveste synlige
  punktet **på innerflaten av den valgte veggen** («Innsyn - inn i stasjon»).
  Den som ser lengst ned velges først, deretter den neste verste som ligger
  minst «Min. vinkel mellom siktlinjer» (standard 30°) fra de allerede
  valgte, sett fra veggen. Slik spres linjene på ulike retninger.
  Kommentarfeltet på linjene har vegg, dybde, avstand og koordinater.
- **Innsynskart:** fargede ruter på terrenget (DirectShape, Generic Models)
  i hver observatørcelle som ser lenger ned enn tillatt på minst én valgt
  vegg. Fargen viser hvor langt under toppen cellen ser (verste vegg):
  gul 0-0,5 m, oransje 0,5-1 m, rød 1-2 m, mørkerød over 2 m.
  Fargene vises i skyggelagt visning.
- **Rapport** i pyRevit-konsollen og **CSV** (semikolon, desimalkomma) ved
  siden av modellfilen.
- Ny kjøring sletter linjer og innsynskart fra forrige kjøring.

## Begrensninger

- **Vegetasjon og bygg er ikke med** (DTM er bart terreng). Det gir
  konservative svar, som om det alltid var vinter uten løv.
- **Åpninger og porter i veggene vurderes ikke.** En vegg regnes som tett
  opp til toppen. Gap *mellom* vegger blokkerer ikke siktlinjer.
- **Veggtopp** hentes fra veggens bounding box (høyeste punkt). Vegger med
  skrå eller varierende topp regnes med høyeste punkt.
- **Stasjonen finnes via geometri:** vegger regnes som tilkoblet hvis et
  endepunkt ligger innenfor 0,6 m fra en annen veggs senterlinje. Vegger
  med større gap mellom seg blir ikke med, og da kan innsiden bli feil
  (rapporten varsler om vegger som ikke omslutter noe).
- **Vegger i lenkede modeller** er ikke med, verken som stasjon eller
  hindring.
- **Koordinater:** samme oppsett som Lag Toposolid, dvs. ren forskyvning via
  Project Base Point og ingen rotasjon (angle to true north brukes ikke).
- **HPCS:** transformasjonen er kopiert uendret fra Lag Toposolid, slik at
  terrenget treffer toposolider laget med den knappen.
- **Tid:** 2 km radius med 1 m terreng tar typisk 1-3 minutter, mest
  nedlasting (ca. 25 fliser fra Kartverket).

## Filer

| Fil | Innhold |
|---|---|
| `script.py` | Revit-delen: dialog, valg, geometri, linjer, innsynskart, rapport |
| `innsyn_kjerne.py` | Beregningen (ren numpy, kan testes uten Revit) |
| `innsyn_dtm.py` | Henting av DTM fra Kartverket og resampling |
