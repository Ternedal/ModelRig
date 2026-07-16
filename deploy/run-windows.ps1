<#
  ModelRig launcher for Windows (PowerShell 5.1+).

  Starts the RAG worker (uvicorn) and then the backend, bound to 0.0.0.0 so your
  phone can reach it. Ctrl+C stops both.

  Prereqs:
    - Ollama running with your models pulled
    - Python deps installed:  pip install -r ..\worker\requirements.txt
    - Backend built:          go build -o ..\backend\modelrig-server.exe ..\backend\cmd\modelrig-server

  Usage:
    powershell -ExecutionPolicy Bypass -File .\run-windows.ps1
#>
$ErrorActionPreference = "Stop"

function Default($name, $fallback) {
    if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name))) { $fallback }
    else { [Environment]::GetEnvironmentVariable($name) }
}

# Config (child processes inherit these $env: values)
$env:MODELRIG_HOST       = Default "MODELRIG_HOST"       "0.0.0.0"
$env:MODELRIG_PORT       = Default "MODELRIG_PORT"       "8080"
$env:MODELRIG_OLLAMA_URL = Default "MODELRIG_OLLAMA_URL" "http://127.0.0.1:11434"
$env:MODELRIG_WORKER_URL = Default "MODELRIG_WORKER_URL" "http://127.0.0.1:8099"

$root       = Split-Path -Parent $PSScriptRoot
$workerDir  = Join-Path $root "worker"
$backendExe = Join-Path $root "backend\modelrig-server.exe"

if (-not (Test-Path $backendExe)) {
    throw "Backend binary not found at $backendExe. Build it first (see header)."
}

Write-Host "Starting RAG worker on 127.0.0.1:8099 ..." -ForegroundColor Cyan
$workerExe = Get-ChildItem -Path $workerDir -Filter "modelrig-worker*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($workerExe) {
    # Prebuilt exe from the GitHub release (no Python needed on the rig)
    Write-Host "  (prebuilt exe: $($workerExe.Name))" -ForegroundColor DarkGray
    $worker = Start-Process -FilePath $workerExe.FullName `
        -WorkingDirectory $workerDir -PassThru -NoNewWindow
} else {
    # app.entrypoint wraps FastAPI at the ASGI boundary: real request-body
    # limits for chunked uploads + cleanup after streaming voice completes.
    $worker = Start-Process -FilePath "python" `
        -ArgumentList "-m","uvicorn","app.entrypoint:app","--host","127.0.0.1","--port","8099" `
        -WorkingDirectory $workerDir -PassThru -NoNewWindow
}

try {
    Start-Sleep -Seconds 2
    Write-Host "Starting backend on $($env:MODELRIG_HOST):$($env:MODELRIG_PORT) ..." -ForegroundColor Cyan
    Write-Host "Pair a device in another terminal:  .\..\backend\modelrig-server.exe -pair" -ForegroundColor DarkGray
    & $backendExe   # foreground; Ctrl+C ends it
}
finally {
    Write-Host "Stopping worker ..." -ForegroundColor Cyan
    if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue }
}
