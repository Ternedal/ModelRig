# Safe operator entrypoint for V1 physical campaign preflight.
# Does not start services, alter repositories or activate production.
[CmdletBinding()]
param(
    [string]$Workspace = 'C:\Rig\src',
    [string]$OutputRoot = 'C:\Rig\validation\v1-physical',
    [switch]$SkipHardwareInventory
)
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'kaliv_v1_physical_preflight.py'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Missing preflight script: $scriptPath"
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw 'Python not found in PATH; preflight cannot run.'
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'
$report = Join-Path $OutputRoot "preflight-$stamp.json"
Write-Host "Kaliv V1 physical preflight (read-only)"
Write-Host "Workspace: $Workspace"
Write-Host "Report: $report"
& $python.Source $scriptPath --workspace $Workspace --output $report
$code = $LASTEXITCODE
if (-not $SkipHardwareInventory) {
    $hardwareScript = Join-Path $PSScriptRoot "kaliv_v1_hardware_smoke.py"
    $hardwareReport = Join-Path $OutputRoot "hardware-$stamp.json"
    & $python.Source $hardwareScript --output $hardwareReport
    $hardwareCode = $LASTEXITCODE
    Write-Host "Hardware inventory: $hardwareReport (exit $hardwareCode)"
    if ($hardwareCode -ne 0) { Write-Warning "GPU inventory unavailable or failed." }
}
if ($code -ne 0) {
    Write-Warning "Preflight blocked (exit $code). Inspect report: $report"
    exit $code
}
Write-Host "Preflight complete. Physical gates remain PENDING: $report"
