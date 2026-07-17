[CmdletBinding()]
param(
    [string]$BaseUrl = $(
        if ([string]::IsNullOrWhiteSpace($env:MODELRIG_BASE_URL)) {
            "http://127.0.0.1:8080"
        } else {
            $env:MODELRIG_BASE_URL
        }
    ),
    [string]$PlannerModel = $env:KALIV_AGENT3_PLANNER_MODEL,
    [string]$ReportPath = "",
    [switch]$ApproveWrite,
    [switch]$SkipReadinessRegeneration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $ReportPath = Join-Path $repoRoot "validation/agent3-rig-validation-latest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($ReportPath)) {
    $ReportPath = Join-Path $repoRoot $ReportPath
}
$ReportPath = [System.IO.Path]::GetFullPath($ReportPath)

if ([string]::IsNullOrWhiteSpace($env:MODELRIG_TOKEN)) {
    throw "MODELRIG_TOKEN mangler. Brug et paired device-token i miljøet; skriv det ikke på kommandolinjen."
}
if ([string]::IsNullOrWhiteSpace($PlannerModel)) {
    throw "Planner-model mangler. Sæt KALIV_AGENT3_PLANNER_MODEL eller brug -PlannerModel."
}

$reportDirectory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null

# Child processes and the local readiness generator now use the exact same
# absolute report. This cannot change an already-running worker process; the
# status check below proves whether that worker was started with the same path.
$env:MODELRIG_BASE_URL = $BaseUrl
$env:KALIV_AGENT3_PLANNER_MODEL = $PlannerModel
$env:KALIV_AGENT3_VALIDATION_REPORT = $ReportPath

$evidenceArgs = @(
    (Join-Path $repoRoot "scripts\agent3_rig_evidence.py"),
    "--base-url", $BaseUrl,
    "--planner-model", $PlannerModel,
    "--report", $ReportPath
)
if ($ApproveWrite) {
    $evidenceArgs += "--approve-write"
}

Write-Host "[1/3] Kører fysisk Agent3-evidens mod $BaseUrl"
& python @evidenceArgs
if ($LASTEXITCODE -ne 0) {
    throw "Agent3-evidens fejlede med exit code $LASTEXITCODE. Rapport: $ReportPath"
}

Write-Host "[2/3] Kontrollerer at den kørende worker vurderer samme rapport"
$headers = @{ Authorization = "Bearer $env:MODELRIG_TOKEN" }
$status = Invoke-RestMethod `
    -Method Get `
    -Uri ($BaseUrl.TrimEnd("/") + "/api/v1/experimental/agent3/status") `
    -Headers $headers
$rig = $status.rig_validation
if ($null -eq $rig) {
    throw "Agent3-status mangler rig_validation. Backend/worker er ikke den forventede build."
}
if ($rig.configured -ne $true) {
    throw (
        "Evidensen er skrevet, men workeren blev ikke startet med rapportstien. " +
        "Sæt KALIV_AGENT3_VALIDATION_REPORT='$ReportPath' før worker-start, genstart workeren og kør kommandoen igen."
    )
}
if ($rig.present -ne $true) {
    $reasons = @($rig.reasons) -join ", "
    throw (
        "Workeren kan ikke se rapporten på sin konfigurerede sti. " +
        "Forventet lokal rapport: $ReportPath. Blockers: $reasons"
    )
}

# `configured` + `present` only proves that the worker can see a report. Bind
# its assessment to the exact bytes produced above, so another valid or stale
# report on a different configured path cannot satisfy this command.
$remoteShaProperty = $rig.PSObject.Properties["report_sha256"]
if ($null -eq $remoteShaProperty -or [string]::IsNullOrWhiteSpace([string]$remoteShaProperty.Value)) {
    throw "Worker-status mangler report_sha256; samme-rapport-binding kan ikke bevises."
}
$localSha = (Get-FileHash -LiteralPath $ReportPath -Algorithm SHA256).Hash.ToLowerInvariant()
$remoteSha = ([string]$remoteShaProperty.Value).ToLowerInvariant()
if ($remoteSha -ne $localSha) {
    throw (
        "Workeren vurderer en anden rapport end den netop producerede. " +
        "Lokal SHA-256: $localSha. Worker SHA-256: $remoteSha. " +
        "Kontroller KALIV_AGENT3_VALIDATION_REPORT og genstart workeren."
    )
}

if ($rig.eligible_for_developer_preview -ne $true) {
    $reasons = @($rig.reasons) -join ", "
    throw "Rapporten blev fundet, men promotion-gaten afviste den: $reasons"
}
if ($rig.production_activation -ne $false) {
    throw "Sikkerhedsbrud: status må aldrig sætte production_activation=true."
}

if (-not $SkipReadinessRegeneration) {
    Write-Host "[3/3] Regenererer lokal ACTIVATION_READINESS.md fra samme rapport"
    & python (Join-Path $repoRoot "scripts\activation_readiness.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Evidensen bestod, men readiness-generatoren fejlede med exit code $LASTEXITCODE."
    }
} else {
    Write-Host "[3/3] Readiness-regenerering blev eksplicit sprunget over"
}

$level = if ($rig.eligible_for_write_pilot -eq $true) { "write-pilot" } else { "developer-preview" }
Write-Host "PASS: fysisk Agent3-evidens er synlig for workeren ($level, production_activation=false)"
Write-Host "Rapport: $ReportPath"
Write-Host "SHA-256: $localSha"
