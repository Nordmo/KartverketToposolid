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

### 4. Kjør det automatiske oppsett-scriptet

`setup.ps1` (ligger i repo-roten) automatiserer det som ellers er mest
tidkrevende: henter WebView2-komponentene fra NuGet automatisk, finner
riktig Python-versjon på maskinen din, og installerer `numpy`,
`rasterio` og `pyproj` rett inn i PyRevit sin `site-packages`-mappe.
Krever ingen administrator-rettigheter.

Åpne PowerShell i repo-mappen og kjør:
```powershell
.\setup.ps1
```

**Får du feilmeldingen "running scripts is disabled on this system"** —
Windows blokkerer som standard kjøring av `.ps1`-filer. Kjør i stedet:
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```
(dette endrer ingen permanente innstillinger — kun for denne ene
kjøringen)

Har du **ikke** en Python-installasjon som matcher versjonen PyRevit
bruker (scriptet forteller deg nøyaktig hvilken), stopper scriptet opp
og ber deg installere den ene manglende tingen — resten kjører
automatisk når du limer inn stien.

**Sjekk i tillegg at WebView2 Runtime er installert** (de fleste
Windows 10/11-maskiner har den fra før via Edge — scriptet sjekker
dette for deg og varsler hvis den mangler):
`https://go.microsoft.com/fwlink/p/?LinkId=2124703`

### 5. Test

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

Skulle noe likevel feile på selve `Toposolid.Create(...)`-linjen i
`opprett_toposolid()` i `script.py` — dette er den ene delen av koden
som ikke er 100 % fremtidssikker mot fremtidige Revit API-endringer.
Sjekk signaturen med [RevitLookup](https://github.com/jeremytammik/RevitLookup)
eller Revit sin API-dokumentasjon hvis den slutter å virke etter en
Revit-oppdatering.

---

## Mappestruktur

```
setup.ps1                              ← kjør dette først (steg 4)
KartverketToposolid.extension/
└── KartverketToposolid.tab/
    └── DTM.panel/
        └── LagToposolid.pushbutton/
            ├── bundle.yaml
            ├── script.py
            ├── ui.html
            ├── icon.png                          ← egen logo
            ├── Microsoft.Web.WebView2.Core.dll   ← hentes i steg 4
            ├── Microsoft.Web.WebView2.Wpf.dll    ← hentes i steg 4
            └── WebView2Loader.dll                ← hentes i steg 4
```
