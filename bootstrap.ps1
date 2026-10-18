<#
.SYNOPSIS
  Ett-kommando-installasjon av KartverketToposolid - ingen Git nødvendig.

.DESCRIPTION
  Laster ned repoet som en zip-fil direkte fra GitHub, pakker det ut i
  Dokumenter\GitRepos\KartverketToposolid, og kjører setup.ps1
  automatisk etterpå. Beregnet for kolleger som bare skal BRUKE
  verktøyet - utviklere som skal endre koden bør heller bruke
  'git clone' (se README.md), slik at endringer kan committes.

  Kjøres normalt IKKE direkte - se bruksanvisning under, som henter
  denne filen fra GitHub og kjører den i samme slengen.

.USAGE
  Kjør denne ENE linjen i et vanlig PowerShell-vindu:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; irm https://raw.githubusercontent.com/Nordmo/KartverketToposolid/main/bootstrap.ps1 | iex
#>

$ErrorActionPreference = "Stop"

Write-Host "=== KartverketToposolid - installasjon ===" -ForegroundColor Cyan
Write-Host ""

$dokumenter = [Environment]::GetFolderPath("MyDocuments")
$gitReposMappe = Join-Path $dokumenter "GitRepos"
$maalMappe = Join-Path $gitReposMappe "KartverketToposolid"

New-Item -ItemType Directory -Force -Path $gitReposMappe | Out-Null
$avbrutt = $false

if (Test-Path $maalMappe) {
    if (Test-Path (Join-Path $maalMappe ".git")) {
        Write-Host "Mappen finnes allerede og er et git-repo:" -ForegroundColor Yellow
        Write-Host "  $maalMappe" -ForegroundColor Yellow
        Write-Host "Bruk 'git pull' der for å oppdatere i stedet - hopper over nedlasting." -ForegroundColor Yellow
    } else {
        Write-Host "Fjerner tidligere nedlastet versjon i $maalMappe ..."
        # PowerShell kan ikke slette mappen den selv står i (typisk når
        # kommandoen kjøres på nytt i samme vindu) - gå ut av den først.
        $her = (Get-Location).ProviderPath
        if ($her -and $her.StartsWith($maalMappe, [System.StringComparison]::OrdinalIgnoreCase)) {
            Set-Location $gitReposMappe
        }
        try {
            Remove-Item $maalMappe -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Host ""
            Write-Host "Kunne ikke fjerne den gamle versjonen - noen filer er i bruk." -ForegroundColor Red
            Write-Host "Vanligste årsak: Revit er åpent (WebView2-filene er lastet inn)." -ForegroundColor Red
            Write-Host "Lukk Revit helt og kjør kommandoen på nytt." -ForegroundColor Red
            Write-Host ""
            Write-Host "Detalj: $($_.Exception.Message)" -ForegroundColor DarkGray
            $avbrutt = $true
        }
    }
}

if (-not $avbrutt -and -not (Test-Path $maalMappe)) {
    Write-Host "Laster ned nyeste versjon fra GitHub ..."
    $zipUrl = "https://github.com/Nordmo/KartverketToposolid/archive/refs/heads/main.zip"
    $tempZip = Join-Path $env:TEMP "KartverketToposolid_$(Get-Random).zip"
    $tempUtpakket = Join-Path $env:TEMP "KartverketToposolid_utpakket_$(Get-Random)"

    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip
        Expand-Archive -Path $tempZip -DestinationPath $tempUtpakket -Force

        # GitHub sin zip pakker alt inn i en undermappe "<repo>-<branch>"
        # (f.eks. "KartverketToposolid-main") - flytt innholdet opp ett nivå.
        $innerFolder = Get-ChildItem $tempUtpakket -Directory | Select-Object -First 1
        if (-not $innerFolder) {
            throw "Fant ingen mappe inni den nedlastede zip-filen - noe gikk galt under utpakking."
        }
        Move-Item $innerFolder.FullName $maalMappe
        Write-Host "Lastet ned til: $maalMappe" -ForegroundColor Green
    } finally {
        Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tempUtpakket -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($avbrutt) {
    Write-Host ""
    Write-Host "Installasjonen ble avbrutt. Den gamle versjonen kan være delvis slettet," -ForegroundColor Yellow
    Write-Host "så lukk Revit og kjør kommandoen på nytt før du bruker knappene." -ForegroundColor Yellow
} else {
Write-Host ""
Write-Host "=== Starter setup.ps1 ===" -ForegroundColor Cyan
Write-Host ""

Push-Location $maalMappe
try {
    & (Join-Path $maalMappe "setup.ps1")
} finally {
    # Tilbake til der brukeren stod, slik at mappen ikke er "i bruk" av
    # dette PowerShell-vinduet neste gang kommandoen kjøres.
    Pop-Location
}
}
