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
$global:HealthAfterStart = $null
function global:Stop-ScheduledTask { param($TaskName) [void]$global:Calls.Add("stop:$TaskName") }
function global:Start-ScheduledTask { param($TaskName) [void]$global:Calls.Add("start:$TaskName"); $global:Health = $global:HealthAfterStart }
function global:Invoke-RestMethod {
    param($Method, $Uri, $Headers, $TimeoutSec, [switch]$UseBasicParsing)
    if ([string]$Uri -like 'http://127.0.0.1:*/healthz') {
        if ($null -eq $global:Health) { throw 'health endpoint down' }
        return [pscustomobject]@{ version = $global:Health }
    }
    Microsoft.PowerShell.Utility\Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec -UseBasicParsing
}

function New-Rig([string]$Case) {
    $root = Join-Path $suite $Case
    [IO.Directory]::CreateDirectory((Join-Path $root 'logs')) | Out-Null
    Copy-Item -LiteralPath (Join-Path $AssetRoot "v2.0.20\$updaterName") -Destination (Join-Path $root $updaterName)
    foreach ($n in $names) { Copy-Item -LiteralPath (Join-Path $AssetRoot "v2.0.20\$n") -Destination (Join-Path $root $n) }
    [IO.File]::WriteAllText((Join-Path $root 'update-transaction.json'), '{"state":"committed"}')
    return $root
}
function Snapshot([string]$Root) {
    return (@(Get-ChildItem -LiteralPath $Root -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName + '=' + (Hash $_.FullName) }) -join '|')
}
function Invoke-Restore([string]$Root, [hashtable]$Extra) {
    $global:Calls.Clear()
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
#    for writing-exclusion until after the backups exist: the swap must wait for the handle.
$rig = New-Rig 'apply'
$global:Health = '2.0.20'
$global:HealthAfterStart = '2.0.12'
$holder = @"
`$f = [IO.File]::Open('$((Join-Path $rig $names[0]).Replace("'", "''"))', 'Open', 'Read', 'Read')
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
foreach ($n in $names) { Assert ((Hash (Join-Path $rig $n)) -ceq $h12[$n]) "$n is not the signed v2.0.12 bytes" }
Assert ((Hash (Join-Path $rig $updaterName)) -ceq $hUpdater) 'The live updater changed'
Assert (-not (Test-Path -LiteralPath (Join-Path $rig 'update-transaction.json'))) 'The journal was not archived'
Assert (-not (Test-Path -LiteralPath (Join-Path $rig 'updater.lock'))) 'The lock was left behind'
$work = @(Get-ChildItem -LiteralPath (Join-Path $rig 'backups') -Directory)
Assert ($work.Count -eq 1) 'Expected exactly one restore folder'
Assert (Test-Path -LiteralPath (Join-Path $work[0].FullName 'update-transaction.json')) 'The archived journal is missing'
foreach ($n in $names) { Assert ((Hash (Join-Path $work[0].FullName "v2.0.20\$n")) -ceq $h20[$n]) "The v2.0.20 backup of $n is wrong" }
Assert (($global:Calls -join ',') -ceq 'stop:KalivSupervisor,start:KalivSupervisor') "Unexpected task calls: $($global:Calls -join ',')"
Write-Host 'ok: apply installs signed v2.0.12, keeps the v2.0.20 updater and backups, archives the journal'

# 3. A second run is a no-op.
$global:Health = '2.0.12'
$out = Invoke-Restore $rig @{ Apply = $true } *>&1 | Out-String
Assert ($out -match 'Already on signed v2.0.12') 'Second run was not a no-op'
Assert ($global:Calls.Count -eq 0) 'Second run touched the scheduled task'
Write-Host 'ok: second run is a no-op'

# 4. Refusals before any change.
$global:Health = '2.0.20'
$rig = New-Rig 'lock'; [IO.File]::WriteAllText((Join-Path $rig 'updater.lock'), 'pid 1 started 2026-11-15T00:00:00Z')
Assert-Refused $rig 'updater.lock exists' 'an existing updater.lock'
$rig = New-Rig 'journal'; [IO.File]::WriteAllText((Join-Path $rig 'update-transaction.json'), '{"state":"swapping"}')
Assert-Refused $rig 'Unfinished appliance transaction' 'an unfinished journal'
$rig = New-Rig 'updater'; Copy-Item -LiteralPath (Join-Path $AssetRoot "v2.0.12\$($names[0])") -Destination (Join-Path $rig $updaterName) -Force
Assert-Refused $rig 'not the signed v2.0.20 updater' 'a live updater other than v2.0.20'
$rig = New-Rig 'unknown'; [IO.File]::WriteAllText((Join-Path $rig $names[2]), 'not a release')
Assert-Refused $rig 'neither signed' 'an unknown worker'

Remove-Item -LiteralPath $suite -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'All Stage B source-restore checks passed.'
