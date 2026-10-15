#Requires -Version 7.0
<#
.SYNOPSIS
  Physical cancellation/cleanup regression for the isolated Kaliv voice worker.
.DESCRIPTION
  Starts a fresh test-only worker on loopback port 8102; leaves any existing
  worker on 8101 and production ports 8080/8099 completely untouched.
  Runs eight cancellation probes, then stops only the process it started.
  Reads prior failure evidence but does not delete or overwrite its report.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repo = "C:\Rig\validation\ModelRig-voice-candidate"
$python = "C:\Rig\venvs\ModelRig-voice-test\Scripts\python.exe"
$branch = "fix/voice-stream-cancel-cleanup-20261015"
$port = 8102

if (!(Test-Path -LiteralPath $python)) { throw "Test Python not found: $python" }
if (!(Test-Path -LiteralPath (Join-Path $repo ".git"))) {
    throw "Isolated test repository not found: $repo"
}
Set-Location -LiteralPath $repo
$head = (git rev-parse HEAD).Trim()
$remoteHead = (git rev-parse "origin/$branch").Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $remoteHead) {
    throw "Checkout is not the current candidate: $branch"
}
git diff --quiet
if ($LASTEXITCODE -ne 0) { throw "Tracked working-tree changes detected; stopping." }
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw "Staged changes detected; stopping." }
if (!(Test-Path -LiteralPath "validation\voice-fixtures\turn-01.wav")) {
    throw "Existing Danish test fixture is missing."
}

$old = "validation\voice-cancel-smoke.json"
if (Test-Path -LiteralPath $old) {
    Write-Host "Previous cancellation failure details:" -ForegroundColor Cyan
    $previous = Get-Content -LiteralPath $old -Raw | ConvertFrom-Json
    foreach ($item in @($previous.probes | Where-Object { !$_.passed })) {
        Write-Host ("  Probe {0} ({1}), cleanup wait {2} ms" -f $item.probe, $item.trigger, $item.cleanup.wait_ms)
        foreach ($leftover in @($item.cleanup.remaining)) {
            Write-Host ("  Leftover: {0} ; exists now: {1}" -f $leftover, (Test-Path -LiteralPath $leftover))
        }
    }
}

Write-Host "Checking only loopback port $port..." -ForegroundColor Cyan
$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    throw "Port 8102 is already occupied by PID $($listener.OwningProcess). No process will be stopped."
}

& $python -m py_compile "worker\app\main_impl.py" "worker\app\voice_pipeline.py" "scripts\voice_cancel_smoke.py" "tests\worker_voice_stream.py"
if ($LASTEXITCODE -ne 0) { throw "Python compile failed." }

& $python "tests\worker_voice_stream.py"
if ($LASTEXITCODE -ne 0) { throw "Voice cancellation unit test failed." }

$cublas = "C:\Rig\venvs\KalivVoice-v1\Lib\site-packages\nvidia\cublas\bin"
if (Test-Path -LiteralPath $cublas) { $env:PATH = "$cublas;$env:PATH" }

$logs = Join-Path $env:TEMP "kaliv-voice-8102"
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$startArgs = @{
    FilePath = $python
    ArgumentList = @("-m", "uvicorn", "app.entrypoint:app", "--host", "127.0.0.1", "--port", "8102")
    WorkingDirectory = (Join-Path $repo "worker")
    RedirectStandardOutput = (Join-Path $logs "stdout.log")
    RedirectStandardError = (Join-Path $logs "stderr.log")
    PassThru = $true
}
$process = $null
try {
    $process = Start-Process @startArgs
    Write-Host "Started isolated test worker PID $($process.Id)"
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        $process.Refresh()
        if ($process.HasExited) { break }
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:8102/healthz" -TimeoutSec 2
            $listenerNow = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if (!$listenerNow -or [int]$listenerNow.OwningProcess -ne [int]$process.Id) {
                throw "Port 8102 is owned by a process other than the new test worker."
            }
            $ready = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (!$ready) {
        Get-Content -LiteralPath (Join-Path $logs "stderr.log") -Tail 35 -ErrorAction SilentlyContinue
        throw "Isolated test worker did not become ready."
    }

    $report = "validation\voice-cancel-smoke-fixed-8102.json"
    Write-Host "Starting eight isolated cancellation/cleanup probes..." -ForegroundColor Cyan
    & $python "scripts\voice_cancel_smoke.py" --worker-url "http://127.0.0.1:8102" --probes 8 --cleanup-timeout 20 --report $report
    $testExit = $LASTEXITCODE
    if (!(Test-Path -LiteralPath $report)) { throw "No cancellation report was generated." }
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    $result.summary | Format-List
    $result.probes | Select-Object probe, trigger, aborted, worker_healthy, passed |
        Format-Table -AutoSize
    Write-Host ("Whole-campaign cleanup: {0}" -f $result.campaign_cleanup.clean)
    foreach ($leftover in @($result.campaign_cleanup.remaining)) {
        Write-Host ("Leftover: {0} ; exists now: {1}" -f $leftover, (Test-Path -LiteralPath $leftover))
    }
    Write-Host "Report: $report"
    Write-Host "Ports 8080, 8099 and 8101 were not modified." -ForegroundColor Green
    if ($testExit -ne 0) { throw "Cancellation test failed; see the report above." }
}
finally {
    if ($null -ne $process) {
        $process.Refresh()
        if (!$process.HasExited) {
            Write-Host "Stopping only our own temporary port-8102 worker PID $($process.Id)"
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        }
    }
}
