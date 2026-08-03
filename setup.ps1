<#
.SYNOPSIS
  Automatisk engangsoppsett for KartverketToposolid PyRevit-utvidelsen.

.DESCRIPTION
  Kjores EN gang per PC, etter at repoet er klonet og koblet til PyRevit
  (se README.md steg 1-3). Automatiserer:
    - Henter WebView2-komponentene fra NuGet (i stedet for manuell
      nedlasting + endre filendelse + pakke ut + finne riktige filer)
    - Finner/verifiserer riktig Python-versjon og installerer
      numpy/rasterio/pyproj rett inn i pyRevit sin site-packages

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

$cengineRoot = "$env:APPDATA\pyRevit-Master\bin\cengines"
if (-not (Test-Path $cengineRoot)) {
    Write-Error "Fant ikke $cengineRoot - er pyRevit installert, og er CPython-motoren aktivert (pyRevit-fanen -> Settings)?"
    exit 1
}
$cengineDir = Get-ChildItem $cengineRoot -Directory | Where-Object { $_.Name -like "CPY*" } | Select-Object -First 1
if (-not $cengineDir) {
    Write-Error "Fant ingen CPython-motor under $cengineRoot. Aktiver CPython-motoren i pyRevit sine innstillinger foerst."
    exit 1
}
$verDigits = $cengineDir.Name -replace "CPY", ""      # f.eks "3123"
$major = $verDigits.Substring(0, 1)
$minor = $verDigits.Substring(1, 2)
$maalVersjon = "$major.$minor"
Write-Host "PyRevit bruker Python $maalVersjon (motor: $($cengineDir.Name))"

$sitePackages = "$env:APPDATA\pyRevit-Master\site-packages"
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

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
    Write-Host ""
    Write-Host "Fant ingen installert Python $maalVersjon.x." -ForegroundColor Yellow
    Write-Host "Last ned fra: https://www.python.org/downloads/release/  (soek opp Python $maalVersjon)"
    Write-Host "NB: sjekk at siden faktisk har en 'Windows installer (64-bit)' - noen delversjoner har kun kildekode."
    Write-Host "IKKE huk av 'Add to PATH' under installasjonen."
    Write-Host ""
    $pythonExe = Read-Host "Lim inn full sti til python.exe naar installert (Enter for aa avbryte)"
    if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
        Write-Error "Ingen gyldig python.exe oppgitt. Avbryter."
        exit 1
    }
}
Write-Host "Bruker: $pythonExe" -ForegroundColor Green

# ============================================================
#  3. Installer numpy/rasterio/pyproj i pyRevit sin site-packages
# ============================================================
Skriv-Steg "Installerer numpy, rasterio, pyproj"

& $pythonExe -m pip install --target $sitePackages numpy rasterio pyproj
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install feilet - se meldingen over."
    exit 1
}
Write-Host "Pakker installert i $sitePackages" -ForegroundColor Green

# ============================================================
#  4. Hent WebView2-komponentene automatisk fra NuGet
# ============================================================
Skriv-Steg "Henter WebView2-komponenter fra NuGet"

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
