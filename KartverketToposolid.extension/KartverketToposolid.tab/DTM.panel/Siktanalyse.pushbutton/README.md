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
   - **Velg stasjonsvegger**: veggene du vil sjekke. Du trenger ikke velge
     alle: resten av stasjonen finnes automatisk via hjørner og
     T-koblinger, og avgjør hva som er inne og ute
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
- **Stasjonen:** de valgte veggene pluss alle vegger som henger sammen med
  dem (felles hjørne eller T-kobling). Innsiden av hver valgt vegg er den
  siden som er omsluttet av stasjonen. Innervegger (omsluttet på begge
  sider) sjekkes ikke.
- **Hindringer:** terreng, alle vegger i modellen innenfor radius, og valgt
  ekstra skjerming.
- **Hver vegg for seg:** punkter langs veggtoppen (standard hver 1 m), med
  start et lite stykke inn fra endene slik at linjene treffer selve veggen
  og ikke hjørnet. En observatør teller for en vegg bare hvis siktlinjen
  går inn over **akkurat den veggen** (ingen annen stasjonsvegg mellom
  observatøren og veggtoppen), og observatøren ligger høyere enn toppen.
- **Dybde:** siktlinjen fortsetter inn i stasjonen med samme fall til den
  treffer en vegg som er høy nok til å stoppe den (også skillevegger),
  eller forlater stasjonen over motsatt vegg. **Dybden** er hvor langt
  under veggtoppen linjen er der, begrenset til veggens høyde (gulvet).
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
