#Requires -Version 7.0
<#
.SYNOPSIS
  Isolated ModelRig/Kaliv voice-device laboratory (never starts the release appliance).
.DESCRIPTION
  Combines the candidate voice worker and a separately paired Go backend on
  worker port 8121 / backend port 8181. The opt-in -ExposeLan binds the BACKEND
  to 0.0.0.0 so a physical Android device can reach it; the worker stays on
  loopback. Dedicated console windows are left open for inspection and manual
  shutdown. The existing release/test processes and their data are NEVER killed
  or reconfigured. All test pairing data lives under validation/voice-device-lab.
.EXAMPLE
  pwsh -File .\scripts\voice-device-lab.ps1 -Role Start -ExposeLan
  pwsh -File .\scripts\voice-device-lab.ps1 -Role Pair
  pwsh -File .\scripts\voice-device-lab.ps1 -Role BuildApk
#>
[CmdletBinding()]
param(
    [ValidateSet("Start","Worker","Backend","Pair","BuildApk","Status")]
    [string]$Role = "Status",
    [switch]$ExposeLan
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$branch = "validation/kaliv-voice-device-integration-20261015"
$python = "C:\Rig\venvs\ModelRig-voice-test\Scripts\python.exe"
$workerPort = 8121
$backendPort = 8181
$lab = Join-Path $repo "validation\voice-device-lab"
$backendExe = Join-Path $lab "modelrig-server-voice-lab.exe"
$store = Join-Path $lab "device-pairings.json"
$gradle = Join-Path $repo "android\gradlew.bat"

function Assert-ExactCheckout {
    Push-Location $repo
    try {
        $actual = (& git rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Not a git checkout." }
        $expected = (& git rev-parse "origin/$branch").Trim()
        if ($LASTEXITCODE -ne 0 -or $expected -ne $actual) {
            throw "This lab must run from exact origin/$branch. Actual HEAD=$actual, remote=$expected."
        }
        & git diff --quiet
        if ($LASTEXITCODE -ne 0) { throw "Tracked file changes present; stop before testing." }
        & git diff --cached --quiet
        if ($LASTEXITCODE -ne 0) { throw "Staged changes present; stop before testing." }
        Write-Host "Candidate verified: $($actual.Substring(0, 12))" -ForegroundColor Green
    } finally { Pop-Location }
}

function Assert-PortFree([int]$port) {
    $owner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($owner) {
        throw "Port $port is already in use by PID $($owner.OwningProcess); no process will be stopped."
    }
}

function Set-BackendEnv {
    # Explicitly override all endpoint and state settings; never reuse the
    # production pairing file or a pre-existing MODELRIG_CONFIG path.
    $env:MODELRIG_CONFIG = ""
    $env:MODELRIG_HOST = $(if ($ExposeLan) { "0.0.0.0" } else { "127.0.0.1" })
    $env:MODELRIG_PORT = [string]$backendPort
    $env:MODELRIG_WORKER_URL = "http://127.0.0.1:$workerPort"
    $env:MODELRIG_DATA = $store
    $env:MODELRIG_OLLAMA_URL = "http://127.0.0.1:11434"
    # With no admin key, /api/v1/pair/start is loopback-only. On-rig -pair
    # therefore works but LAN devices cannot mint their own pairing codes.
    $env:MODELRIG_ADMIN_KEY = ""
    $env:KALIV_AGENT4_OPERATOR_API = "0"
    $env:KALIV_SCHEDULER = "0"
}
function Set-WorkerEnv {
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:KALIV_AGENT4_OPERATOR_API = "0"
    $env:KALIV_SCHEDULER = "0"
    $env:KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED = "0"
    $env:KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED = "0"
    $env:KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED = "0"
    $cublas = "C:\Rig\venvs\KalivVoice-v1\Lib\site-packages\nvidia\cublas\bin"
    if (Test-Path -LiteralPath $cublas) {
        $env:PATH = "$cublas;$env:PATH"
    }
}
function Test-Endpoint([string]$url) {
    try {
        $r = Invoke-RestMethod -Uri $url -TimeoutSec 2
        return ($r.status -eq "ok")
    } catch { return $false }
}

if (!(Test-Path -LiteralPath $python)) {
    if ($Role -in @("Start", "Worker")) { throw "Voice test Python missing: $python" }
}
Assert-ExactCheckout
New-Item -ItemType Directory -Path $lab -Force | Out-Null

switch ($Role) {
    "Worker" {
        Set-WorkerEnv
        Assert-PortFree $workerPort
        Write-Host "VOICE LAB WORKER on 127.0.0.1:$workerPort; close this console to stop." -ForegroundColor Cyan
        Set-Location (Join-Path $repo "worker")
        & $python -m uvicorn app.entrypoint:app --host 127.0.0.1 --port $workerPort
        if ($LASTEXITCODE -ne 0) { throw "Voice lab worker exited with code $LASTEXITCODE" }
    }
    "Backend" {
        Set-BackendEnv
        Assert-PortFree $backendPort
        if (!(Test-Path -LiteralPath $backendExe)) {
            throw "Isolated backend binary is missing. Run -Role Start first."
        }
        Write-Host "VOICE LAB BACKEND on $($env:MODELRIG_HOST):$backendPort; close this console to stop." -ForegroundColor Cyan
        Write-Host "Pairing store: $store (never shared with release)" -ForegroundColor DarkGray
        & $backendExe
        if ($LASTEXITCODE -ne 0) { throw "Voice lab backend exited with code $LASTEXITCODE" }
    }
    "Pair" {
        Set-BackendEnv
        # The CLI must connect via loopback when the backend is bound to
        # 0.0.0.0 (or 127.0.0.1). No store is opened by -pair if server is up.
        $env:MODELRIG_HOST = "0.0.0.0"
        if (!(Test-Endpoint "http://127.0.0.1:$backendPort/healthz")) {
            throw "Isolated backend not running on $backendPort; no offline pairing permitted."
        }
        if (!(Test-Path -LiteralPath $backendExe)) {
            throw "Isolated backend binary missing."
        }
        & $backendExe -pair
        if ($LASTEXITCODE -ne 0) { throw "Lab pairing code could not be minted." }
        Write-Host "Use this code ONLY in the separate .a425f test app." -ForegroundColor Green
    }
    "BuildApk" {
        if (!(Test-Path -LiteralPath $gradle)) { throw "Android Gradle wrapper not found: $gradle" }
        Push-Location (Join-Path $repo "android")
        try {
            & $gradle ":app:assembleA425f"
            if ($LASTEXITCODE -ne 0) { throw "Android lab build failed ($LASTEXITCODE)." }
        } finally { Pop-Location }
        $apk = Join-Path $repo "android\app\build\outputs\apk\a425f\app-a425f.apk"
        if (!(Test-Path -LiteralPath $apk)) { throw "Gradle succeeded but APK was not found: $apk" }
        Write-Host "Test-only APK: $apk" -ForegroundColor Green
        Write-Host "Android package: dk.ternedal.modelrig.a425f (does not replace Kaliv)." -ForegroundColor Green
    }
    "Status" {
        Write-Host "Voice lab candidate HEAD: $(git -C $repo rev-parse --short HEAD)"
        Write-Host "Worker 127.0.0.1:$workerPort healthy: $(Test-Endpoint "http://127.0.0.1:$workerPort/healthz")"
        Write-Host "Backend 127.0.0.1:$backendPort healthy: $(Test-Endpoint "http://127.0.0.1:$backendPort/healthz")"
        Write-Host "Separate pairing store: $store (exists: $(Test-Path -LiteralPath $store))"
        Write-Host "No production ports or processes inspected or modified."
    }
    "Start" {
        Assert-PortFree $workerPort
        Assert-PortFree $backendPort
        if (!(Get-Command go -ErrorAction SilentlyContinue)) { throw "Go is not in PATH." }
        if (!(Get-Command pwsh -ErrorAction SilentlyContinue)) { throw "PowerShell 7 missing." }
        Push-Location (Join-Path $repo "backend")
        try {
            & go test ./internal/proxy
            if ($LASTEXITCODE -ne 0) { throw "Go streaming-proxy cancellation regression failed." }
            & go build -o $backendExe ./cmd/modelrig-server
            if ($LASTEXITCODE -ne 0) { throw "Go isolated backend build failed." }
        } finally { Pop-Location }

        # Windows Python venv launchers may create subprocesses; avoid any
        # destructive automatic PID matching. Only these TWO new consoles are
        # created; close them manually when finished, preserving old workers.
        $shell = (Get-Command pwsh).Source
        $self = '"' + $PSCommandPath + '"'
        $workerArgs = @("-NoExit", "-NoProfile", "-File", $self, "-Role", "Worker")
        $backendArgs = @("-NoExit", "-NoProfile", "-File", $self, "-Role", "Backend")
        if ($ExposeLan) { $backendArgs += "-ExposeLan" }

        Start-Process -FilePath $shell -ArgumentList $workerArgs | Out-Null
        $workerReady = $false
        for ($i = 0; $i -lt 80; $i++) {
            if (Test-Endpoint "http://127.0.0.1:$workerPort/healthz") {
                $workerReady = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }
        if (!$workerReady) {
            throw "Voice worker did not start. Inspect the dedicated worker console; no existing process was stopped."
        }
        Start-Process -FilePath $shell -ArgumentList $backendArgs | Out-Null
        $backendReady = $false
        for ($i = 0; $i -lt 40; $i++) {
            if (Test-Endpoint "http://127.0.0.1:$backendPort/healthz") {
                $backendReady = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }
        if (!$backendReady) {
            throw "Voice backend did not start. Inspect the dedicated backend console."
        }

        Write-Host "ISOLATED VOICE DEVICE LAB READY" -ForegroundColor Green
        Write-Host "  Worker: 127.0.0.1:$workerPort (loopback only)"
        Write-Host "  Backend: $($env:MODELRIG_HOST):$backendPort"
        if ($ExposeLan) {
            Write-Host "  Android: http://<your-rig-LAN-IP>:$backendPort" -ForegroundColor Cyan
            Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
                Select-Object InterfaceAlias, IPAddress |
                Format-Table -AutoSize
        } else {
            Write-Host "  Backend is LOCAL ONLY. Re-run -Role Start -ExposeLan for Android access."
        }
        Write-Host "  Pair: pwsh -File .\scripts\voice-device-lab.ps1 -Role Pair"
        Write-Host "  APK:  pwsh -File .\scripts\voice-device-lab.ps1 -Role BuildApk"
        Write-Host "  The existing Kaliv installation and production ports are unchanged."
        Write-Host "  Close the two dedicated lab console windows to stop the lab."
    }
}
