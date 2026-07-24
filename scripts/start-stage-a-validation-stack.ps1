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

    [switch]$WorkerOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot "validation\stage-a-runtime"
$backendExe = Join-Path $runtimeDir "modelrig-server-stage-a.exe"
$backendCmd = Join-Path $runtimeDir "backend.cmd"
$workerCmd = Join-Path $runtimeDir "worker.cmd"

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

function Find-PairingData {
    if (-not [string]::IsNullOrWhiteSpace($PairingData)) {
        $fullPath = [IO.Path]::GetFullPath($PairingData, $repoRoot)
        $parent = Split-Path $fullPath -Parent
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        return $fullPath
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

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$escapedRepo = $repoRoot.Replace('%', '%%')
$escapedReport = ([IO.Path]::GetFullPath($ValidationReport)).Replace('%', '%%')

@"
@echo off
cd /d "$escapedRepo"
set "PYTHONPATH=$escapedRepo\worker"
set "PYTHONDONTWRITEBYTECODE=1"
set "KALIV_AGENT3_ENABLED=1"
set "KALIV_TOOLS_ENABLED=1"
set "KALIV_AGENT3_PLANNER_MODEL=$PlannerModel"
set "KALIV_AGENT3_VALIDATION_REPORT=$escapedReport"
python -m uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099
"@ | Set-Content -LiteralPath $workerCmd -Encoding ASCII

if ($WorkerOnly) {
    Wait-PortFree -Port 8099 -Label "worker"
    Write-Host "  Starter exact-head worker i et nyt vindue..." -ForegroundColor Cyan
    Start-Process -FilePath "cmd.exe" -ArgumentList "/k", ('"' + $workerCmd + '"') -WorkingDirectory $repoRoot | Out-Null
    Wait-Endpoint -Url "http://127.0.0.1:8099/healthz"
    Write-Host "  Exact-head worker er klar." -ForegroundColor Green
    return
}

$resolvedPairingData = Find-PairingData
$escapedData = $resolvedPairingData.Replace('%', '%%')
$escapedHost = $BackendHost.Replace('%', '%%')
$schedulerValue = if ($EnableSchedulerApi) { "1" } else { "0" }
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
set "KALIV_SCHEDULER_API=$schedulerValue"
"$backendExe"
"@ | Set-Content -LiteralPath $backendCmd -Encoding ASCII

Write-Host "  Starter kandidatens backend og worker i to synlige vinduer..." -ForegroundColor Cyan
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", ('"' + $backendCmd + '"') -WorkingDirectory $runtimeDir | Out-Null
Start-Sleep -Seconds 1
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", ('"' + $workerCmd + '"') -WorkingDirectory $repoRoot | Out-Null

Wait-Endpoint -Url "http://127.0.0.1:8080/healthz"
Wait-Endpoint -Url "http://127.0.0.1:8099/healthz"

Write-Host "  Exact-head validation-stack er klar." -ForegroundColor Green
Write-Host "  Backend-binding: $BackendHost"
Write-Host "  Pairing-data: $resolvedPairingData"
Write-Host "  Luk de to nye konsolvinduer efter testen."
