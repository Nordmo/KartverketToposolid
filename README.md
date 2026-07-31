# Kartverket → Revit Toposolid (PyRevit-knapp)

Henter høydedata fra Kartverket og oppretter Toposolid direkte i den åpne
Revit-modellen. Project Base Point leses automatisk inn som nullpunkt —
du trenger kun å sette midtpunkt, radius og punkttetthet, og trykke
**"Lag Toposolid"**.

Ingen nedlasting av filer, ingen manuell import, ingen kjørende
Flask-server. Alt skjer inne i Revit.

---

## Engangsoppsett

Dette gjøres én gang per PC/installasjon, ikke hver gang du bruker knappen.

### 1. Installer PyRevit (hvis ikke allerede gjort)

Last ned og installer fra [pyrevitlabs.io](https://pyrevitlabs.io) hvis du
ikke allerede har det.

### 2. Kopier utvidelsen inn i PyRevit

Kopier hele mappen `KartverketToposolid.extension` inn i PyRevit sin
extensions-mappe. Standard plassering er:

```
%APPDATA%\pyRevit\Extensions\
```

(Du kan også finne riktig mappe via pyRevit-fanen → **Settings** →
**Custom Extension Directories**, eller legge til denne mappen som en
egen extension-katalog derfra i stedet for å kopiere.)

### 3. Installer Python-pakker i PyRevit sin CPython-motor

Scriptet bruker `#! python3`-direktivet øverst, som forteller PyRevit å
kjøre det med CPython i stedet for IronPython. Dette gir tilgang til
pip-installerte pakker.

Åpne en terminal og kjør (bytt ut stien med din faktiske CPython-motor —
finnes normalt under `%APPDATA%\pyRevit-Master\bin\` eller tilsvarende;
se pyRevit sin dokumentasjon for **CPython engine** for eksakt sti på
din installasjon):

```
"<sti-til-pyrevit-cpython>\python.exe" -m pip install rasterio numpy pyproj requests
```

### 4. Hent WebView2-komponentene

Disse er .NET-sammenstillinger (ikke pip-pakker) og må hentes separat via
NuGet:

1. Gå til [nuget.org/packages/Microsoft.Web.WebView2](https://www.nuget.org/packages/Microsoft.Web.WebView2)
2. Last ned `.nupkg`-filen (den er egentlig en zip-fil — endre
   filendelsen til `.zip` og pakk ut, eller bruk 7-Zip direkte)
3. Finn disse tre filene inne i den utpakkede pakken (under en mappe som
   `runtimes\win-x64\native\` og `lib\net462\` eller `lib\netcoreapp3.0\`):
   - `Microsoft.Web.WebView2.Core.dll`
   - `Microsoft.Web.WebView2.Wpf.dll`
   - `WebView2Loader.dll` (x64-versjonen)
4. Kopier alle tre inn i:
   ```
   KartverketToposolid.extension\KartverketToposolid.tab\DTM.panel\LagToposolid.pushbutton\
   ```
   (samme mappe som `script.py` og `ui.html`)

### 5. Sjekk at WebView2 Runtime er installert

De aller fleste Windows 10/11-maskiner har dette allerede (følger med
Edge). Test ved å åpne:
```
https://go.microsoft.com/fwlink/p/?LinkId=2124703
```
Hvis maskinen mangler runtime, laster denne siden ned installasjonsfilen
("Evergreen Bootstrapper") — kjør den, krever normalt ikke
administrator-rettigheter.

### 6. Last inn PyRevit på nytt

I Revit: pyRevit-fanen → **Reload**. Knappen **"Lag Toposolid"** skal nå
dukke opp under fanen **KartverketToposolid → DTM**.

---

## Kjent usikkerhet — les dette før du tester

`script.py` er skrevet etter beste kunnskap om Revit API, men er **ikke
testet mot en ekte Revit-installasjon**. Den mest usikre delen er
funksjonen `opprett_toposolid()`, som kaller `Toposolid.Create(...)`.
Toposolid ble introdusert i Revit 2024, og den eksakte signaturen til
denne metoden bør du dobbeltsjekke — enklest med
[RevitLookup](https://github.com/jeremytammik/RevitLookup) eller Revit
2026 sin API-dokumentasjon, hvis du får en feilmelding her.

Andre ting som er verdt å sjekke om noe oppfører seg uventet:
- At `OST_ProjectBasePoint`-kategorien faktisk gir deg Project Base
  Point (ikke Survey Point) i din Revit-versjon.
- At `Position`-egenskapen på Base Point-elementet gir koordinatene du
  forventer (sammenlign med tallene i **Manage → Coordinates**).

Alt annet i scriptet (Kartverket-integrasjon, HPCS/NN54-korreksjon,
kart-UI) er direkte portert fra en fullt fungerende og testet
frittstående nettapp-versjon, og skal fungere identisk.

---

## Mappestruktur

```
KartverketToposolid.extension/
└── KartverketToposolid.tab/
    └── DTM.panel/
        └── LagToposolid.pushbutton/
            ├── bundle.yaml
            ├── script.py
            ├── ui.html
            ├── Microsoft.Web.WebView2.Core.dll   ← du legger til denne
            ├── Microsoft.Web.WebView2.Wpf.dll    ← du legger til denne
            └── WebView2Loader.dll                ← du legger til denne
```
