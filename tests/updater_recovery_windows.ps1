[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$AssetRoot,
    [switch]$ProbeReleasedV16
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script = Join-Path $PSScriptRoot '..\scripts\Recover-UpdaterV2018.ps1'
$name = 'modelrig-updater-windows-x64.exe'
$oldAsset = Join-Path (Join-Path $AssetRoot 'v2.0.16') $name
$newAsset = Join-Path (Join-Path $AssetRoot 'v2.0.18') $name
$oldHash = (Get-FileHash $oldAsset -Algorithm SHA256).Hash
$newHash = (Get-FileHash $newAsset -Algorithm SHA256).Hash
$suite = Join-Path $env:RUNNER_TEMP ("Anders's Rig " + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($suite) | Out-Null
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function New-Fixture([string]$Case) {
    $root = Join-Path $suite $Case
    [IO.Directory]::CreateDirectory($root) | Out-Null
    Copy-Item -LiteralPath $oldAsset -Destination (Join-Path $root $name)
    Copy-Item -LiteralPath $newAsset -Destination ((Join-Path $root $name) + '.pending')
    return $root
}
function Assert-Installed([string]$Root) {
    $live = Join-Path $Root $name
    Assert ((Get-FileHash $live -Algorithm SHA256).Hash -ceq $newHash) 'Installed hash differs from signed v2.0.18'
    Assert (-not (Test-Path (Join-Path $Root 'updater.lock'))) 'Recovery stranded its lock'
    $backups = @(Get-ChildItem (Join-Path $Root 'backups') -Filter '*.exe')
    Assert ($backups.Count -eq 1) 'Original updater backup missing or ambiguous'
    Assert ((Get-FileHash $backups[0].FullName -Algorithm SHA256).Hash -ceq $oldHash) 'Backup does not contain the original updater'
}
function Assert-Refused([string]$Root, [string]$Pattern) {
    $caught = $null
    try { & $script -RigRoot $Root -InstallOnly } catch { $caught = $_ }
    Assert ($null -ne $caught) 'Unsafe recovery was accepted'
    Assert ($caught.Exception.Message -match $Pattern) ("Unexpected refusal: " + $caught.Exception.Message)
    Assert ((Get-FileHash (Join-Path $Root $name) -Algorithm SHA256).Hash -ceq $oldHash) 'Refused recovery changed the installed updater'
}

$root = New-Fixture 'normal'
& $script -RigRoot $root -InstallOnly
Assert-Installed $root
Write-Host 'PASS: verified pending file atomically installed with exact original backup'

$dead = Start-Process $env:ComSpec -ArgumentList '/c exit 0' -PassThru -Wait -WindowStyle Hidden
$deadId = $dead.Id
$root = New-Fixture 'stale-lock'
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value "pid $deadId started 2026-10-20T15:55:30Z"
& $script -RigRoot $root -InstallOnly
Assert-Installed $root
Assert (@(Get-ChildItem $root -Filter 'updater.lock.stale-*').Count -eq 1) 'Stale lock evidence was not retained'
Write-Host 'PASS: dead owner lock archived before recovery'

$root = New-Fixture 'already-installed'
Copy-Item -LiteralPath $newAsset -Destination (Join-Path $root $name) -Force
Remove-Item -LiteralPath ((Join-Path $root $name) + '.pending')
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value "pid $deadId started 2026-10-20T15:55:30Z"
& $script -RigRoot $root -InstallOnly
Assert (-not (Test-Path (Join-Path $root 'updater.lock'))) 'Already-installed recovery stranded lock'
Write-Host 'PASS: already-installed v18 and stale lock handled without needing pending file'

$root = New-Fixture 'bad-hash'
Set-Content -LiteralPath ((Join-Path $root $name) + '.pending') -Value 'wrong bytes'
Assert-Refused $root 'differs from the verified'
$root = New-Fixture 'live-owner'
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value "pid $PID started 2026-10-20T15:55:30Z"
Assert-Refused $root 'owner is still alive'
$root = New-Fixture 'unknown-lock'
Set-Content -LiteralPath (Join-Path $root 'updater.lock') -Value 'unknown owner'
Assert-Refused $root 'Unrecognized updater lock'
$root = New-Fixture 'unfinished-transaction'
Set-Content -LiteralPath (Join-Path $root 'update-transaction.json.tmp') -Value '{"state":"swapping"}'
Assert-Refused $root 'Unfinished appliance transaction'
$root = New-Fixture 'missing-pending'
Remove-Item -LiteralPath ((Join-Path $root $name) + '.pending')
Assert-Refused $root 'pending updater is missing'
Write-Host 'PASS: bad hash, live owner, unknown lock, unfinished transaction and missing pending all refuse without replacing old updater'

# Execute the old helper's actual PowerShell body while a Windows file handle
# denies FILE_SHARE_DELETE, then show recovery survives the same transient lock.
$root = New-Fixture 'legacy-sharing-lock'
$live = Join-Path $root $name
$pending = $live + '.pending'
$lock = Join-Path $root 'updater.lock'
Set-Content -LiteralPath $lock -Value "pid $deadId started 2026-10-20T15:55:30Z"
function Quote-PS([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
$legacyBody = '$ErrorActionPreference=''Stop''; Wait-Process -Id ' + $deadId + ' -ErrorAction SilentlyContinue; try { Move-Item -LiteralPath ' + (Quote-PS $pending) + ' -Destination ' + (Quote-PS $live) + ' -Force } finally { Remove-Item -LiteralPath ' + (Quote-PS $lock) + ' -Force -ErrorAction SilentlyContinue }'
$handle = [IO.File]::Open($live, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
try {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($legacyBody))
    $helper = Start-Process powershell.exe -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', $encoded) -PassThru -Wait -WindowStyle Hidden
    Assert ($helper.ExitCode -ne 0) 'Legacy helper unexpectedly replaced a delete-locked executable'
    Assert ((Get-FileHash $live -Algorithm SHA256).Hash -ceq $oldHash) 'Legacy failure did not preserve old file'
    Assert (Test-Path -LiteralPath $pending) 'Legacy failure lost verified pending file'
} finally { $handle.Dispose() }
Write-Host 'PASS: reproduced legacy one-shot helper failure on a Windows sharing lock'

$ready = Join-Path $root 'sharing-lock-ready'
$holdBody = '$h=[IO.File]::Open(' + (Quote-PS $live) + ',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite); try { [IO.File]::WriteAllText(' + (Quote-PS $ready) + ',''ready''); Start-Sleep -Seconds 4 } finally { $h.Dispose() }'
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($holdBody))
$holder = Start-Process powershell.exe -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', $encoded) -PassThru -WindowStyle Hidden
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not (Test-Path -LiteralPath $ready)) {
        if ($holder.HasExited -or [DateTime]::UtcNow -gt $deadline) { throw 'Sharing lock fixture did not start' }
        Start-Sleep -Milliseconds 100
    }
    & $script -RigRoot $root -InstallOnly
    Assert-Installed $root
} finally { if (-not $holder.HasExited) { $holder.WaitForExit(10000) | Out-Null } }
Write-Host 'PASS: recovery retried an actual transient Windows sharing violation and retained the original bytes'

# Exercise the exact immutable-download/bootstrap command in a fresh PowerShell
# process, with InstallOnly as the sole CI substitution for updating the rig.
$root = New-Fixture 'downloaded-bootstrap'
$fix = Join-Path $root 'Recover-UpdaterV2018.ps1'
Invoke-WebRequest 'https://raw.githubusercontent.com/Ternedal/ModelRig/e57653fc6df979e420bc0cac9edab06f438670c0/scripts/Recover-UpdaterV2018.ps1' -OutFile $fix -UseBasicParsing
if ((Get-FileHash -LiteralPath $fix -Algorithm SHA256).Hash.ToLowerInvariant() -cne '93c9afb9e6526bbe544076259a56fea8d8c0c72c2d09a92a00efd09bfb1a8226') { throw 'Downloaded recovery script checksum differs' }
& pwsh -NoProfile -ExecutionPolicy Bypass -File $fix -RigRoot $root -InstallOnly
Assert ($LASTEXITCODE -eq 0) 'Downloaded recovery command failed'
Assert-Installed $root
Write-Host 'PASS: immutable downloaded recovery command installs exact signed v18 bytes in a fresh PowerShell process'

# The archived v16 executable uses an unauthenticated GitHub metadata request.
# Its bootstrap defect is already reproduced in runs 39436520247 and 39437312491.
# Keep this external diagnostic explicit; the recovery and real current helper
# regression tests run on every push without depending on that old HTTP client.
if ($ProbeReleasedV16) {
    # Exercise the actual published v16 updater, including its real detached helper.
    # This explicit diagnostic records whether the user failure occurs on clean Windows
    # runner; it does not mistake that result for evidence from the physical rig.
    $root = Join-Path $env:RUNNER_TEMP ('actual-released-v16-clean-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($root) | Out-Null
    $live = Join-Path $root $name
    Copy-Item -LiteralPath $oldAsset -Destination $live
    & $live -self-update -dir $root
    Assert ($LASTEXITCODE -eq 0) 'Actual released v16 updater failed before staging/replacement'
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    $swapped = $false
    do {
        if (-not (Test-Path (Join-Path $root 'updater.lock'))) {
            $swapped = (Get-FileHash $live -Algorithm SHA256).Hash -ceq $newHash
            if ($swapped) { break }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    Write-Host "ACTUAL RELEASED V16 HELPER: installed-v18=$swapped pending=$(Test-Path ($live + '.pending')) lock=$(Test-Path (Join-Path $root 'updater.lock'))"
    if (-not $swapped) { & $script -RigRoot $root -InstallOnly; Assert-Installed $root }
    Write-Host 'PASS: actual published updater bootstrap finished or was recovered with pinned v18 bytes'
}
