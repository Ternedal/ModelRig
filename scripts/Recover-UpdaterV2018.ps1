# Recovery for a verified updater stranded as .pending by the legacy one-shot helper.
# By default the target is v2.0.18, whose bytes are pinned below: the release-bound,
# cryptographically verified asset built at 5d535a8d391f25677c0e3d85e82eb8a9360c796b.
#
# Every updater up to and including v2.0.18 has that helper and runs a self-update by itself after
# an appliance update, so the move to the NEXT release strands the same way (#2241 6724065058).
# For that release, pass its version and the updater's SHA-256 from its attested SHA256SUMS.txt
# (printed in its release notes):
#   Recover-UpdaterV2018.ps1 -ExpectedVersion 2.0.19 -ExpectedSha256 <64 hex>
# The checks are the same for every target, and no verification flags change.
[CmdletBinding()]
param(
    [string]$RigRoot = 'C:\Rig\ModelRig',
    [switch]$InstallOnly,
    [string]$ExpectedVersion = '2.0.18',
    [string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$V2018Updater = 'a62716e195d5fb4a33f14f045a7e7217ec8d5797f12d1a7eb8bd0db092b41b2d'
if ($ExpectedVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "ExpectedVersion '$ExpectedVersion' is not X.Y.Z. No files changed." }
if (-not $ExpectedSha256) {
    if ($ExpectedVersion -cne '2.0.18') {
        throw "Updater $ExpectedVersion needs -ExpectedSha256 from that release's attested SHA256SUMS.txt. No files changed."
    }
    $ExpectedSha256 = $V2018Updater
}
$expectedHash = $ExpectedSha256.Trim().ToLowerInvariant()
if ($expectedHash -notmatch '^[0-9a-f]{64}$') { throw 'ExpectedSha256 is not a 64-digit SHA-256. No files changed.' }
if ($ExpectedVersion -ceq '2.0.18' -and $expectedHash -cne $V2018Updater) {
    throw 'ExpectedSha256 is not the attested v2.0.18 updater. No files changed.'
}
$RigRoot = [IO.Path]::GetFullPath($RigRoot)
$live = Join-Path $RigRoot 'modelrig-updater-windows-x64.exe'
$pending = $live + '.pending'
$lockPath = Join-Path $RigRoot 'updater.lock'

function Get-SHA256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

# Never race another updater or a detached replacement helper. Fail closed if
# process inspection itself fails, rather than treating unknown as stopped.
$processes = @(Get-CimInstance Win32_Process -Filter "Name='modelrig-updater-windows-x64.exe' OR Name='powershell.exe' OR Name='pwsh.exe'")
foreach ($process in $processes) {
    if ($process.ProcessId -eq $PID) { continue }
    if ($process.Name -ieq 'modelrig-updater-windows-x64.exe') {
        throw "An updater is still running (PID $($process.ProcessId)). No files changed."
    }
    $command = [string]$process.CommandLine
    if ($command -match 'modelrig-updater-windows-x64\.exe' -and $command -match '\.pending' -and $command -match 'Wait-Process|Move-Item|\[IO\.File\]::Replace') {
        throw "A replacement helper is still running (PID $($process.ProcessId)). No files changed."
    }
}

foreach ($name in @('update-transaction.json', 'update-transaction.json.tmp')) {
    $path = Join-Path $RigRoot $name
    if (Test-Path -LiteralPath $path) {
        $journal = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($journal.state -notin @('committed', 'rolled_back')) {
            throw "Unfinished appliance transaction in $name ($($journal.state)). No files changed."
        }
    }
}
if (-not (Test-Path -LiteralPath $live -PathType Leaf)) { throw "Installed updater is missing: $live" }
$alreadyInstalled = (Get-SHA256 $live) -ceq $expectedHash
if (-not $alreadyInstalled) {
    if (-not (Test-Path -LiteralPath $pending -PathType Leaf)) {
        throw "The verified pending updater is missing: $pending. No files changed."
    }
    if ((Get-SHA256 $pending) -cne $expectedHash) { throw "Pending updater differs from the verified v$ExpectedVersion release. No files changed." }
}

$suffix = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N')
if (Test-Path -LiteralPath $lockPath) {
    $lockText = (Get-Content -LiteralPath $lockPath -Raw).Trim()
    if ($lockText -notmatch '^pid ([0-9]+) started \S+$') { throw 'Unrecognized updater lock. No files changed.' }
    $ownerId = [int]$Matches[1]
    if (Get-Process -Id $ownerId -ErrorAction SilentlyContinue) {
        throw "The updater lock owner is still alive (PID $ownerId). No files changed."
    }
    Move-Item -LiteralPath $lockPath -Destination ($lockPath + '.stale-' + $suffix)
}

# The normal updater uses exclusive creation of this same lock. Taking it before
# replacement also blocks any new update launched by a scheduled task.
$guard = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
try {
    $lockBytes = [Text.Encoding]::UTF8.GetBytes("pid $PID started $([DateTime]::UtcNow.ToString('o'))")
    $guard.Write($lockBytes, 0, $lockBytes.Length)
    $guard.Flush()
    if (-not $alreadyInstalled) {
        $backupDirectory = Join-Path $RigRoot 'backups'
        [IO.Directory]::CreateDirectory($backupDirectory) | Out-Null
        $backup = Join-Path $backupDirectory ('updater-before-v' + $ExpectedVersion + '-' + $suffix + '.exe')
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while ($true) {
            try {
                # Same-volume atomic replacement retains the original executable
                # as a backup. A failed replacement leaves the old updater intact.
                [IO.File]::Replace($pending, $live, $backup)
                break
            } catch {
                $cause = $_.Exception
                while ($cause.InnerException) { $cause = $cause.InnerException }
                $win32Code = $cause.HResult -band 0xffff
                if ($win32Code -notin @(32, 33) -or [DateTime]::UtcNow -ge $deadline) { throw }
                Start-Sleep -Milliseconds 500
            }
        }
        Write-Host "Original updater kept at $backup"
    }
    if ((Get-SHA256 $live) -cne $expectedHash) { throw "Installed updater SHA256 differs from v$ExpectedVersion." }
    $version = (& $live -version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $version -cne $ExpectedVersion) { throw "Installed updater did not report version $ExpectedVersion." }
    Write-Host "Updater $ExpectedVersion installed and verified."
} finally {
    $guard.Dispose()
    Remove-Item -LiteralPath $lockPath -Force
}
if (-not $InstallOnly) {
    & $live -dir $RigRoot
    if ($LASTEXITCODE -ne 0) { throw "Appliance update exited with code $LASTEXITCODE. Keep its output for diagnosis." }
}
