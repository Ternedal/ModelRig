# Native Windows run of scripts/Restore-StageBSource2012.ps1 against the actual published
# executables. Only the scheduled task and the two local health endpoints are stubbed; downloads,
# hashing, GitHub provenance, process inspection and file locking are real.
#
#   & .\tests\stage_b_source_restore_windows.ps1 -AssetRoot <dir with v2.0.12\ and v2.0.20\>
#
# AssetRoot\v2.0.20 holds the signed server, supervisor, worker and updater; AssetRoot\v2.0.12
# holds the signed server, supervisor and worker. The workflow downloads and verifies them.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$AssetRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script = Join-Path $PSScriptRoot '..\scripts\Restore-StageBSource2012.ps1'
$names = @('modelrig-server-windows-x64.exe', 'modelrig-supervisor-windows-x64.exe', 'modelrig-worker-windows-x64.exe')
$updaterName = 'modelrig-updater-windows-x64.exe'
$suite = Join-Path $env:RUNNER_TEMP ("Anders's Rig " + [Guid]::NewGuid().ToString('N').Substring(0, 8))
[IO.Directory]::CreateDirectory($suite) | Out-Null
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
$h12 = @{}; $h20 = @{}
foreach ($n in $names) { $h12[$n] = Hash (Join-Path $AssetRoot "v2.0.12\$n"); $h20[$n] = Hash (Join-Path $AssetRoot "v2.0.20\$n") }
$hUpdater = Hash (Join-Path $AssetRoot "v2.0.20\$updaterName")

$global:Calls = New-Object System.Collections.ArrayList
$global:Health = $null
$global:HealthQueue = New-Object System.Collections.Queue
$global:Writers = New-Object System.Collections.ArrayList
$global:CurrentRig = $null
# A started supervisor is a real separate process writing Unix ms to logs\supervisor-heartbeat
# every 500 ms, as the supervisor does each tick; stopping the task kills it.
function global:Stop-Writers {
    foreach ($writer in @($global:Writers)) { try { if (-not $writer.HasExited) { $writer.Kill(); $writer.WaitForExit(10000) | Out-Null } } catch { } }
    $global:Writers.Clear()
}
function global:Stop-ScheduledTask { param($TaskName) [void]$global:Calls.Add("stop:$TaskName"); Stop-Writers }
# Each start of the task makes health report the next queued value ($null = down).
function global:Start-ScheduledTask {
    param($TaskName)
    [void]$global:Calls.Add("start:$TaskName")
    $next = $global:HealthQueue.Dequeue()
    if ($next -ceq 'throw') { throw 'simulated task start failure' }
    $global:Health = $next
    $beat = (Join-Path (Join-Path $global:CurrentRig 'logs') 'supervisor-heartbeat').Replace("'", "''")
    $loop = "while (`$true) { try { [IO.File]::WriteAllText('$beat', [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString()) } catch { }; Start-Sleep -Milliseconds 500 }"
    [void]$global:Writers.Add((Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($loop))) -PassThru -WindowStyle Hidden))
}
function global:Invoke-RestMethod {
    param($Method, $Uri, $Headers, $TimeoutSec, [switch]$UseBasicParsing)
    if ([string]$Uri -like 'http://127.0.0.1:*/healthz') {
        if ($null -eq $global:Health) { throw 'health endpoint down' }
        return [pscustomobject]@{ version = $global:Health }
    }
    Microsoft.PowerShell.Utility\Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec -UseBasicParsing
}

# The updater installs the worker in worker\, everything else in the rig root.
function Live([string]$Root, [string]$Name) {
    if ($Name -eq 'modelrig-worker-windows-x64.exe') { return Join-Path (Join-Path $Root 'worker') $Name }
    return Join-Path $Root $Name
}
function New-Rig([string]$Case) {
    $root = Join-Path $suite $Case
    [IO.Directory]::CreateDirectory((Join-Path $root 'logs')) | Out-Null
    Copy-Item -LiteralPath (Join-Path $AssetRoot "v2.0.20\$updaterName") -Destination (Join-Path $root $updaterName)
    [IO.Directory]::CreateDirectory((Join-Path $root 'worker')) | Out-Null
    foreach ($n in $names) { Copy-Item -LiteralPath (Join-Path $AssetRoot "v2.0.20\$n") -Destination (Live $root $n) }
    [IO.File]::WriteAllText((Join-Path $root 'update-transaction.json'), '{"state":"committed"}')
    $global:CurrentRig = $root
    return $root
}
function Snapshot([string]$Root) {
    return (@(Get-ChildItem -LiteralPath $Root -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName + '=' + (Hash $_.FullName) }) -join '|')
}
function Invoke-Restore([string]$Root, [hashtable]$Extra) {
    Stop-Writers
    $global:Calls.Clear()
    $all = @{ SupervisorIntervalSeconds = 2; HeartbeatSettleSeconds = 30 }
    foreach ($key in $Extra.Keys) { $all[$key] = $Extra[$key] }
    $Extra = $all
    & $script -RigRoot $Root @Extra
}
function Assert-Refused([string]$Root, [string]$Expected, [string]$What) {
    $before = Snapshot $Root
    $message = ''
    try { Invoke-Restore $Root @{ Apply = $true } | Out-Null } catch { $message = [string]$_ }
    Assert ($message -like "*$Expected*") "$What was not refused as expected: '$message'"
    Assert ($global:Calls.Count -eq 0) "$What touched the scheduled task"
    $after = (@(Get-ChildItem -LiteralPath $Root -Recurse -File | Where-Object { $_.FullName -notlike '*\backups\*' } | Sort-Object FullName | ForEach-Object { $_.FullName + '=' + (Hash $_.FullName) }) -join '|')
    Assert ($before -ceq $after) "$What changed rig files"
    Write-Host "ok: $What refused"
}

# 1. Check mode reads only.
$rig = New-Rig 'check'
$global:Health = '2.0.20'
$before = Snapshot $rig
$out = Invoke-Restore $rig @{} *>&1 | Out-String
Assert ($out -match 'Check only') 'Check mode did not say so'
Assert ((Snapshot $rig) -ceq $before) 'Check mode changed files'
Assert (-not (Test-Path -LiteralPath (Join-Path $rig 'backups'))) 'Check mode created a backup folder'
Assert ($global:Calls.Count -eq 0) 'Check mode touched the scheduled task'
Write-Host 'ok: check mode changes nothing'

# 2. Apply with real downloads and provenance, while another process holds the live server open
#    without write sharing until after the backups exist: the swap must hit the sharing
#    violation, say so, and wait for the handle.
$rig = New-Rig 'apply'
$global:Health = '2.0.20'
$global:HealthQueue.Clear(); $global:HealthQueue.Enqueue('2.0.12')
$holder = @"
`$f = [IO.File]::Open('$((Join-Path $rig $names[0]).Replace("'", "''"))', 'Open', 'Read', 'Read')
[IO.File]::WriteAllText('$((Join-Path $suite 'held.txt').Replace("'", "''"))', 'held')
`$deadline = [DateTime]::UtcNow.AddMinutes(10)
while ([DateTime]::UtcNow -lt `$deadline) {
    if (@(Get-ChildItem -LiteralPath '$((Join-Path $rig 'backups').Replace("'", "''"))' -Recurse -Filter '$($names[2])' -ErrorAction SilentlyContinue | Where-Object { `$_.DirectoryName -like '*\v2.0.20' }).Count -gt 0) { break }
    Start-Sleep -Milliseconds 200
}
Start-Sleep -Seconds 3
`$f.Dispose()
"@
$holderProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($holder))) -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
$out = Invoke-Restore $rig @{ Apply = $true } *>&1 | Out-String
Write-Host $out
$holderProcess.WaitForExit(60000) | Out-Null
Assert ($out -match 'Stage B source ready') 'Apply did not report ready'
Assert (Test-Path -LiteralPath (Join-Path $suite 'held.txt')) 'The handle holder never opened the live server'
Assert ($out -match ('waiting for another process to release .*' + [regex]::Escape($names[0]))) 'The swap did not meet the held handle (no sharing-violation wait)'
foreach ($n in $names) { Assert ((Hash (Live $rig $n)) -ceq $h12[$n]) "$n is not the signed v2.0.12 bytes" }
Assert (-not (Test-Path -LiteralPath (Join-Path $rig $names[2]))) 'A worker was written to the rig root'
Assert ((Hash (Join-Path $rig $updaterName)) -ceq $hUpdater) 'The live updater changed'
Assert (-not (Test-Path -LiteralPath (Join-Path $rig 'update-transaction.json'))) 'The journal was not archived'
Assert (-not (Test-Path -LiteralPath (Join-Path $rig 'updater.lock'))) 'The lock was left behind'
$work = @(Get-ChildItem -LiteralPath (Join-Path $rig 'backups') -Directory)
Assert ($work.Count -eq 1) 'Expected exactly one restore folder'
Assert (Test-Path -LiteralPath (Join-Path $work[0].FullName 'update-transaction.json')) 'The archived journal is missing'
foreach ($n in $names) { Assert ((Hash (Join-Path $work[0].FullName "v2.0.20\$n")) -ceq $h20[$n]) "The v2.0.20 backup of $n is wrong" }
Assert (($global:Calls -join ',') -ceq 'stop:KalivSupervisor,start:KalivSupervisor') "Unexpected task calls: $($global:Calls -join ',')"
Write-Host 'ok: apply installs signed v2.0.12, proves the supervisor loops, keeps the v2.0.20 updater and backups, archives the journal'

# 3. A second run is a no-op.
$global:Health = '2.0.12'
$out = Invoke-Restore $rig @{ Apply = $true } *>&1 | Out-String
Assert ($out -match 'Already on signed v2.0.12') 'Second run was not a no-op'
Assert ($global:Calls.Count -eq 0) 'Second run touched the scheduled task'
Write-Host 'ok: second run is a no-op'

# 4. 2.0.12 that never comes up: the rollback restores the v2.0.20 bytes and the original journal
#    files, stops 2.0.12 before swapping back, starts the task once more and sees 2.0.20 again.
$rig = New-Rig 'rollback'
[IO.File]::WriteAllText((Join-Path $rig 'update-transaction.json.tmp'), '{"state":"rolled_back"}')
$journalBefore = Hash (Join-Path $rig 'update-transaction.json')
$tmpBefore = Hash (Join-Path $rig 'update-transaction.json.tmp')
$global:Health = '2.0.20'
$global:HealthQueue.Clear(); $global:HealthQueue.Enqueue($null); $global:HealthQueue.Enqueue('2.0.20')
$message = ''
try { Invoke-Restore $rig @{ Apply = $true; HealthTimeoutSeconds = 6 } | Out-Null } catch { $message = [string]$_ }
Assert ($message -match 'did not both report 2\.0\.12') "Rollback case did not name the health failure: '$message'"
Assert ($message -match 'rolled back to v2\.0\.20 with the original journal' -and $message -match ', supervisor looping\)') "Rollback was not reported complete with a looping supervisor: '$message'"
foreach ($n in $names) { Assert ((Hash (Live $rig $n)) -ceq $h20[$n]) "$n is not the v2.0.20 bytes after the rollback" }
Assert ((Hash (Join-Path $rig $updaterName)) -ceq $hUpdater) 'The live updater changed in the rollback case'
Assert ((Hash (Join-Path $rig 'update-transaction.json')) -ceq $journalBefore) 'The journal was not put back byte for byte'
Assert ((Hash (Join-Path $rig 'update-transaction.json.tmp')) -ceq $tmpBefore) 'The journal .tmp was not put back byte for byte'
Assert (-not (Test-Path -LiteralPath (Join-Path $rig 'updater.lock'))) 'The lock was left behind after the rollback'
Assert (($global:Calls -join ',') -ceq 'stop:KalivSupervisor,start:KalivSupervisor,stop:KalivSupervisor,start:KalivSupervisor') "Unexpected task calls in the rollback: $($global:Calls -join ',')"
Assert ($global:Health -ceq '2.0.20') 'Health is not back on 2.0.20 after the rollback'
Write-Host 'ok: 2.0.12 that never comes up is rolled back to the v2.0.20 bytes and the original journal'

# 5. A rollback whose runtime cannot be verified keeps updater.lock, with the files still put back:
#    once when backend and worker stay down after the rollback, once when the task will not start.
foreach ($case in @(
    @{ What = 'rollback that stays down'; Queue = @($null, $null); Expect = 'are not back to the versions before the restore' },
    @{ What = 'rollback whose task will not start'; Queue = @($null, 'throw'); Expect = 'could not be started' }
)) {
    $rig = New-Rig ('unverified-' + $case.Queue[1])
    [IO.File]::WriteAllText((Join-Path $rig 'update-transaction.json.tmp'), '{"state":"rolled_back"}')
    $journalBefore = Hash (Join-Path $rig 'update-transaction.json')
    $tmpBefore = Hash (Join-Path $rig 'update-transaction.json.tmp')
    $global:Health = '2.0.20'
    $global:HealthQueue.Clear(); foreach ($value in $case.Queue) { $global:HealthQueue.Enqueue($value) }
    $message = ''
    try { Invoke-Restore $rig @{ Apply = $true; HealthTimeoutSeconds = 4 } | Out-Null } catch { $message = [string]$_ }
    Assert ($message -match 'ROLLBACK NOT VERIFIED' -and $message -match [regex]::Escape($case.Expect) -and $message -match 'updater\.lock is KEPT') "$($case.What): unexpected message '$message'"
    Assert (Test-Path -LiteralPath (Join-Path $rig 'updater.lock')) "$($case.What): updater.lock was released"
    foreach ($n in $names) { Assert ((Hash (Live $rig $n)) -ceq $h20[$n]) "$($case.What): $n is not the v2.0.20 bytes" }
    Assert ((Hash (Join-Path $rig 'update-transaction.json')) -ceq $journalBefore -and (Hash (Join-Path $rig 'update-transaction.json.tmp')) -ceq $tmpBefore) "$($case.What): journal not back byte for byte"
    Assert (($global:Calls -join ',') -ceq 'stop:KalivSupervisor,start:KalivSupervisor,stop:KalivSupervisor,start:KalivSupervisor') "$($case.What): unexpected task calls $($global:Calls -join ',')"
    Write-Host "ok: a $($case.What) keeps updater.lock with the v2.0.20 bytes and the journal back"
}

# 6. Refusals before any change.
$global:Health = '2.0.20'
$rig = New-Rig 'lock'; [IO.File]::WriteAllText((Join-Path $rig 'updater.lock'), 'pid 1 started 2026-11-15T00:00:00Z')
Assert-Refused $rig 'updater.lock exists' 'an existing updater.lock'
$rig = New-Rig 'journal'; [IO.File]::WriteAllText((Join-Path $rig 'update-transaction.json'), '{"state":"swapping"}')
Assert-Refused $rig 'Unfinished appliance transaction' 'an unfinished journal'
$rig = New-Rig 'updater'; Copy-Item -LiteralPath (Join-Path $AssetRoot "v2.0.12\$($names[0])") -Destination (Join-Path $rig $updaterName) -Force
Assert-Refused $rig 'not the signed v2.0.20 updater' 'a live updater other than v2.0.20'
$rig = New-Rig 'unknown'; [IO.File]::WriteAllText((Live $rig $names[2]), 'not a release')
Assert-Refused $rig 'neither signed' 'an unknown worker'

Stop-Writers
Remove-Item -LiteralPath $suite -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'All Stage B source-restore checks passed.'
