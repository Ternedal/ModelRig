# start-dev-appliance.ps1 -- run the appliance straight from this checkout.
#
# THE DEVELOPMENT CHANNEL. Decided 02/09: as long as nothing is in
# production, the rig develops as fast as possible. That means the code on
# the appliance is whatever this checkout holds -- `git pull` + this script
# = new code running, with the operator's own data and env -- instead of a
# multi-session physical promotion for every change.
#
# What this deliberately does NOT do:
#   * It does not touch production_activation. Every PRODUCTION_ACTIVATION
#     constant stays False (the flip guard would fail CI if it did not), and
#     the physical promotion path (Stage A, the proof campaign, Stage B)
#     stays the bar for the day production becomes real.
#   * It does not produce evidence. Nothing it runs is candidate-bound, and
#     no gate reads its output. Do not cite a dev-appliance run in an issue
#     as proof of anything.
#   * It does not replace the release appliance permanently: -Stop restores
#     the KalivBootstrap task, so the signed release comes back.
#
# Usage (elevated PowerShell on the rig):
#   .\scripts\start-dev-appliance.ps1                 # build + run from HEAD
#   .\scripts\start-dev-appliance.ps1 -Stop           # back to the release appliance
#   .\scripts\start-dev-appliance.ps1 -ApplianceDir D:\ModelRig-appliance

[CmdletBinding()]
param(
    [switch]$Stop,
    [string]$ApplianceDir = "",
    [string]$BackendHost = "0.0.0.0",
    [int]$BackendPort = 8080,
    [int]$WorkerPort = 8099
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "Read-KalivEnvFile.ps1")

if ([string]::IsNullOrWhiteSpace($ApplianceDir)) {
    $ApplianceDir = Join-Path (Split-Path -Parent $repoRoot) "ModelRig-appliance"
}
$runtimeDir = Join-Path $repoRoot "validation\dev-appliance"
$stateFile = Join-Path $runtimeDir "state.json"

function Escape-CmdValue {
    param([string]$Value)
    if ($Value -match '[\r\n"]') { throw "En env-værdi indeholder ugyldige tegn: $Value" }
    return $Value.Replace('%', '%%')
}

function Get-ListenerPid {
    param([int]$Port)
    try {
        $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($c) { return [int]$c.OwningProcess }
    } catch { }
    return $null
}

function Stop-ReleaseAppliance {
    foreach ($task in "KalivSupervisor", "KalivBootstrap") {
        try { Stop-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null } catch { }
    }
    Get-Process modelrig-server-windows-x64, modelrig-worker-windows-x64, modelrig-supervisor-windows-x64 -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Stop-DevProcesses {
    if (Test-Path -LiteralPath $stateFile) {
        try {
            $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
            foreach ($id in @($state.backend_pid, $state.worker_pid)) {
                if ($id) { Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue }
            }
        } catch { }
        Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
    }
    foreach ($port in $BackendPort, $WorkerPort) {
        $owner = Get-ListenerPid -Port $port
        if ($owner) {
            $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
            if ($proc -and ($proc.ProcessName -match '^(python|modelrig-server-dev)$')) {
                Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

if ($Stop) {
    Stop-DevProcesses
    Start-Sleep -Seconds 2
    try { Start-ScheduledTask -TaskName KalivBootstrap -ErrorAction Stop } catch {
        Write-Host "KalivBootstrap kunne ikke startes: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    Write-Host "Dev-appliance stoppet. Release-appliancen starter via KalivBootstrap." -ForegroundColor Green
    exit 0
}

# --- preflight ---------------------------------------------------------------
if (-not (Get-Command go -ErrorAction SilentlyContinue)) { throw "go mangler i PATH." }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "python mangler i PATH." }
$envFile = Join-Path $ApplianceDir "modelrig.env"
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Fandt ikke $envFile. Angiv -ApplianceDir, eller opret env-filen først."
}
$head = (& git -C $repoRoot rev-parse HEAD).Trim()
$dirty = @(& git -C $repoRoot status --porcelain)
$appEnv = Read-KalivEnvFile -Path $envFile

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  KALIV DEV-APPLIANCE -- koerer direkte fra checkouten" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  HEAD:      $head" -ForegroundColor DarkGray
Write-Host "  tree:      $(if ($dirty.Count -eq 0) { 'rent' } else { "$($dirty.Count) aendrede filer (dev-mode tillader det)" })" -ForegroundColor DarkGray
Write-Host "  appliance: $ApplianceDir ($($appEnv.Count) env-noegler, kommentarer strippet)" -ForegroundColor DarkGray
Write-Host "  binding:   ${BackendHost}:$BackendPort / worker 127.0.0.1:$WorkerPort" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  IKKE BEVIST: dette er udviklingskanalen. production_activation" -ForegroundColor Yellow
Write-Host "  forbliver false; intet herfra taeller som evidens." -ForegroundColor Yellow
Write-Host ""

# --- release appliance down, ports free -------------------------------------
Stop-ReleaseAppliance
Stop-DevProcesses
Start-Sleep -Seconds 2
foreach ($port in $BackendPort, $WorkerPort) {
    $owner = Get-ListenerPid -Port $port
    if ($owner) { throw "Port $port er stadig optaget af pid $owner. Luk den, og koer igen." }
}
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

# --- build backend from HEAD -------------------------------------------------
$backendExe = Join-Path $runtimeDir "modelrig-server-dev.exe"
Write-Host "  Bygger backend fra HEAD..." -ForegroundColor DarkGray
Push-Location (Join-Path $repoRoot "backend")
try {
    & go build -o $backendExe .\cmd\modelrig-server
    if ($LASTEXITCODE -ne 0) { throw "Backend-build fejlede." }
} finally { Pop-Location }

# --- explicit env for both processes -----------------------------------------
# The appliance env is the source of truth; a few keys are pinned for dev
# mode so the phone can reach the backend and the worker sees the checkout.
$dataPath = if ($appEnv.ContainsKey('MODELRIG_DATA') -and $appEnv['MODELRIG_DATA']) { $appEnv['MODELRIG_DATA'] } else { Join-Path $ApplianceDir "modelrig-data.json" }
$overrides = @{
    'MODELRIG_HOST'          = $BackendHost
    'MODELRIG_PORT'          = "$BackendPort"
    'MODELRIG_DATA'          = $dataPath
    'MODELRIG_WORKER_URL'    = "http://127.0.0.1:$WorkerPort"
    'PYTHONPATH'             = (Join-Path $repoRoot "worker")
    'PYTHONDONTWRITEBYTECODE' = '1'
}
$merged = @{}
foreach ($k in $appEnv.Keys) { $merged[$k] = $appEnv[$k] }
foreach ($k in $overrides.Keys) { $merged[$k] = $overrides[$k] }

$setLines = ($merged.Keys | Sort-Object | ForEach-Object { 'set "' + $_ + '=' + (Escape-CmdValue ([string]$merged[$_])) + '"' }) -join "`r`n"
$escapedRepo = Escape-CmdValue $repoRoot

$backendCmd = Join-Path $runtimeDir "backend.cmd"
@"
@echo off
title Kaliv DEV backend ($($head.Substring(0,10)))
cd /d "$escapedRepo"
$setLines
"$(Escape-CmdValue $backendExe)"
"@ | Set-Content -LiteralPath $backendCmd -Encoding ASCII

$workerCmd = Join-Path $runtimeDir "worker.cmd"
@"
@echo off
title Kaliv DEV worker ($($head.Substring(0,10)))
cd /d "$escapedRepo"
$setLines
python -u -m uvicorn app.entrypoint:app --host 127.0.0.1 --port $WorkerPort
"@ | Set-Content -LiteralPath $workerCmd -Encoding ASCII

# --- start ---------------------------------------------------------------------
$worker = Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "`"$workerCmd`"" -PassThru
$backend = Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "`"$backendCmd`"" -PassThru
@{ head = $head; backend_pid = $backend.Id; worker_pid = $worker.Id; started_at = (Get-Date).ToString("o") } |
    ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8

$deadline = (Get-Date).AddSeconds(90)
$backendOk = $false; $workerOk = $false; $version = $null
while ((Get-Date) -lt $deadline -and -not ($backendOk -and $workerOk)) {
    Start-Sleep -Seconds 2
    if (-not $workerOk) { try { Invoke-RestMethod "http://127.0.0.1:$WorkerPort/healthz" -TimeoutSec 2 | Out-Null; $workerOk = $true } catch { } }
    if (-not $backendOk) { try { $h = Invoke-RestMethod "http://127.0.0.1:$BackendPort/healthz" -TimeoutSec 2; $version = $h.version; $backendOk = $true } catch { } }
}
if (-not ($backendOk -and $workerOk)) {
    throw "Stacken kom ikke op inden 90 s (backend=$backendOk worker=$workerOk). Se de to konsolvinduer."
}
Write-Host ""
Write-Host "  DEV-APPLIANCE OPPE -- version $version fra HEAD $($head.Substring(0,10))" -ForegroundColor Green
Write-Host "  Telefonen naar backend paa http://<rig-LAN-ip>:$BackendPort (binding $BackendHost)." -ForegroundColor DarkGray
Write-Host "  Ny kode: git pull, og koer scriptet igen. Tilbage til release: -Stop." -ForegroundColor DarkGray
Write-Host ""
