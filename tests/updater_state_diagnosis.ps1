# Get-UpdaterState.ps1 is read-only and names every state the recovery distinguishes.
# Runs against the real published v2.0.16 and v2.0.18 updater executables (-AssetRoot), in both
# Windows PowerShell 5.1 and PowerShell 7 (updater-v18-recovery-check.yml).
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$AssetRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script = Join-Path $PSScriptRoot '..\scripts\Get-UpdaterState.ps1'
$name = 'modelrig-updater-windows-x64.exe'
$oldAsset = Join-Path (Join-Path $AssetRoot 'v2.0.16') $name
$newAsset = Join-Path (Join-Path $AssetRoot 'v2.0.18') $name
$temp = $env:RUNNER_TEMP
if (-not $temp) { $temp = [IO.Path]::GetTempPath() }
$suite = Join-Path $temp ("Anders's Rig diagnosis " + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($suite) | Out-Null
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }

# A process that has exited: its PID is a dead lock owner.
$dead = Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList @('-NoProfile', '-Command', 'exit 0') -PassThru -Wait
$deadId = $dead.Id

function New-Fixture([string]$Case, [string]$Live, [string]$Pending) {
    $root = Join-Path $suite $Case
    [IO.Directory]::CreateDirectory($root) | Out-Null
    if ($Live) { Copy-Item -LiteralPath $Live -Destination (Join-Path $root $name) }
    if ($Pending) { Copy-Item -LiteralPath $Pending -Destination ((Join-Path $root $name) + '.pending') }
    return $root
}
function Get-Snapshot([string]$Root) {
    $lines = foreach ($file in @(Get-ChildItem -LiteralPath $Root -Recurse -Force -File | Sort-Object FullName)) {
        '{0}|{1}|{2}|{3}' -f $file.FullName.Substring($Root.Length), $file.Length,
            (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash, $file.LastWriteTimeUtc.Ticks
    }
    return ($lines -join "`n")
}
function Test-Case([string]$Root, [string]$Expected) {
    $before = Get-Snapshot $Root
    $result = (& $script -RigRoot $Root -SkipHealth -Json | Out-String) | ConvertFrom-Json
    Assert ((Get-Snapshot $Root) -ceq $before) "the diagnosis changed files in $Root"
    Assert ($result.Verdict -ceq $Expected) ("expected $Expected, got " + $result.Verdict + " in $Root")
    Write-Host "PASS: $Expected, nothing changed"
    return $result
}

$r = Test-Case (New-Fixture 'stranded' $oldAsset $newAsset) 'stranded_v2018_pending'
Assert ($r.Executables.$name.Release -ceq '2.0.16') 'the old updater is named 2.0.16'
Assert ($r.Pending.Release -ceq '2.0.18') 'the pending updater is named 2.0.18'

$root = New-Fixture 'stranded-stale-lock' $oldAsset $newAsset
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value "pid $deadId started 2026-10-20T15:55:30Z"
$r = Test-Case $root 'stranded_v2018_pending'
Assert ($r.Lock.OwnerPid -eq $deadId -and $r.Lock.OwnerAlive -eq $false) 'a dead lock owner is reported dead'

$root = New-Fixture 'live-owner' $oldAsset $newAsset
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value "pid $PID started 2026-10-20T15:55:30Z"
$null = Test-Case $root 'lock_owner_alive'

$root = New-Fixture 'unknown-lock' $oldAsset $newAsset
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value 'unknown owner'
$null = Test-Case $root 'lock_unrecognized'

$null = Test-Case (New-Fixture 'installed' $newAsset $null) 'installed_v2018'

# The installed layout (Codex #2241 4505567754): the worker lives in RigRoot\worker, as the updater
# and bootstrap-new-rig.ps1 install it. A stray copy in RigRoot itself is not the installed worker.
$root = New-Fixture 'installed-layout' $newAsset $null
$workerName = 'modelrig-worker-windows-x64.exe'
$workerPath = Join-Path (Join-Path $root 'worker') $workerName
[IO.Directory]::CreateDirectory((Split-Path -Parent $workerPath)) | Out-Null
Set-Content -LiteralPath $workerPath -Value 'the installed worker'
Set-Content -LiteralPath (Join-Path $root $workerName) -Value 'a stray copy'
$r = Test-Case $root 'installed_v2018'
$worker = $r.Executables.$workerName
Assert ($worker.Present -eq $true) 'the worker in RigRoot\worker is found'
Assert ($worker.Sha256 -ceq (Get-FileHash -LiteralPath $workerPath -Algorithm SHA256).Hash.ToLowerInvariant()) 'the worker is hashed from RigRoot\worker, not from RigRoot'
Assert ($worker.Release -ceq 'unknown') 'bytes that match no release are named unknown'
$r = Test-Case (New-Fixture 'no-worker-dir' $newAsset $null) 'installed_v2018'
Assert ($r.Executables.$workerName.Present -eq $false) 'without RigRoot\worker the worker is reported missing'

$root = New-Fixture 'installed-stale-lock' $newAsset $null
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value "pid $deadId started 2026-10-20T15:55:30Z"
$null = Test-Case $root 'installed_v2018_stale_lock'

$root = New-Fixture 'bad-pending' $oldAsset $null
Set-Content -LiteralPath ((Join-Path $root $name) + '.pending') -Value 'wrong bytes'
$r = Test-Case $root 'pending_unknown'
Assert ($r.Pending.Release -ceq 'unknown') 'unknown bytes are named unknown'

$root = New-Fixture 'unfinished-transaction' $oldAsset $newAsset
Set-Content -LiteralPath (Join-Path $root 'update-transaction.json.tmp') -Value '{"state":"swapping"}'
$null = Test-Case $root 'transaction_unfinished'

$root = New-Fixture 'finished-transaction' $newAsset $null
Set-Content -LiteralPath (Join-Path $root 'update-transaction.json') -Value '{"state":"committed"}'
$null = Test-Case $root 'installed_v2018'

$null = Test-Case (New-Fixture 'not-staged' $oldAsset $null) 'not_staged'
$null = Test-Case (New-Fixture 'empty' $null $null) 'updater_missing'
Write-Host 'PASS: every updater state named, and the diagnosis wrote, moved and deleted nothing'
