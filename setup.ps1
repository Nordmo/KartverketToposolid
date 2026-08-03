<#
.SYNOPSIS
  Automatisk engangsoppsett for KartverketToposolid PyRevit-utvidelsen.

.DESCRIPTION
  Kjores EN gang per PC, etter at repoet er klonet og koblet til PyRevit
  (se README.md steg 1-3). Automatiserer:
    - Henter WebView2-komponentene fra NuGet (i stedet for manuell
      nedlasting + endre filendelse + pakke ut + finne riktige filer)
    - Finner en lokal Python med riktig hovedversjon - eller tilbyr aa
      laste ned og installere den stille (per bruker, ingen admin) hvis
      versjonen er kjent (se $kjenteVersjoner lenger ned)
    - Installerer numpy/rasterio/pyproj rett inn i pyRevit sin
      site-packages

  Hopper automatisk over installasjon av det som allerede finnes -
  trygt aa kjore paa nytt om noe feilet underveis forrige gang.

  Krever INGEN administrator-rettigheter.

.USAGE
  Kjor fra samme mappe som denne filen ligger i (repo-roten):
    .\setup.ps1
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PushbuttonDir = Join-Path $ScriptDir "KartverketToposolid.extension\KartverketToposolid.tab\DTM.panel\LagToposolid.pushbutton"

function Skriv-Steg($tekst) {
    Write-Host ""
    Write-Host "=== $tekst ===" -ForegroundColor Cyan
}

if (-not (Test-Path $PushbuttonDir)) {
    Write-Error "Fant ikke pushbutton-mappen. Kjor dette scriptet fra repo-roten (samme sted som README.md ligger)."
    exit 1
}

# ============================================================
#  1. Finn pyRevit sin CPython-motor og hvilken Python-versjon
# ============================================================
Skriv-Steg "Sjekker pyRevit sin CPython-motor"

# PyRevit-installasjonen kan hete hva som helst (f.eks. "pyRevit-Master",
# "pyRevit", eller et selvvalgt navn), OG kan ligge to ulike steder
# avhengig av installasjonstype:
#   - Brukerinstallasjon: %APPDATA%  (vanligst ved egen installasjon)
#   - Admin-installasjon: Program Files  (vanlig ved sentral IT-utrulling)
# Vi soeker gjennom begge i stedet for aa anta noen av delene.
$soekeStier = @($env:APPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }
$cloneRoot = $null
$cengineDir = $null

foreach ($rot in $soekeStier) {
    if ($cloneRoot -or -not (Test-Path $rot)) { continue }
    Get-ChildItem $rot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        if (-not $cloneRoot) {
            $kandidat = Join-Path $_.FullName "bin\cengines"
            if (Test-Path $kandidat) {
                $funnetMotor = Get-ChildItem $kandidat -Directory -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -like "CPY*" } | Select-Object -First 1
                if ($funnetMotor) {
                    $cloneRoot = $_.FullName
                    $cengineDir = $funnetMotor
                }
            }
        }
    }
}

if (-not $cloneRoot) {
    Write-Error "Fant ingen pyRevit-installasjon med en CPython-motor under $($soekeStier -join ' eller '). Sjekk at pyRevit er installert, og at 'Active CPython Engine' viser et valg i pyRevit-fanen -> Settings (se README)."
    exit 1
}

$verDigits = $cengineDir.Name -replace "CPY", ""      # f.eks "3123"
$major = $verDigits.Substring(0, 1)
$minor = $verDigits.Substring(1, 2)
$maalVersjon = "$major.$minor"
Write-Host "Fant pyRevit-installasjon: $cloneRoot"
Write-Host "PyRevit bruker Python $maalVersjon (motor: $($cengineDir.Name))"

$sitePackages = Join-Path $cloneRoot "site-packages"

try {
    New-Item -ItemType Directory -Force -Path $sitePackages -ErrorAction Stop | Out-Null
    $testFil = Join-Path $sitePackages ".skrivetest-$(Get-Random)"
    New-Item -ItemType File -Path $testFil -ErrorAction Stop | Out-Null
    Remove-Item $testFil -Force -ErrorAction SilentlyContinue
} catch {
    Write-Error (
        "Har ikke skrive-tilgang til $sitePackages`n" +
        "Dette skjer ofte naar pyRevit er installert sentralt av IT til " +
        "'Program Files', som normalt er skrivebeskyttet for vanlige " +
        "brukere. Proev en av disse:`n" +
        "  1. Hoyreklikk PowerShell -> 'Kjor som administrator', kjor " +
        "setup.ps1 paa nytt derfra (kun for dette ene steget)`n" +
        "  2. Be IT-avdelingen gi deg skrive-tilgang til denne mappen`n" +
        "  3. Be IT installere pyRevit paa nytt som brukerinstallasjon " +
        "(uten admin-rettigheter), som installerer til %APPDATA% i stedet"
    )
    exit 1
}

# ============================================================
#  2. Finn en lokal Python med samme hovedversjon
# ============================================================
Skriv-Steg "Leter etter Python $maalVersjon.x paa maskinen"

$pythonExe = $null

# Proev "py"-launcheren foerst - lister alle installerte versjoner presist
try {
    $pyListe = & py -0p 2>$null
    foreach ($linje in $pyListe) {
        if ($linje -match "$major\.$minor.*?(\S*python\.exe)") {
            $pythonExe = $Matches[1]
            break
        }
    }
} catch {}

# Fallback: sjekk om "python" i PATH tilfeldigvis stemmer
if (-not $pythonExe) {
    try {
        $verOutput = (& python --version 2>&1) -join ""
        if ($verOutput -match "Python $major\.$minor") {
            $pythonExe = (Get-Command python).Source
        }
    } catch {}
}

if (-not $pythonExe) {
    # Kjente, bekreftede fullversjoner per hovedversjon (siste utgivelse
    # MED Windows-installer - nyere delversjoner har ofte kun kildekode,
    # se README). Utvid denne listen etter hvert som flere hovedversjoner
    # er testet og bekreftet aa fungere.
    $kjenteVersjoner = @{
        "3.12" = "3.12.10"
    }

    Write-Host ""
    Write-Host "Fant ingen installert Python $maalVersjon.x." -ForegroundColor Yellow

    if ($kjenteVersjoner.ContainsKey($maalVersjon)) {
        $fullVersjon = $kjenteVersjoner[$maalVersjon]
        Write-Host "Scriptet kan laste ned og installere Python $fullVersjon automatisk:"
        Write-Host "  - Ingen administrator-rettigheter noedvendig (per-bruker-installasjon)"
        Write-Host "  - Legges IKKE til i PATH (paavirker ikke andre Python-installasjoner du har)"
        Write-Host "  - Installeres til standard per-bruker-mappe (samme som en vanlig manuell installasjon)"
        Write-Host ""
        $svar = Read-Host "Vil du at scriptet gjoer dette automatisk? (j/n)"

        if ($svar -match "^[jJ]") {
            Write-Host ""
            Write-Host "Laster ned Python $fullVersjon ..."
            $installerUrl = "https://www.python.org/ftp/python/$fullVersjon/python-$fullVersjon-amd64.exe"
            $installerPath = Join-Path $env:TEMP "python-$fullVersjon-amd64.exe"
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

            Write-Host "Installerer stille (per bruker, ingen admin) - kan ta et minutt ..."
            $installArgs = @("/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_test=0")
            Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

            $forventetSti = "$env:LOCALAPPDATA\Programs\Python\Python$major$minor\python.exe"
            if (Test-Path $forventetSti) {
                $pythonExe = $forventetSti
                Write-Host "Python $fullVersjon installert." -ForegroundColor Green
            } else {
                Write-Host "Installasjonen ser ut til aa ha kjort, men fant ikke python.exe paa forventet sted:" -ForegroundColor Yellow
                Write-Host "  $forventetSti"
                $pythonExe = Read-Host "Lim inn full sti til python.exe (Enter for aa avbryte)"
            }
        }
    } else {
        Write-Host "Automatisk nedlasting er ikke satt opp for Python $maalVersjon ennaa."
    }

    if (-not $pythonExe) {
        Write-Host ""
        Write-Host "Last ned manuelt fra: https://www.python.org/downloads/release/  (soek opp Python $maalVersjon)"
        Write-Host "NB: sjekk at siden faktisk har en 'Windows installer (64-bit)' - noen delversjoner har kun kildekode."
        Write-Host "IKKE huk av 'Add to PATH' under installasjonen."
        Write-Host ""
        $pythonExe = Read-Host "Lim inn full sti til python.exe naar installert (Enter for aa avbryte)"
    }

    if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
        Write-Error "Ingen gyldig python.exe oppgitt. Avbryter."
        exit 1
    }
}
Write-Host "Bruker: $pythonExe" -ForegroundColor Green

# ============================================================
#  3. Installer numpy/rasterio/pyproj i pyRevit sin site-packages
# ============================================================
Skriv-Steg "Sjekker numpy, rasterio, pyproj"

$paakrevdePakker = @("numpy", "rasterio", "pyproj")
$alleredeInstallert = $true
foreach ($pakke in $paakrevdePakker) {
    if (-not (Test-Path (Join-Path $sitePackages $pakke))) {
        $alleredeInstallert = $false
        break
    }
}

if ($alleredeInstallert) {
    Write-Host "numpy, rasterio og pyproj ser allerede ut til å være installert - hopper over." -ForegroundColor Green
} else {
    Write-Host "Installerer numpy, rasterio, pyproj ..."
    & $pythonExe -m pip install --target $sitePackages numpy rasterio pyproj
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install feilet - se meldingen over."
        exit 1
    }
    Write-Host "Pakker installert i $sitePackages" -ForegroundColor Green
}

# ============================================================
#  4. Hent WebView2-komponentene automatisk fra NuGet
# ============================================================
Skriv-Steg "Sjekker WebView2-komponenter"

$dllFiler = @("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.Wpf.dll", "WebView2Loader.dll")
$alleDllFinnes = $true
foreach ($dll in $dllFiler) {
    if (-not (Test-Path (Join-Path $PushbuttonDir $dll))) {
        $alleDllFinnes = $false
        break
    }
}

if ($alleDllFinnes) {
    Write-Host "WebView2-filene finnes allerede i pushbutton-mappen - hopper over." -ForegroundColor Green
} else {
    Write-Host "Henter WebView2-komponenter fra NuGet ..."
    $webview2Versjon = "1.0.4078.44"
    $nupkgUrl = "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/$webview2Versjon"
    $tempDir = Join-Path $env:TEMP "webview2_nuget_$(Get-Random)"
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    $nupkgPath = Join-Path $tempDir "webview2.zip"

    try {
        Invoke-WebRequest -Uri $nupkgUrl -OutFile $nupkgPath
        Expand-Archive -Path $nupkgPath -DestinationPath $tempDir -Force

        $coreDll = Get-ChildItem $tempDir -Recurse -Filter "Microsoft.Web.WebView2.Core.dll" |
            Where-Object { $_.FullName -like "*net462*" } | Select-Object -First 1
        $wpfDll = Get-ChildItem $tempDir -Recurse -Filter "Microsoft.Web.WebView2.Wpf.dll" |
            Where-Object { $_.FullName -like "*net462*" } | Select-Object -First 1
        $loaderDll = Get-ChildItem $tempDir -Recurse -Filter "WebView2Loader.dll" |
            Where-Object { $_.FullName -like "*win-x64*" } | Select-Object -First 1

        if (-not $coreDll -or -not $wpfDll -or -not $loaderDll) {
            throw "Fant ikke alle tre filene i NuGet-pakken. Sjekk mappestrukturen manuelt i: $tempDir"
        }

        Copy-Item $coreDll.FullName -Destination $PushbuttonDir -Force
        Copy-Item $wpfDll.FullName -Destination $PushbuttonDir -Force
        Copy-Item $loaderDll.FullName -Destination $PushbuttonDir -Force
        Write-Host "WebView2-filer kopiert til pushbutton-mappen." -ForegroundColor Green
    } finally {
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ============================================================
#  5. Sjekk WebView2 Runtime (kan ikke installeres uten admin,
#     men kan sjekkes)
# ============================================================
Skriv-Steg "Sjekker WebView2 Runtime"

$runtimeKey = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
if (Test-Path $runtimeKey) {
    Write-Host "WebView2 Runtime funnet." -ForegroundColor Green
} else {
    Write-Host "Fant ikke WebView2 Runtime i registeret." -ForegroundColor Yellow
    Write-Host "Test manuelt i nettleseren: https://go.microsoft.com/fwlink/p/?LinkId=2124703"
}

Skriv-Steg "Oppsett ferdig"
Write-Host "Restart Revit HELT (ikke bare Reload), aapne et prosjekt med" -ForegroundColor Cyan
Write-Host "Project Base Point satt, og trykk 'Lag Toposolid'." -ForegroundColor Cyan
