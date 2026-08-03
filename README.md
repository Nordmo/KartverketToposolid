# Kartverket → Revit Toposolid (PyRevit-knapp)

Henter høydedata fra Kartverket og oppretter Toposolid direkte i den åpne
Revit-modellen. Project Base Point leses automatisk inn som nullpunkt —
du setter kun midtpunkt, radius og punkttetthet, og trykker
**"Lag Toposolid"**.

Ingen nedlasting av filer, ingen manuell import, ingen kjørende
Flask-server. Alt skjer inne i Revit.

Krever **Revit 2024 eller nyere** (Toposolid finnes ikke i eldre versjoner).

---

## Engangsoppsett

Dette gjøres én gang per PC, ikke hver gang du bruker knappen. Regn med
15–20 minutter første gang.

### 1. Installer PyRevit

Last ned fra [pyrevitlabs.io](https://pyrevitlabs.io) hvis du ikke
allerede har det.

### 2. Hent ned dette repoet

```powershell
cd Dokumenter
mkdir GitRepos
cd GitRepos
git clone https://github.com/Nordmo/KartverketToposolid.git
```

### 3. Koble mappen til PyRevit

I Revit: **pyRevit**-fanen → **Settings** → **Custom Extension
Directories** → legg til stien til mappen du klonet
(`...\GitRepos\KartverketToposolid`, altså mappen som *inneholder*
`.extension`-mappen).

Lukk innstillingene, trykk **Reload** på pyRevit-fanen. Knappen **"Lag
Toposolid"** skal nå dukke opp under fanen **KartverketToposolid** →
panelet **DTM**.

Trykker du på den nå, feiler den — det er forventet. To ting gjenstår.

### 4. Hent WebView2-komponentene

Disse er .NET-filer (ikke pip-pakker) og må hentes separat via NuGet:

1. Gå til [nuget.org/packages/Microsoft.Web.WebView2](https://www.nuget.org/packages/Microsoft.Web.WebView2)
2. Trykk **Download package** — du får en `.nupkg`-fil
3. Endre filendelsen fra `.nupkg` til `.zip`, pakk ut
4. Finn disse tre filene (typisk under `lib\net462\` og
   `runtimes\win-x64\native\` — bruk **net462**, ikke `netcoreapp`/`net6.0`,
   siden Revit er en .NET Framework-vert):
   - `Microsoft.Web.WebView2.Core.dll`
   - `Microsoft.Web.WebView2.Wpf.dll`
   - `WebView2Loader.dll`
5. Kopier alle tre inn i:
   ```
   KartverketToposolid.extension\KartverketToposolid.tab\DTM.panel\LagToposolid.pushbutton\
   ```

Sjekk også at **WebView2 Runtime** er installert (de fleste Windows
10/11-maskiner har den fra før via Edge) — test ved å åpne
`https://go.microsoft.com/fwlink/p/?LinkId=2124703` i nettleseren.

### 5. Installer Python-pakker i RIKTIG Python-miljø

Dette er det steget som lettest går galt, så følg det nøye.

**Finn ut hvilken Python-versjon PyRevit sin CPython-motor bruker.**
Åpne
```
%APPDATA%\pyRevit-Master\bin\cengines\
```
og se hvilken mappe som ligger der — navnet forteller versjonen, f.eks.
`CPY3123` betyr Python **3.12.3**. Skriv ned hovedversjonen (3.12, 3.11,
osv.) — dette er avgjørende, siden `numpy` og `rasterio` inneholder
kompilert kode som er versjonsspesifikk.

**Sjekk om du allerede har en Python-installasjon med samme
hovedversjon:**
```powershell
python --version
```

- **Stemmer hovedversjonen** (f.eks. begge er 3.12.x) → bruk den direkte
  i kommandoen under.
- **Stemmer ikke** (eller ingen Python installert) → last ned riktig
  versjon fra
  [python.org/downloads/release](https://www.python.org/downloads/release/)
  (søk opp riktig hovedversjon, f.eks. "Python 3.12"). **NB:** eldre
  3.12.x-delversjoner (nyere enn 3.12.10) har ofte kun kildekode uten
  Windows-installer — sjekk at det faktisk finnes en
  "Windows installer (64-bit)" på nedlastingssiden, ellers gå én
  delversjon ned. Under installasjon: **ikke** huk av "Add to PATH".

**Installer pakkene rett inn i PyRevit sin `site-packages`-mappe** (ikke
i din vanlige Python sin egen):
```powershell
python -m pip install --target "%APPDATA%\pyRevit-Master\site-packages" numpy rasterio pyproj
```
(bytt ut `python` med full sti til riktig `python.exe` hvis du måtte
installere en egen versjon ved siden av, f.eks.
`"C:\Users\<bruker>\AppData\Local\Programs\Python\Python312\python.exe"`)

### 6. Test

1. **Restart Revit helt** (ikke bare Reload — luk hele programmet,
   sjekk i Oppgavebehandling at `Revit.exe` er borte)
2. Åpne et prosjekt med **Project Base Point** satt (tallene under
   Manage → Coordinates skal vise ekte E/N-verdier, ikke 0)
3. Trykk **Lag Toposolid**
4. Vinduet åpnes med nullpunktet forhåndsutfylt — velg koordinatsystem,
   sett midtpunkt (klikk i kartet eller skriv inn), radius og
   punkttetthet, trykk **"Lag Toposolid"**

---

## Feilsøking

Scriptet er bygget med tydelig, presis feilrapportering — feiler noe,
forteller dialogboksen nøyaktig hvilket steg som feilet, og pyRevit sin
**Output-konsoll** (synlig i samme vindu) viser full detalj under.

De vanligste feilene og løsningene er allerede håndtert i koden basert
på reell feilsøking:
- **WebView2-relaterte feil ved andre forsøk i samme økt** → restart
  Revit helt, ikke bare Reload
- **"No module named X"** → feil Python-miljø i steg 5, dobbeltsjekk at
  hovedversjonen faktisk stemmer med PyRevit sin CPython-motor
- **"Name must be unique"** ved gjentatt bruk → skal ikke lenger skje
  (fikset ved å navngi opprettede Level ut fra kote)

Skulle noe likevel feile på selve `Toposolid.Create(...)`-linjen i
`opprett_toposolid()` i `script.py` — dette er den ene delen av koden
som ikke er 100 % fremtidssikker mot fremtidige Revit API-endringer.
Sjekk signaturen med [RevitLookup](https://github.com/jeremytammik/RevitLookup)
eller Revit sin API-dokumentasjon hvis den slutter å virke etter en
Revit-oppdatering.

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
            ├── icon.png                          ← egen logo
            ├── icon.dark.png                      ← mørk temavariant
            ├── Microsoft.Web.WebView2.Core.dll   ← hentes i steg 4
            ├── Microsoft.Web.WebView2.Wpf.dll    ← hentes i steg 4
            └── WebView2Loader.dll                ← hentes i steg 4
```
