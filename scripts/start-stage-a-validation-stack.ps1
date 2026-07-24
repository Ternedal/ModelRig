[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$PlannerModel,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ValidationReport,

    [ValidateNotNullOrEmpty()]
    [string]$BackendHost = "127.0.0.1",

    [string]$PairingData,

    [switch]$EnableSchedulerApi,

    [switch]$EnableScheduler,

    [string]$SchedulerDataDir,

    [string]$SchedulerApprovalSecret,

    [ValidateRange(5, 3600)]
    [double]$SchedulerPollSeconds = 15,

    [string]$WorkerLog,

    [switch]$HeadlessWorker,

    [switch]$WorkerOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot "validation\stage-a-runtime"
$backendExe = Join-Path $runtimeDir "modelrig-server-stage-a.exe"
$backendCmd = Join-Path $runtimeDir "backend.cmd"
$workerCmd = Join-Path $runtimeDir "worker.cmd"

function Resolve-RepoPath {
    param([string]$Value, [string]$Label, [switch]$CreateDirectory)
    if ([string]::IsNullOrWhiteSpace($Value)) { throw "$Label mangler." }
    $candidate = if ([IO.Path]::IsPathRooted($Value)) { $Value } else { Join-Path $repoRoot $Value }
    $resolved = [IO.Path]::GetFullPath($candidate)
    if ($CreateDirectory) {
        New-Item -ItemType Directory -Path $resolved -Force | Out-Null
    }
    else {
        $parent = Split-Path $resolved -Parent
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
    }
    return $resolved
}

function Escape-CmdValue {
    param([string]$Value)
    if ($Value -match '[\r\n"]') { throw "En runtime-værdi indeholder ugyldige tegn." }
    return $Value.Replace('%', '%%')
}

function Get-ListenerPid {
    param([int]$Port)
    try {
        $item = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
            Select-Object -First 1
        if ($null -ne $item) { return [int]$item.OwningProcess }
    }
    catch { }
    return $null
}

function Wait-PortFree {
    param([int]$Port, [string]$Label)
    $pidValue = Get-ListenerPid -Port $Port
    if ($null -eq $pidValue) { return }
    Write-Host ""
    Write-Host "  $Label bruger port $Port (proces $pidValue)." -ForegroundColor Yellow
    Write-Host "  Luk det gamle $Label-vindue. Scriptet fortsætter selv, når porten er fri."
    $deadline = (Get-Date).AddMinutes(5)
    while ($null -ne (Get-ListenerPid -Port $Port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
    }
    if ($null -ne (Get-ListenerPid -Port $Port)) { throw "Port $Port blev ikke frigivet inden for fem minutter." }
}

function Wait-Endpoint {
    param([string]$Url, [int]$Seconds = 90)
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return }
        }
        catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Tjenesten blev ikke klar: $Url"
}

function Start-WorkerCommand {
    $mode = if ($HeadlessWorker) { "/c" } else { "/k" }
    Start-Process -FilePath "cmd.exe" -ArgumentList $mode, ('"' + $workerCmd + '"') -WorkingDirectory $repoRoot | Out-Null
}

function Find-PairingData {
    if (-not [string]::IsNullOrWhiteSpace($PairingData)) {
        return Resolve-RepoPath -Value $PairingData -Label "PairingData"
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:MODELRIG_DATA) { $candidates.Add($env:MODELRIG_DATA) }
    $candidates.Add((Join-Path $repoRoot "modelrig-data.json"))
    $candidates.Add((Join-Path $repoRoot "scripts\modelrig-data.json"))
    $candidates.Add((Join-Path $env:USERPROFILE "Desktop\modelrig-data.json"))

    $listener = Get-ListenerPid -Port 8080
    if ($null -ne $listener) {
        try {
            $process = Get-Process -Id $listener -ErrorAction Stop
            if ($process.Path) {
                $candidates.Insert(0, (Join-Path (Split-Path $process.Path -Parent) "modelrig-data.json"))
            }
        }
        catch { }
    }

    $existing = @(
        $candidates |
            Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
            ForEach-Object { (Resolve-Path -LiteralPath $_).Path } |
            Select-Object -Unique
    )
    if ($existing.Count -eq 0) {
        throw "Kunne ikke finde riggens modelrig-data.json med pairing-data. Start den sædvanlige backend, sæt MODELRIG_DATA eller angiv -PairingData og kør igen."
    }
    return $existing[0]
}

if ($env:OS -ne "Windows_NT") { throw "Validation-stacken må kun startes på Windows-riggen." }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python blev ikke fundet på PATH." }
if (-not $WorkerOnly -and -not (Get-Command go -ErrorAction SilentlyContinue)) {
    throw "Go blev ikke fundet på PATH; den eksakte backend kan derfor ikke bygges fra kandidatens checkout."
}

$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($BackendHost, [ref]$parsedAddress)) {
    throw "BackendHost skal være en gyldig IP-adresse."
}
if ($EnableScheduler -and [string]::IsNullOrWhiteSpace($SchedulerDataDir)) {
    throw "SchedulerDataDir er påkrævet, når scheduleren aktiveres."
}
if (($EnableScheduler -or $EnableSchedulerApi) -and ([string]$SchedulerApprovalSecret).Length -lt 32) {
    throw "SchedulerApprovalSecret skal være mindst 32 tegn for scheduler-testen."
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$escapedRepo = Escape-CmdValue $repoRoot
$escapedReport = Escape-CmdValue ([IO.Path]::GetFullPath($ValidationReport))
$escapedSecret = Escape-CmdValue ([string]$SchedulerApprovalSecret)
$schedulerValue = if ($EnableScheduler) { "1" } else { "0" }
$schedulerApiValue = if ($EnableSchedulerApi) { "1" } else { "0" }
$schedulerEnv = ""
$workerCommand = 'python -u -m uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099'
$resolvedWorkerLog = $null
$resolvedSchedulerDir = $null

if ($EnableScheduler) {
    $resolvedSchedulerDir = Resolve-RepoPath -Value $SchedulerDataDir -Label "SchedulerDataDir" -CreateDirectory
    $escapedSchedulerDir = Escape-CmdValue $resolvedSchedulerDir
    $pollText = $SchedulerPollSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
    $schedulerEnv = @"
set "KALIV_SCHEDULER=$schedulerValue"
set "KALIV_SCHEDULER_POLL_S=$pollText"
set "KALIV_SCHEDULES_DB=$escapedSchedulerDir\kaliv-schedules.db"
set "MODELRIG_JOBS_DB=$escapedSchedulerDir\modelrig-jobs.db"
set "KALIV_AUDIT_DB=$escapedSchedulerDir\kaliv-audit.db"
set "KALIV_TOOLS_STATE=$escapedSchedulerDir\kaliv-tools-state.json"
set "KALIV_TOOLS_DIR=$escapedSchedulerDir\tools"
set "KALIV_SCHEDULER_APPROVAL_SECRET=$escapedSecret"
"@
    if (-not [string]::IsNullOrWhiteSpace($WorkerLog)) {
        $resolvedWorkerLog = Resolve-RepoPath -Value $WorkerLog -Label "WorkerLog"
        $escapedLog = Escape-CmdValue $resolvedWorkerLog
        $workerCommand += " >> `"$escapedLog`" 2>&1"
    }
}
else {
    $schedulerEnv = @"
set "KALIV_SCHEDULER=$schedulerValue"
set "KALIV_SCHEDULER_APPROVAL_SECRET="
"@
}

@"
@echo off
cd /d "$escapedRepo"
set "PYTHONPATH=$escapedRepo\worker"
set "PYTHONDONTWRITEBYTECODE=1"
set "KALIV_AGENT3_ENABLED=1"
set "KALIV_TOOLS_ENABLED=1"
set "KALIV_AGENT3_PLANNER_MODEL=$PlannerModel"
set "KALIV_AGENT3_VALIDATION_REPORT=$escapedReport"
$schedulerEnv
$workerCommand
"@ | Set-Content -LiteralPath $workerCmd -Encoding ASCII

if ($WorkerOnly) {
    Wait-PortFree -Port 8099 -Label "worker"
    Write-Host "  Starter exact-head worker..." -ForegroundColor Cyan
    Start-WorkerCommand
    Wait-Endpoint -Url "http://127.0.0.1:8099/healthz"
    Write-Host "  Exact-head worker er klar." -ForegroundColor Green
    return
}

$resolvedPairingData = Find-PairingData
$escapedData = Escape-CmdValue $resolvedPairingData
$escapedHost = Escape-CmdValue $BackendHost
Wait-PortFree -Port 8080 -Label "backend"
Wait-PortFree -Port 8099 -Label "worker"

Write-Host "  Bygger exact-head backend..." -ForegroundColor Cyan
Push-Location (Join-Path $repoRoot "backend")
try {
    & go build -o $backendExe .\cmd\modelrig-server
    if ($LASTEXITCODE -ne 0) { throw "Backend-build fejlede." }
}
finally { Pop-Location }

@"
@echo off
cd /d "$runtimeDir"
set "MODELRIG_HOST=$escapedHost"
set "MODELRIG_PORT=8080"
set "MODELRIG_DATA=$escapedData"
set "KALIV_AGENT3_ENABLED=1"
set "KALIV_SCHEDULER_API=$schedulerApiValue"
set "KALIV_SCHEDULER_APPROVAL_SECRET=$escapedSecret"
"$backendExe"
"@ | Set-Content -LiteralPath $backendCmd -Encoding ASCII

Write-Host "  Starter kandidatens backend og worker..." -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", ('"' + $backendCmd + '"') -WorkingDirectory $runtimeDir | Out-Null
Start-Sleep -Seconds 1
Start-WorkerCommand

Wait-Endpoint -Url "http://127.0.0.1:8080/healthz"
Wait-Endpoint -Url "http://127.0.0.1:8099/healthz"

Write-Host "  Exact-head validation-stack er klar." -ForegroundColor Green
Write-Host "  Backend-binding: $BackendHost"
Write-Host "  Pairing-data: $resolvedPairingData"
if ($EnableScheduler) {
    Write-Host "  Scheduler-data: $resolvedSchedulerDir"
    if ($resolvedWorkerLog) { Write-Host "  Worker-log: $resolvedWorkerLog" }
}
Write-Host "  Luk de nye konsolvinduer efter testen."
