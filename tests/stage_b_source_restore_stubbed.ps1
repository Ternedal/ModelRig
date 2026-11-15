# Behaviour test for scripts/Restore-StageBSource2012.ps1 with the Windows-only cmdlets stubbed.
# Linux pwsh only (the fake updater is a shell script). The real-asset run is
# tests/stage_b_source_restore_windows.ps1.
#   pwsh -NoProfile -File tests/stage_b_source_restore_stubbed.ps1
# It rewrites a copy of the script so the pinned hashes point at fake contents, and records the
# provenance call instead of going to GitHub; the real provenance function is checked against two
# saved GitHub attestation replies in tests/fixtures/stage_b_source_restore/.
$ErrorActionPreference = 'Stop'
$here = Join-Path ([IO.Path]::GetTempPath()) ('stage-b-restore-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $here | Out-Null
$real = Join-Path (Join-Path $PSScriptRoot '..') (Join-Path 'scripts' 'Restore-StageBSource2012.ps1')
$fixtures = Join-Path (Join-Path $PSScriptRoot 'fixtures') 'stage_b_source_restore'
$fails = 0
function Check([bool]$ok, [string]$what) {
    if ($ok) { Write-Host "  ok   $what" } else { Write-Host "  FAIL $what"; $script:fails++ }
}
function Sha([string]$text) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    return ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
}
$names = 'modelrig-server-windows-x64.exe', 'modelrig-supervisor-windows-x64.exe', 'modelrig-worker-windows-x64.exe'
$realHash = @{
    'modelrig-server-windows-x64.exe'     = @('0af13cb40220f757cd7782d00a82de32e92f7faaf9510720f93ef04bf1415269', '23933927652492da1b70bbec424df60f4315ec43b5bf9a0bc085e4da1b088cc7')
    'modelrig-supervisor-windows-x64.exe' = @('f4007a07c9259902bf5dfdd711e1a772c94d47244597da62e91ac4f762cc2a70', '50274ab5e4b1e366b0a3b4cf56c1b11eaad096bd2ed68eaefc31e36958b544c1')
    'modelrig-worker-windows-x64.exe'     = @('05148f125801b471ea504918cffbd76c6609342ccce39a3eb50d470c208a65b2', '7a255a2dcdfb5b73ba3eaede75b6a182e5e360a1b59cd731f5250b25d853a9ab')
}
$updaterText = "#!/bin/sh`necho 2.0.20`n"

# A copy of the script whose pinned hashes point at fake contents, and whose provenance call is
# recorded instead of going to GitHub (the real function is tested separately below).
$src = Get-Content -LiteralPath $real -Raw
foreach ($n in $names) {
    $src = $src.Replace($realHash[$n][0], (Sha "$n 2.0.12")).Replace($realHash[$n][1], (Sha "$n 2.0.20"))
}
$src = $src.Replace('26e131ccfaa9e551311c5e897d1e8c3b964e7bc0b519e2b2f015458c3b0237ed', (Sha $updaterText))
$src = $src.Replace('function Assert-ReleaseProvenance([string]$Digest) {', "function Assert-ReleaseProvenance([string]`$Digest) { `$global:Prov += `$Digest }`nfunction Assert-ReleaseProvenance-Real([string]`$Digest) {")
$copy = Join-Path $here 'under-test.ps1'
Set-Content -LiteralPath $copy -Value $src -Encoding ascii

function global:Get-CimInstance { param($ClassName, $Filter) @($global:Procs) }
function global:Stop-ScheduledTask { param($TaskName) $global:Calls += "stop-task" }
function global:Start-ScheduledTask { param($TaskName) $global:Calls += "start-task"; if ($global:HealthAfterStart) { $global:Health = $global:HealthAfterStart } }
function global:Invoke-RestMethod {
    param($Method, $Uri, $Headers, $TimeoutSec, [switch]$UseBasicParsing)
    if ($Uri -like '*healthz') { if ($null -eq $global:Health) { throw 'down' }; return [pscustomobject]@{ version = $global:Health } }
    if ($global:AttReply) { return $global:AttReply }
    throw "unexpected $Uri"
}
function global:Invoke-WebRequest {
    param([switch]$UseBasicParsing, $Uri, $OutFile, $TimeoutSec)
    $name = Split-Path -Leaf $Uri
    $global:Downloads += $name
    $text = "$name 2.0.12"
    if ($global:BadDownload -eq $name) { $text = 'tampered' }
    [IO.File]::WriteAllText($OutFile, $text)
}
function global:Copy-Item {
    param([string]$LiteralPath, [string]$Destination, [switch]$Force)
    if ($global:FailCopyTo -and $Destination -like "*$($global:FailCopyTo)" -and $LiteralPath -like '*v2.0.12*') { throw 'simulated copy failure' }
    Microsoft.PowerShell.Management\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
}

function New-Rig([hashtable]$liveVersion) {
    $root = Join-Path $here ('rig-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
    New-Item -ItemType Directory -Path (Join-Path $root 'logs') -Force | Out-Null
    $u = Join-Path $root 'modelrig-updater-windows-x64.exe'
    [IO.File]::WriteAllText($u, $updaterText); chmod +x $u
    foreach ($n in $names) { [IO.File]::WriteAllText((Join-Path $root $n), "$n $($liveVersion[$n])") }
    return $root
}
function Reset([string]$health) {
    $global:Procs = @(); $global:Calls = @(); $global:Downloads = @(); $global:Prov = @()
    $global:Health = $health; $global:HealthAfterStart = '2.0.12'; $global:BadDownload = $null; $global:FailCopyTo = $null; $global:AttReply = $null
}
function Run([string]$root, [hashtable]$extra) {
    $out = & $copy -RigRoot $root @extra *>&1 | Out-String
    return $out
}
function RunErr([string]$root, [hashtable]$extra) {
    try { $null = & $copy -RigRoot $root @extra *>&1; return '' } catch { return [string]$_ }
}
function LiveIs([string]$root, [string]$v) {
    foreach ($n in $names) { if ([IO.File]::ReadAllText((Join-Path $root $n)) -cne "$n $v") { return $false } }
    return $true
}
$all2020 = @{}; $all2012 = @{}; foreach ($n in $names) { $all2020[$n] = '2.0.20'; $all2012[$n] = '2.0.12' }

Write-Host 'check mode changes nothing'
Reset '2.0.20'; $r = New-Rig $all2020
[IO.File]::WriteAllText((Join-Path $r 'update-transaction.json'), '{"state":"committed"}')
$o = Run $r @{}
Check ($o -match 'Check only') 'says check only'
Check (LiveIs $r '2.0.20') 'live set untouched'
Check (Test-Path (Join-Path $r 'update-transaction.json')) 'journal untouched'
Check ($global:Downloads.Count -eq 0 -and $global:Calls.Count -eq 0) 'no download, no task call'
Check (-not (Test-Path (Join-Path $r 'backups'))) 'no backup folder'

Write-Host 'apply restores, archives the journal and leaves the updater'
Reset '2.0.20'; $r = New-Rig $all2020
[IO.File]::WriteAllText((Join-Path $r 'update-transaction.json'), '{"state":"committed"}')
[IO.File]::WriteAllText((Join-Path $r 'update-transaction.json.tmp'), '{"state":"committed"}')
$o = Run $r @{ Apply = $true }
Check ($o -match 'Stage B source ready') 'reports ready'
Check (LiveIs $r '2.0.12') 'live set is 2.0.12'
Check (-not (Test-Path (Join-Path $r 'update-transaction.json')) -and -not (Test-Path (Join-Path $r 'update-transaction.json.tmp'))) 'journal and tmp gone from root'
$bk = @(Get-ChildItem (Join-Path $r 'backups') -Directory)[0].FullName
Check ((Test-Path (Join-Path $bk 'update-transaction.json')) -and (Test-Path (Join-Path $bk 'update-transaction.json.tmp'))) 'journal and tmp archived'
Check ([IO.File]::ReadAllText((Join-Path (Join-Path $bk 'v2.0.20') 'modelrig-worker-windows-x64.exe')) -ceq 'modelrig-worker-windows-x64.exe 2.0.20') '2.0.20 backup kept'
Check ([IO.File]::ReadAllText((Join-Path $r 'modelrig-updater-windows-x64.exe')) -ceq $updaterText) 'updater untouched'
Check (-not (Test-Path (Join-Path $r 'updater.lock'))) 'lock released'
Check ($global:Prov.Count -eq 3) 'provenance checked for all three'
Check (($global:Calls -join ',') -ceq 'stop-task,start-task') 'stopped then started once'

Write-Host 'a second run is a no-op'
$global:Calls = @(); $global:Downloads = @(); $global:Health = '2.0.12'
$o = Run $r @{ Apply = $true }
Check ($o -match 'Already on signed v2.0.12') 'says already ready'
Check ($global:Calls.Count -eq 0 -and $global:Downloads.Count -eq 0) 'no task call, no download'

Write-Host 'refusals before any change'
foreach ($case in @(
    @{ What = 'existing lock'; Prep = { param($r) [IO.File]::WriteAllText((Join-Path $r 'updater.lock'), 'pid 1 started x') }; Expect = 'updater.lock exists' },
    @{ What = 'pending updater'; Prep = { param($r) [IO.File]::WriteAllText((Join-Path $r 'modelrig-updater-windows-x64.exe.pending'), 'x') }; Expect = 'pending exists' },
    @{ What = 'unfinished journal'; Prep = { param($r) [IO.File]::WriteAllText((Join-Path $r 'update-transaction.json'), '{"state":"swapping"}') }; Expect = 'Unfinished appliance transaction' },
    @{ What = 'unreadable journal'; Prep = { param($r) [IO.File]::WriteAllText((Join-Path $r 'update-transaction.json.tmp'), 'not json') }; Expect = 'Unfinished appliance transaction' },
    @{ What = 'unknown binary'; Prep = { param($r) [IO.File]::WriteAllText((Join-Path $r 'modelrig-worker-windows-x64.exe'), 'other') }; Expect = 'neither signed' },
    @{ What = 'wrong updater'; Prep = { param($r) [IO.File]::WriteAllText((Join-Path $r 'modelrig-updater-windows-x64.exe'), "#!/bin/sh`necho 2.0.18`n") }; Expect = 'not the signed v2.0.20 updater' },
    @{ What = 'running updater'; Prep = { param($r) $global:Procs = @([pscustomobject]@{ ProcessId = 99999; Name = 'modelrig-updater-windows-x64.exe'; CommandLine = '' }) }; Expect = 'An updater is running' },
    @{ What = 'running helper'; Prep = { param($r) $global:Procs = @([pscustomobject]@{ ProcessId = 99998; Name = 'powershell.exe'; CommandLine = "powershell -Command x modelrig-updater-windows-x64.exe.pending" }) }; Expect = 'replacement helper is running' },
    @{ What = 'tampered download'; Prep = { param($r) $global:BadDownload = 'modelrig-worker-windows-x64.exe' }; Expect = 'does not match' }
)) {
    Reset '2.0.20'; $r = New-Rig $all2020
    & $case.Prep $r
    $before = @(Get-ChildItem $r -Recurse -File | ForEach-Object { $_.FullName + '=' + (Get-FileHash $_.FullName).Hash }) -join '|'
    $e = RunErr $r @{ Apply = $true }
    Check ($e -match [regex]::Escape($case.Expect)) "$($case.What): refused ($($e.Substring(0, [Math]::Min(70, $e.Length))))"
    Check ($global:Calls.Count -eq 0) "$($case.What): no task call"
    $after = @(Get-ChildItem $r -Recurse -File | Where-Object { $_.FullName -notlike '*\backups\*' -and $_.FullName -notlike '*/backups/*' } | ForEach-Object { $_.FullName + '=' + (Get-FileHash $_.FullName).Hash }) -join '|'
    Check ($before -ceq $after) "$($case.What): rig files unchanged"
}

Write-Host 'a failed swap puts 2.0.20 back and restarts'
Reset '2.0.20'; $r = New-Rig $all2020
$global:FailCopyTo = 'modelrig-worker-windows-x64.exe'
[IO.File]::WriteAllText((Join-Path $r 'update-transaction.json'), '{"state":"committed"}')
$e = RunErr $r @{ Apply = $true }
Check ($e -match 'rolled back to v2.0.20') 'reports rollback'
Check (LiveIs $r '2.0.20') 'live set back on 2.0.20'
Check (-not (Test-Path (Join-Path $r 'updater.lock'))) 'lock released'
Check (($global:Calls -join ',') -ceq 'stop-task,start-task') 'supervisor restarted once'

Write-Host 'health that never reaches 2.0.12 fails loudly'
Reset '2.0.20'; $r = New-Rig $all2020
$global:HealthAfterStart = '2.0.20'
$e = RunErr $r @{ Apply = $true; HealthTimeoutSeconds = 4 }
Check ($e -match 'did not both report 2.0.12') 'reports health failure'
Check (-not (Test-Path (Join-Path $r 'updater.lock'))) 'lock released'
Check (($global:Calls -join ',') -ceq 'stop-task,start-task') 'supervisor started exactly once'

Write-Host 'provenance check against the real GitHub attestations'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($copy, [ref]$null, [ref]$null)
$fn = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-ReleaseProvenance-Real' }, $true) | Select-Object -First 1
. ([scriptblock]::Create($fn.Extent.Text))
$SourceTag = 'v2.0.12'
$global:AttReply = Get-Content (Join-Path $fixtures 'att-server-2012.json') -Raw | ConvertFrom-Json
$ok = $true; try { Assert-ReleaseProvenance-Real '0af13cb40220f757cd7782d00a82de32e92f7faaf9510720f93ef04bf1415269' } catch { $ok = $false; Write-Host $_ }
Check $ok 'real v2.0.12 server attestation accepted'
$global:AttReply = Get-Content (Join-Path $fixtures 'att-server-2020.json') -Raw | ConvertFrom-Json
$ok = $false; try { Assert-ReleaseProvenance-Real '23933927652492da1b70bbec424df60f4315ec43b5bf9a0bc085e4da1b088cc7' } catch { $ok = $true }
Check $ok 'v2.0.20 attestation refused for source tag v2.0.12'
$global:AttReply = Get-Content (Join-Path $fixtures 'att-server-2012.json') -Raw | ConvertFrom-Json
$ok = $true; try { Assert-ReleaseProvenance-Real '05148f125801b471ea504918cffbd76c6609342ccce39a3eb50d470c208a65b2' } catch { $ok = $false }
Check $ok 'v2.0.12 worker accepted (one attestation covers all release assets)'
$ok = $false; try { Assert-ReleaseProvenance-Real '7a255a2dcdfb5b73ba3eaede75b6a182e5e360a1b59cd731f5250b25d853a9ab' } catch { $ok = $true }
Check $ok 'digest outside the attestation subjects refused'

Remove-Item -LiteralPath $here -Recurse -Force
Write-Host "failures: $fails"
exit $fails
