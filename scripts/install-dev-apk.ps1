# install-dev-apk.ps1 -- get the APK for this checkout's HEAD onto the phone.
#
# The phone side of the development channel (see DEV_APPLIANCE.md). CI's
# candidate-apk workflow builds a debug APK signed with the same modelrig
# key as the release and with the same package id, so it installs OVER the
# release app and keeps the pairing. This script dispatches that build for
# origin/main's tip if no artifact exists yet, waits for it, downloads it,
# and installs it over adb.
#
# Not evidence: the a425f physical-test app and the candidate freeze are
# separate, candidate-bound builds. This is the everyday loop only.
#
# Usage (PowerShell on the rig, GITHUB_TOKEN/GH_TOKEN set, phone on adb):
#   .\scripts\install-dev-apk.ps1                 # build (if needed) + install HEAD
#   .\scripts\install-dev-apk.ps1 -ApkPath x.apk  # install a given APK, no CI

[CmdletBinding()]
param(
    [string]$ApkPath = "",
    [string]$Serial = "",
    [int]$TimeoutMinutes = 25
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-Adb {
    param([string[]]$Arguments)
    $argv = @()
    if ($Serial) { $argv += @("-s", $Serial) }
    $argv += $Arguments
    & adb @argv
}

# --- phone ---------------------------------------------------------------------
if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { throw "adb mangler i PATH." }
$devices = @(& adb devices | Select-String "\sdevice$" | ForEach-Object { ($_ -split "\s+")[0] })
if (-not $Serial) {
    if ($devices.Count -ne 1) { throw "Forventede EN adb-enhed, fandt $($devices.Count). Angiv -Serial." }
    $Serial = $devices[0]
}
Write-Host "  enhed: $Serial" -ForegroundColor DarkGray

# --- APK -----------------------------------------------------------------------
if (-not $ApkPath) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "gh mangler i PATH." }
    if (-not $env:GH_TOKEN -and -not $env:GITHUB_TOKEN) { throw "GH_TOKEN/GITHUB_TOKEN mangler." }
    if (-not $env:GH_TOKEN) { $env:GH_TOKEN = $env:GITHUB_TOKEN }

    & git -C $repoRoot fetch -q origin main
    $tip = (& git -C $repoRoot rev-parse origin/main).Trim()
    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($head -ne $tip) {
        Write-Host "  HEAD ($($head.Substring(0,10))) er ikke origin/main ($($tip.Substring(0,10))). CI bygger origin/main." -ForegroundColor Yellow
    }
    $artifact = "kaliv-candidate-apk-$tip"

    function Get-CompletedRun {
        $json = & gh run list --repo Ternedal/ModelRig --workflow candidate-apk.yml --branch main --limit 10 --json databaseId,headSha,status,conclusion 2>$null
        if (-not $json) { return $null }
        foreach ($r in ($json | ConvertFrom-Json)) {
            if ($r.headSha -eq $tip -and $r.status -eq "completed") { return $r }
        }
        return $null
    }

    $run = Get-CompletedRun
    if (-not $run) {
        Write-Host "  Ingen faerdig APK for $($tip.Substring(0,10)) -- bestiller CI-byg..." -ForegroundColor DarkGray
        & gh workflow run candidate-apk.yml --repo Ternedal/ModelRig --ref main | Out-Null
        $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
        do {
            Start-Sleep -Seconds 30
            $run = Get-CompletedRun
            if (-not $run) { Write-Host "  venter paa CI..." -ForegroundColor DarkGray }
        } while (-not $run -and (Get-Date) -lt $deadline)
        if (-not $run) { throw "CI blev ikke faerdig inden $TimeoutMinutes min." }
    }
    if ($run.conclusion -ne "success") { throw "CI-byg $($run.databaseId) endte som '$($run.conclusion)'." }

    $dest = Join-Path $env:TEMP ("kaliv-dev-apk-" + $tip.Substring(0, 10))
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    & gh run download $run.databaseId --repo Ternedal/ModelRig -n $artifact -D $dest
    if ($LASTEXITCODE -ne 0) { throw "Download af $artifact fejlede." }
    $ApkPath = (Get-ChildItem $dest -Filter *.apk -Recurse | Select-Object -First 1).FullName
    if (-not $ApkPath) { throw "Ingen .apk i $dest." }
}
if (-not (Test-Path -LiteralPath $ApkPath -PathType Leaf)) { throw "APK findes ikke: $ApkPath" }

# --- install -------------------------------------------------------------------
# -r: over the installed app (same key, same package id, pairing kept).
# -d: allow a lower versionCode -- a dev build may carry a smaller number
#     than the release it replaces, and that is fine on the development channel.
Write-Host "  installerer $ApkPath" -ForegroundColor DarkGray
Invoke-Adb -Arguments @("install", "-r", "-d", $ApkPath)
if ($LASTEXITCODE -ne 0) { throw "adb install fejlede." }
$installed = Invoke-Adb -Arguments @("shell", "dumpsys", "package", "dk.ternedal.modelrig")
$version = ($installed | Select-String "versionName=").Line
Write-Host ""
Write-Host "  DEV-APK INSTALLERET -- $($version.Trim())" -ForegroundColor Green
Write-Host "  Aabn Kaliv; parringen er bevaret. Tilbage til release: installer release-APK'en igen." -ForegroundColor DarkGray
