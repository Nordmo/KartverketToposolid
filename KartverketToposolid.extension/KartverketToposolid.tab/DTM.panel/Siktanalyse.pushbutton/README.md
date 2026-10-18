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
   - **Velg stasjonsvegger**: veggene som omslutter stasjonen
   - **Velg ekstra skjerming** (valgfritt): gjerder, skjermvegger o.l.
3. Sett koordinatsystem og nullpunkt **likt som da toposolidet ble laget**.
   Nullpunkt fylles inn fra Project Base Point.
4. Sett øyehøyde, tillatt innsyn under veggtopp, radius osv. og trykk
   **Kjør analyse**.

Innstillingene huskes til neste gang (`%APPDATA%\KartverketToposolid\innsyn.json`).

## Hva den regner

- **Observatører:** rutenett (standard 10 x 10 m) innenfor radius fra
  stasjonen. I hver celle brukes det høyeste terrengpunktet, i sin faktiske
  posisjon, pluss øyehøyde. Celler inne i stasjonen fjernes.
- **Terreng:** Kartverket DTM1 (bart terreng) hentes flislagt for hele
  radiusen. Toposolidet legges oppå der det finnes, slik at voller og
  terrengendringer i modellen er med. DTM-høyden justeres automatisk mot
  toposolidet (medianavvik), så høydedatum (NN2000, NN54, +95 m, relativ Z)
  trenger ikke oppgis.
- **Hver vegg for seg:** punkter langs veggtoppen (standard hver 1 m). Fra
  hvert punkt regnes en horisont utover i terrenget, inkludert de andre
  veggene og valgt skjerming. En observatør som ser veggtoppen og ligger
  høyere enn den, ser inn. Siktlinjen fortsetter inn i stasjonen med samme
  fall, og **dybden under veggtopp** der den når motsatt side er resultatet.
  Dybden begrenses til veggens høyde.
- **Innsyn** = dybde større enn «Tillatt innsyn under veggtopp».
- **Jordkrumning og refraksjon** (k = 0,13) er med som standard (ca. 0,3 m
  ved 2 km).

## Resultat

- **Siktlinjer** for de verste observatørene per vegg: rød linje fra
  øyepunkt til veggtopp (linjestil «Innsyn - siktlinje») og lilla linje
  videre inn til dypeste synlige punkt («Innsyn - inn i stasjon»).
  Kommentarfeltet på linjene har vegg, dybde, avstand og koordinater.
- **Innsynskart:** fargede ruter på terrenget (DirectShape, Generic Models)
  der det er innsyn, gradert etter dybde: 0-0,5 / 0,5-1 / 1-2 / over 2 m.
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
- **Innhegningen** er det konvekse omrisset av veggene. For L-formede
  stasjoner blir den indre lengden litt overvurdert (gir mer innsyn, altså
  på den sikre siden).
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
