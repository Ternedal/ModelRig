#Requires -Version 7.0
<#
.SYNOPSIS
  Physical cancellation/cleanup regression for the isolated Kaliv voice worker.
.DESCRIPTION
  Picks an unused test-only loopback port 8102-8110. Does not stop existing
  workers on 8101/8102 or production ports 8080/8099.
  Runs eight cancellation probes, then stops only the process it started.
  Reads prior failure evidence but does not delete or overwrite its report.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repo = "C:\Rig\validation\ModelRig-voice-candidate"
$python = "C:\Rig\venvs\ModelRig-voice-test\Scripts\python.exe"
$branch = "fix/voice-stream-cancel-cleanup-20261015"
$port = $null
$ownedListenerPid = $null
$runId = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss-fff")

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

# Never stop an existing listener (especially not the earlier 8102 worker).
# Use the next free *isolated* loopback port for this attempt.
foreach ($candidate in 8102..8110) {
    $occupied = Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue
    if (!$occupied) {
        $port = [int]$candidate
        break
    }
    Write-Host "Port $candidate already occupied; leaving it alone." -ForegroundColor Yellow
}
if ($null -eq $port) { throw "No free isolated test port in 8102-8110." }
Write-Host "Selected isolated loopback port $port" -ForegroundColor Cyan

& $python -m py_compile "worker\app\main_impl.py" "worker\app\voice_pipeline.py" "scripts\voice_cancel_smoke.py" "tests\worker_voice_stream.py"
if ($LASTEXITCODE -ne 0) { throw "Python compile failed." }

& $python "tests\worker_voice_stream.py"
if ($LASTEXITCODE -ne 0) { throw "Voice cancellation unit test failed." }

$cublas = "C:\Rig\venvs\KalivVoice-v1\Lib\site-packages\nvidia\cublas\bin"
if (Test-Path -LiteralPath $cublas) { $env:PATH = "$cublas;$env:PATH" }

function Test-ChildOfProcess {
    param([int]$ProcessIdToCheck, [int]$RootId)
    $current = $ProcessIdToCheck
    for ($depth = 0; $depth -lt 6; $depth++) {
        if ($current -eq $RootId) { return $true }
        $item = Get-CimInstance Win32_Process -Filter "ProcessId = $current" -ErrorAction SilentlyContinue
        if (!$item) { return $false }
        $parent = [int]$item.ParentProcessId
        if ($parent -eq $RootId) { return $true }
        if ($parent -le 0 -or $parent -eq $current) { return $false }
        $current = $parent
    }
    return $false
}

function Test-OwnedListener {
    param([int]$OwnerPid, [int]$RootPid, [int]$PortNumber)
    $item = Get-CimInstance Win32_Process -Filter "ProcessId = $OwnerPid" -ErrorAction SilentlyContinue
    if (!$item) { return $false }
    $command = [string]$item.CommandLine
    $expectedPort = "--port"
    $isExpectedWorker = (
        $command.Contains("uvicorn") -and
        $command.Contains("app.entrypoint:app") -and
        $command.Contains($expectedPort) -and
        $command.Contains([string]$PortNumber) -and
        $command.Contains("127.0.0.1")
    )
    return ($isExpectedWorker -and (Test-ChildOfProcess -ProcessIdToCheck $OwnerPid -RootId $RootPid))
}

$logs = Join-Path $env:TEMP "kaliv-voice-$port-$runId"
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$startArgs = @{
    FilePath = $python
    ArgumentList = @("-m", "uvicorn", "app.entrypoint:app", "--host", "127.0.0.1", "--port", [string]$port)
    WorkingDirectory = (Join-Path $repo "worker")
    RedirectStandardOutput = (Join-Path $logs "stdout.log")
    RedirectStandardError = (Join-Path $logs "stderr.log")
    PassThru = $true
}
$process = $null
try {
    $process = Start-Process @startArgs
    Write-Host "Started test launcher PID $($process.Id)"
    $ready = $false
    $startupProblem = $null

    for ($i = 0; $i -lt 60; $i++) {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2
            $listenerNow = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if (!$listenerNow) {
                throw "Health endpoint responded, but no listener is visible."
            }
            $serverPid = [int]$listenerNow.OwningProcess
            if (!(Test-OwnedListener -OwnerPid $serverPid -RootPid $process.Id -PortNumber $port)) {
                $startupProblem = "Listener PID $serverPid is not a verified child of launcher PID $($process.Id)."
                break
            }
            $ownedListenerPid = $serverPid
            $ready = $true
            Write-Host "Verified worker listener PID $serverPid (launcher PID $($process.Id))." -ForegroundColor Green
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (!$ready) {
        Get-Content -LiteralPath (Join-Path $logs "stderr.log") -Tail 25 -ErrorAction SilentlyContinue
        if ($startupProblem) { throw $startupProblem }
        throw "Isolated test worker did not become ready. Logs: $logs"
    }

    $report = "validation\voice-cancel-smoke-fixed-$port-$runId.json"
    Write-Host "Starting eight isolated cancellation/cleanup probes..." -ForegroundColor Cyan
    & $python "scripts\voice_cancel_smoke.py" --worker-url "http://127.0.0.1:$port" --probes 8 --cleanup-timeout 20 --report $report
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
    Write-Host "Original failure evidence and workers on other ports were not touched." -ForegroundColor Green
    if ($testExit -ne 0) { throw "Cancellation test failed; see report above." }
}
finally {
    # Windows venv launchers can spawn a separate real Uvicorn Python process.
    # Kill only the listener PID that passed the exact descendant+CLI checks,
    # then the launcher that this script started. Never touch an existing port.
    if ($null -ne $ownedListenerPid -and $null -ne $process) {
        $now = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($now -and [int]$now.OwningProcess -eq $ownedListenerPid -and
            (Test-OwnedListener -OwnerPid $ownedListenerPid -RootPid $process.Id -PortNumber $port)) {
            Write-Host "Stopping verified temporary listener PID $ownedListenerPid"
            Stop-Process -Id $ownedListenerPid -ErrorAction SilentlyContinue
        }
    }
    if ($null -ne $process) {
        $process.Refresh()
        if (!$process.HasExited) {
            Write-Host "Stopping test launcher PID $($process.Id)"
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        }
    }
}
