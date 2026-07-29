[CmdletBinding()]
param(
    [string]$PlannerModel
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$phoneScript = Join-Path $PSScriptRoot "stage-a-phone-test.ps1"
$stackScript = Join-Path $PSScriptRoot "start-stage-a-validation-stack.ps1"
$phoneStatePath = Join-Path $repoRoot "validation\stage-a-runtime\phone-test-state.json"
$manualPath = Join-Path $repoRoot "validation\voice-manual-observations.json"
$reportPath = Join-Path $repoRoot "validation\voice-baseline-latest.json"
$fixtureReportPath = Join-Path $repoRoot "validation\voice-baseline-fixture-check.json"
$agent3ReportPath = Join-Path $repoRoot "validation\agent3-rig-validation-latest.json"

function Resolve-PlannerModel {
    if (-not [string]::IsNullOrWhiteSpace($PlannerModel)) { return $PlannerModel.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($env:KALIV_AGENT3_PLANNER_MODEL)) {
        return $env:KALIV_AGENT3_PLANNER_MODEL.Trim()
    }
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        throw "Ollama blev ikke fundet på PATH."
    }
    try {
        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
        $names = @($tags.models | ForEach-Object { [string]$_.name })
        foreach ($preferred in @("qwen3:14b", "qwen3:8b")) {
            if ($names -contains $preferred) { return $preferred }
        }
        $candidate = $names | Where-Object {
            $_ -and $_ -notmatch "embed" -and $_ -notmatch "^nomic-"
        } | Select-Object -First 1
        if ($candidate) { return [string]$candidate }
    }
    catch { }
    throw "Ollama svarer ikke, eller der findes ingen planner-model."
}

function Get-ListenerPid {
    param([int]$Port)
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return [int]$listener.OwningProcess
}

function Get-ProcessInfo {
    param([int]$ProcessId)
    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Assert-ExpectedWorker {
    param([int]$ProcessId)
    $process = Get-ProcessInfo -ProcessId $ProcessId
    if ($null -eq $process) { throw "Worker-processen $ProcessId findes ikke." }
    $commandLine = [string]$process.CommandLine
    if ([string]$process.Name -ine "python.exe" -or
        $commandLine -notmatch "uvicorn\s+app\.entrypoint:app" -or
        $commandLine -notmatch "--port\s+8099") {
        throw "Port 8099 ejes ikke af den forventede Stage A-worker; ingen proces blev stoppet."
    }
}

function Wait-PortFree {
    param([int]$Port, [int]$Seconds = 30)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ($null -ne (Get-ListenerPid -Port $Port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if ($null -ne (Get-ListenerPid -Port $Port)) {
        throw "Port $Port blev ikke frigivet inden for $Seconds sekunder."
    }
}

function Update-WorkerPid {
    param([int]$ProcessId)
    $state = Get-Content -LiteralPath $phoneStatePath -Raw | ConvertFrom-Json
    $state.worker_pid = $ProcessId
    $state | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $phoneStatePath -Encoding UTF8
}

if ($env:OS -ne "Windows_NT") { throw "Voice-testen må kun køres på Windows-riggen." }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python blev ikke fundet på PATH." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git blev ikke fundet på PATH." }
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "Ollama blev ikke fundet på PATH." }

Push-Location $repoRoot
try {
    $dirty = (& git status --porcelain) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Git-status kunne ikke læses." }
    if (-not [string]::IsNullOrWhiteSpace($dirty)) {
        throw "Working tree er ikke ren. Voice-beviset må kun køres på en eksakt kandidat."
    }

    $model = Resolve-PlannerModel
    Write-Host ""
    Write-Host "===============================================================" -ForegroundColor Cyan
    Write-Host "  KALIV STAGE A - GUIDET VOICE-TEST" -ForegroundColor Cyan
    Write-Host "===============================================================" -ForegroundColor Cyan
    Write-Host "  Model: $model"
    Write-Host "  Ingen JSON skal redigeres manuelt."
    Write-Host ""

    & $phoneScript -PlannerModel $model

    & python (Join-Path $PSScriptRoot "stage_a_voice_observations.py") `
        --phone-state $phoneStatePath `
        --output $manualPath
    if ($LASTEXITCODE -ne 0) {
        throw "Den manuelle Pixel-matrix blev gemt, men bestod ikke. Voice-baseline køres derfor ikke."
    }

    Write-Host ""
    Write-Host "  Kontrollerer de 20 WAV-filer..." -ForegroundColor Cyan
    & python (Join-Path $PSScriptRoot "voice_baseline.py") `
        --validate-only `
        --report $fixtureReportPath
    if ($LASTEXITCODE -ne 0) {
        throw "Voice-fixtures bestod ikke formatkontrollen."
    }

    $phoneState = Get-Content -LiteralPath $phoneStatePath -Raw | ConvertFrom-Json
    $recordedWorkerPid = [int]$phoneState.worker_pid
    $listenerPid = Get-ListenerPid -Port 8099
    if ($null -eq $listenerPid -or $listenerPid -ne $recordedWorkerPid) {
        throw "Den registrerede Stage A-worker matcher ikke port 8099."
    }
    Assert-ExpectedWorker -ProcessId $recordedWorkerPid

    Write-Host ""
    Write-Host "  Gør voice-pipelinen fysisk kold..." -ForegroundColor Cyan
    & ollama stop $model
    if ($LASTEXITCODE -ne 0) {
        throw "Ollama kunne ikke stoppe $model; cold-start kan derfor ikke erklæres."
    }
    Stop-Process -Id $recordedWorkerPid -Force
    Wait-PortFree -Port 8099

    & $stackScript `
        -PlannerModel $model `
        -ValidationReport $agent3ReportPath `
        -WorkerOnly

    $coldWorkerPid = Get-ListenerPid -Port 8099
    if ($null -eq $coldWorkerPid) { throw "Den friske worker startede ikke på port 8099." }
    Assert-ExpectedWorker -ProcessId $coldWorkerPid
    Update-WorkerPid -ProcessId $coldWorkerPid

    Write-Host ""
    Write-Host "  Kører autoritativ baseline: 1 cold probe, 40 warm runs og 4 cancellation-prober..." -ForegroundColor Cyan
    & python (Join-Path $PSScriptRoot "voice_baseline.py") `
        --worker-url "http://127.0.0.1:8099" `
        --model $model `
        --repetitions 2 `
        --cold-start-confirmed `
        --cancellation-probes 4 `
        --manual-observations $manualPath `
        --require-manual `
        --report $reportPath
    if ($LASTEXITCODE -ne 0) {
        throw "Voice-baselinen bestod ikke. Den konkrete rapport er bevaret i validation\voice-baseline-latest.json."
    }

    Write-Host ""
    Write-Host "===============================================================" -ForegroundColor Green
    Write-Host "  VOICE-BEVISET BESTOD" -ForegroundColor Green
    Write-Host "===============================================================" -ForegroundColor Green
    Write-Host "  Rapport: validation\voice-baseline-latest.json"
    Write-Host "  Ingen JSON blev redigeret manuelt."
    Write-Host "  production_activation=false"
}
finally {
    try {
        & $phoneScript -Stop
    }
    catch {
        Write-Warning "Automatisk cleanup fejlede: $($_.Exception.Message)"
    }
    Pop-Location
}
