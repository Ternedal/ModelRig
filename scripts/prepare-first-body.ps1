<#
.SYNOPSIS
    One command from a VRM file to a body the rig serves: build, install,
    select, configure and verify.

.DESCRIPTION
    Chapter 1 of docs/bodyrig/FIRST_LIVE_BODY.md, run end to end. It builds a
    .mrbody from the avatar plus a demo identity, installs it in the profile
    store, selects it as current, writes KALIV_BODY_STORE into the appliance
    env if it is missing, and then PROVES the result by pairing a throwaway
    device and reading /body/active and /body/frames back.

    The verification is the point. Every earlier step can succeed and still
    leave the renderer with nothing to show -- a store the worker cannot read,
    an env key that never reached the running process. This asks the rig the
    same question the renderer will.

    The demo identity is a fixture, not a person: rebuild from real tracking
    (chapter 5) when the pipeline has run.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\prepare-first-body.ps1 -Vrm C:\Users\admin\Desktop\Kaliv.vrm
#>
param(
    [Parameter(Mandatory = $true)][string]$Vrm,
    [string]$Name = "Kaliv",
    [string]$ApplianceDir = "",
    [string]$Store = "",
    [string]$BackendUrl = "http://127.0.0.1:8080",
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "Read-KalivEnvFile.ps1")

if ([string]::IsNullOrWhiteSpace($ApplianceDir)) {
    $ApplianceDir = Join-Path (Split-Path -Parent $repoRoot) "ModelRig-appliance"
}
if ([string]::IsNullOrWhiteSpace($Store)) {
    $Store = Join-Path $ApplianceDir "bodyrig-profiles"
}
$envFile = Join-Path $ApplianceDir "modelrig.env"

if (-not (Test-Path -LiteralPath $Vrm -PathType Leaf)) {
    throw "VRM ikke fundet: $Vrm  (VRoid Studio -> eksporter som VRM 1.0)"
}
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Appliance-env ikke fundet: $envFile  (angiv -ApplianceDir)"
}

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  FOERSTE KROP -- fra VRM til en krop riggen serverer" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  avatar:    $Vrm"
Write-Host "  navn:      $Name"
Write-Host "  store:     $Store"

# 1. Build + install + select, through the tool that already does exactly that.
Write-Host ""
Write-Host "  [1/4] bygger, installerer og vaelger kroppen..."
$demo = & python (Join-Path $repoRoot "scripts\bodyrig_demo_body.py") --vrm $Vrm --name $Name --store $Store 2>&1
if ($LASTEXITCODE -ne 0) {
    $demo | ForEach-Object { Write-Host "        $_" }
    throw "bodyrig_demo_body.py fejlede -- se linjerne ovenfor."
}
$result = ($demo -join "`n") | ConvertFrom-Json
$bodyId = $result.body_id
Write-Host "        body_id: $bodyId"

# 2. The env key, only if it is missing or points elsewhere.
Write-Host "  [2/4] KALIV_BODY_STORE i appliance-env..."
$appEnv = Read-KalivEnvFile -Path $envFile
$current = if ($appEnv.ContainsKey("KALIV_BODY_STORE")) { $appEnv["KALIV_BODY_STORE"] } else { "" }
if ($current -eq $Store) {
    Write-Host "        allerede sat korrekt"
    $envChanged = $false
} elseif ([string]::IsNullOrWhiteSpace($current)) {
    $raw = Get-Content -LiteralPath $envFile -Raw
    if ($raw.Length -gt 0 -and -not $raw.EndsWith("`n")) { $raw += "`r`n" }
    # Written the way the env parser reads it: KEY=value, no quotes.
    Set-Content -LiteralPath $envFile -Value ($raw + "KALIV_BODY_STORE=$Store`r`n") -NoNewline -Encoding ASCII
    Write-Host "        tilfoejet"
    $envChanged = $true
} else {
    Write-Host "        ADVARSEL: env peger paa '$current', ikke '$Store'." -ForegroundColor Yellow
    Write-Host "        Roerer den ikke. Ret den selv, eller koer med -Store '$current'." -ForegroundColor Yellow
    $envChanged = $false
}

if ($SkipVerify) {
    Write-Host ""
    Write-Host "  Sprunget verifikation over (-SkipVerify)." -ForegroundColor Yellow
    Write-Host "  Genstart dev-appliancen, hvis env blev aendret." -ForegroundColor Yellow
    exit 0
}

# 3. Ask the rig the same question the renderer will.
Write-Host "  [3/4] parrer en engangsenhed og spoerger riggen..."
if ($envChanged) {
    Write-Host "        BEMAERK: env blev aendret -- den koerende worker har den GAMLE." -ForegroundColor Yellow
    Write-Host "        Koer STOP_DEV_APPLIANCE + START_DEV_APPLIANCE og dette script igen." -ForegroundColor Yellow
}
try {
    $pair = Invoke-RestMethod -Method Post -Uri "$BackendUrl/api/v1/pair/start" -TimeoutSec 10
    $claimBody = @{ device_name = "first-body-$(Get-Random)"; code = $pair.code } | ConvertTo-Json -Compress
    $claim = Invoke-RestMethod -Method Post -Uri "$BackendUrl/api/v1/pair/claim" -ContentType "application/json" -Body $claimBody -TimeoutSec 10
    $headers = @{ Authorization = "Bearer $($claim.token)" }
} catch {
    throw "Kunne ikke parre mod $BackendUrl -- koerer dev-appliancen? ($($_.Exception.Message))"
}

$manifest = $null
try {
    $manifest = Invoke-RestMethod -Headers $headers -Uri "$BackendUrl/api/v1/body/active" -TimeoutSec 15
} catch {
    $code = $null
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    if ($code -eq 503) {
        throw "Riggen svarer 503: KALIV_BODY_STORE naaede ikke den koerende worker. Genstart dev-appliancen og koer igen."
    }
    throw "GET /body/active fejlede (HTTP $code): $($_.Exception.Message)"
}
if ($manifest.body_id -ne $bodyId) {
    throw "Riggen serverer en ANDEN krop ($($manifest.body_id)) end den netop valgte ($bodyId)."
}
Write-Host "        /body/active: $($manifest.name) [$($manifest.source)]"

# 4. Frames: the renderer's actual feed.
Write-Host "  [4/4] laeser tre frames..."
$frames = Invoke-RestMethod -Headers $headers -Uri "$BackendUrl/api/v1/body/frames?limit=3" -TimeoutSec 20
$lines = @($frames -split "`n" | Where-Object { $_.StartsWith("data: ") })
if ($lines.Count -lt 3) {
    throw "Fik kun $($lines.Count) frames af 3 -- streamen leverer ikke."
}
$first = ($lines[0].Substring(6)) | ConvertFrom-Json
Write-Host "        state=$($first.state) type=$($first.type)/$($first.version)"

Write-Host ""
Write-Host "  KROPPEN ER KLAR." -ForegroundColor Green
Write-Host "  body_id: $bodyId"
Write-Host ""
Write-Host "  Naeste: Unity-gaten (afsnit 2 i docs/bodyrig/FIRST_LIVE_BODY.md)."
Write-Host "  Til live-tilstand i Unity:"
Write-Host "    `$env:BODYRIG_RIG_URL   = `"$BackendUrl`""
Write-Host "    `$env:BODYRIG_RIG_TOKEN = `"$($claim.token)`""
Write-Host ""
