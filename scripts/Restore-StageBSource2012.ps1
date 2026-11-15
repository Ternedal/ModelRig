# Restore-StageBSource2012.ps1
#
# Puts the appliance back on the signed v2.0.12 server, supervisor and worker, so that Stage B
# (STAGE_B_UPDATER_EVIDENCE.md) can start from its required source. The live updater stays the
# signed v2.0.20 updater: Stage B measures it against v2.0.20's SHA256SUMS as its bootstrap
# boundary, so this script refuses to run unless it is exactly that file, and never touches it.
#
# A source rollback is always two things together (STAGE_B_UPDATER_EVIDENCE.md, "Rollback-reglen"):
# the signed source binaries AND archiving update-transaction.json/.tmp. This script does both.
#
# Without -Apply it only checks and prints the plan: nothing is downloaded, written, stopped or
# moved. With -Apply it:
#   1. downloads the three v2.0.12 executables and verifies each SHA-256 (pinned from v2.0.12's
#      SHA256SUMS.txt) and GitHub build provenance (build-and-release.yml at refs/tags/v2.0.12),
#      all before anything on the rig changes;
#   2. takes updater.lock, so no updater run can start meanwhile;
#   3. stops the supervisor task and the running set, the same way the updater does;
#   4. copies the current v2.0.20 executables to a backup folder and archives the journal files;
#   5. replaces the three executables and verifies their hashes;
#   6. starts the supervisor task, waits until backend and worker report 2.0.12, and proves the
#      supervisor is looping from its heartbeat, as the updater does after an update.
# If any step after the lock fails, including step 6, it rolls back to the v2.0.20 executables and
# the original journal, verifies both, and starts the task again (see "mutate" below).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File Restore-StageBSource2012.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File Restore-StageBSource2012.ps1 -Apply
[CmdletBinding()]
param(
    [string]$RigRoot = 'C:\Rig\ModelRig',
    [switch]$Apply,
    [string]$SupervisorTask = 'KalivSupervisor',
    [int]$HealthTimeoutSeconds = 300,
    # The supervisor's tick (modelrig-updater -supervisor-interval) and how long a restarted
    # supervisor gets to write its first heartbeat (the updater's ProveLooping settle).
    [int]$SupervisorIntervalSeconds = 10,
    [int]$HeartbeatSettleSeconds = 45
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProgressPreference = 'SilentlyContinue'

$SourceVersion = '2.0.12'
$SourceTag = 'v2.0.12'
$TargetVersion = '2.0.20'
# SHA-256 from each release's SHA256SUMS.txt. Source = v2.0.12 (what gets installed),
# Target = v2.0.20 (what must be live before the restore).
$Assets = [ordered]@{
    'modelrig-server-windows-x64.exe'     = @{ Source = '0af13cb40220f757cd7782d00a82de32e92f7faaf9510720f93ef04bf1415269'; Target = '23933927652492da1b70bbec424df60f4315ec43b5bf9a0bc085e4da1b088cc7' }
    'modelrig-supervisor-windows-x64.exe' = @{ Source = 'f4007a07c9259902bf5dfdd711e1a772c94d47244597da62e91ac4f762cc2a70'; Target = '50274ab5e4b1e366b0a3b4cf56c1b11eaad096bd2ed68eaefc31e36958b544c1' }
    'modelrig-worker-windows-x64.exe'     = @{ Source = '05148f125801b471ea504918cffbd76c6609342ccce39a3eb50d470c208a65b2'; Target = '7a255a2dcdfb5b73ba3eaede75b6a182e5e360a1b59cd731f5250b25d853a9ab' }
}
$UpdaterName = 'modelrig-updater-windows-x64.exe'
$UpdaterSha = '26e131ccfaa9e551311c5e897d1e8c3b964e7bc0b519e2b2f015458c3b0237ed'
# Where each executable lives, as the updater installs them: the worker in its own subdirectory,
# everything else in the rig root (modelrig-updater main.go; Get-UpdaterState.ps1).
$InstalledAt = @{ 'modelrig-worker-windows-x64.exe' = 'worker' }
$ServerHealth = 'http://127.0.0.1:8080/healthz'
$WorkerHealth = 'http://127.0.0.1:8099/healthz'

function Get-LivePath([string]$Name) {
    if ($InstalledAt.ContainsKey($Name)) { return Join-Path (Join-Path $RigRoot $InstalledAt[$Name]) $Name }
    return Join-Path $RigRoot $Name
}

function Get-SHA256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-HealthVersion([string]$Uri) {
    try { return [string](Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 5 -UseBasicParsing).version }
    catch { return $null }
}

# The same question the updater and Recover-UpdaterV2018.ps1 ask: does GitHub hold a build-provenance
# attestation for exactly this digest, signed by build-and-release.yml at the source tag?
function Assert-ReleaseProvenance([string]$Digest) {
    $uri = "https://api.github.com/repos/Ternedal/ModelRig/attestations/sha256:$Digest"
    $headers = @{ Accept = 'application/vnd.github+json'; 'User-Agent' = 'modelrig-stage-b-source-restore' }
    if ($env:GH_TOKEN) { $headers['Authorization'] = 'Bearer ' + $env:GH_TOKEN }
    try { $reply = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 30 -UseBasicParsing }
    catch { throw "Could not get GitHub's attestation for $Digest ($($_.Exception.Message)). Nothing on the rig was changed." }
    $signer = "https://github.com/Ternedal/ModelRig/.github/workflows/build-and-release.yml@refs/tags/$SourceTag"
    $attestations = @()
    if ($reply -and ($reply.PSObject.Properties.Name -contains 'attestations')) { $attestations = @($reply.attestations) }
    foreach ($attestation in $attestations) {
        try {
            $bundle = $attestation.bundle
            $payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$bundle.dsseEnvelope.payload))
            $subjects = @(($payload | ConvertFrom-Json).subject | Where-Object { [string]$_.digest.sha256 -ceq $Digest })
            if ($subjects.Count -eq 0) { continue }
            $cert = [Security.Cryptography.X509Certificates.X509Certificate2]::new([Convert]::FromBase64String([string]$bundle.verificationMaterial.certificate.rawBytes))
            $san = @($cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.17' })
            if ($san.Count -ne 1) { continue }
            $uris = @([regex]::Matches($san[0].Format($false), 'https://[^\s,]+') | ForEach-Object { $_.Value })
            if ($uris -ccontains $signer) { return }
        } catch { continue }
    }
    throw "GitHub holds no attestation for $Digest signed by build-and-release.yml at $SourceTag. Nothing on the rig was changed."
}

function Stop-RunningSet {
    Stop-ScheduledTask -TaskName $SupervisorTask -ErrorAction SilentlyContinue
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ($true) {
        $running = @(Get-Process -Name 'modelrig-server*', 'modelrig-worker*', 'modelrig-supervisor*' -ErrorAction SilentlyContinue)
        if ($running.Count -eq 0) { return }
        if ([DateTime]::UtcNow -ge $deadline) { throw "The running set did not stop: $(($running | ForEach-Object { "$($_.Name)($($_.Id))" }) -join ', ')" }
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
}

function Set-Executable([string]$From, [string]$To) {
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    $reported = $false
    while ($true) {
        try { Copy-Item -LiteralPath $From -Destination $To -Force; return }
        catch {
            $cause = $_.Exception
            while ($cause.InnerException) { $cause = $cause.InnerException }
            $code = $cause.HResult -band 0xffff
            if ($code -notin @(32, 33) -or [DateTime]::UtcNow -ge $deadline) { throw }
            if (-not $reported) { Write-Host "waiting for another process to release $To"; $reported = $true }
            Start-Sleep -Milliseconds 500
        }
    }
}

# ---------------------------------------------------------------- preflight (read-only)
$RigRoot = [IO.Path]::GetFullPath($RigRoot)
if (-not (Test-Path -LiteralPath $RigRoot -PathType Container)) { throw "Rig root not found: $RigRoot" }
$updater = Join-Path $RigRoot $UpdaterName
$lockPath = Join-Path $RigRoot 'updater.lock'

if (-not (Test-Path -LiteralPath $updater -PathType Leaf)) { throw "Live updater missing: $updater" }
if ((Get-SHA256 $updater) -cne $UpdaterSha) { throw "Live updater is not the signed v$TargetVersion updater, which Stage B requires as its bootstrap. Nothing changed." }
$updaterVersion = (& $updater -version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $updaterVersion -cne $TargetVersion) { throw "Live updater reports '$updaterVersion', not $TargetVersion. Nothing changed." }

$processes = @(Get-CimInstance Win32_Process -Filter "Name='modelrig-updater-windows-x64.exe' OR Name='powershell.exe' OR Name='pwsh.exe'")
foreach ($process in $processes) {
    if ($process.ProcessId -eq $PID) { continue }
    if ($process.Name -ieq $UpdaterName) { throw "An updater is running (PID $($process.ProcessId)). Nothing changed." }
    $command = [string]$process.CommandLine
    if ($command -match 'modelrig-updater-windows-x64\.exe' -and $command -match '\.pending') {
        throw "An updater replacement helper is running (PID $($process.ProcessId)). Nothing changed."
    }
}
if (Test-Path -LiteralPath $lockPath) { throw "updater.lock exists ($((Get-Content -LiteralPath $lockPath -Raw).Trim())). Run Get-UpdaterState.ps1 first. Nothing changed." }
if (Test-Path -LiteralPath ($updater + '.pending')) { throw "A staged updater .pending exists. Run Get-UpdaterState.ps1 first. Nothing changed." }

$journals = @()
foreach ($name in @('update-transaction.json', 'update-transaction.json.tmp')) {
    $path = Join-Path $RigRoot $name
    if (Test-Path -LiteralPath $path) {
        $state = $null
        try { $state = [string]((Get-Content -LiteralPath $path -Raw | ConvertFrom-Json).state) } catch { }
        if ($state -notin @('committed', 'rolled_back')) { throw "Unfinished appliance transaction in $name (state '$state'). Run the updater with -recover first. Nothing changed." }
        $journals += $path
    }
}

$plan = @()
foreach ($name in $Assets.Keys) {
    $path = Get-LivePath $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Live executable missing: $path. Nothing changed." }
    $hash = Get-SHA256 $path
    if ($hash -ceq $Assets[$name].Source) { $plan += [pscustomobject]@{ Name = $name; Live = $SourceVersion; Action = 'keep' } }
    elseif ($hash -ceq $Assets[$name].Target) { $plan += [pscustomobject]@{ Name = $name; Live = $TargetVersion; Action = 'replace' } }
    else { throw "$name is neither signed v$TargetVersion nor v$SourceVersion (sha256 $hash). Nothing changed." }
}
$serverVersion = Get-HealthVersion $ServerHealth
$workerVersion = Get-HealthVersion $WorkerHealth
$replace = @($plan | Where-Object { $_.Action -eq 'replace' })

Write-Host "updater_version=$updaterVersion updater_sha256_matches_v$TargetVersion=true"
Write-Host "backend_version=$serverVersion worker_version=$workerVersion"
foreach ($row in $plan) { Write-Host ("{0}: live {1} -> {2}" -f $row.Name, $row.Live, $row.Action) }
Write-Host ("journals_to_archive=" + $journals.Count)
if ($replace.Count -eq 0 -and $journals.Count -eq 0 -and $serverVersion -ceq $SourceVersion -and $workerVersion -ceq $SourceVersion) {
    Write-Host "Already on signed v$SourceVersion with no journal. Stage B source is ready."
    exit 0
}
if ([string]::IsNullOrEmpty($serverVersion) -or [string]::IsNullOrEmpty($workerVersion)) {
    throw "Backend and worker must both answer healthz before a restore, so a rollback has a known state to return to. Nothing changed."
}
if (-not $Apply) {
    Write-Host "Check only. Nothing was changed. Run again with -Apply to restore v$SourceVersion."
    exit 0
}

# ---------------------------------------------------------------- download and verify, before any change
$suffix = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$work = Join-Path (Join-Path $RigRoot 'backups') ('stage-b-source-' + $suffix)
$staged = Join-Path $work 'v2.0.12'
$previous = Join-Path $work 'v2.0.20'
[IO.Directory]::CreateDirectory($staged) | Out-Null
[IO.Directory]::CreateDirectory($previous) | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
foreach ($row in $replace) {
    $file = Join-Path $staged $row.Name
    Write-Host "downloading $SourceTag $($row.Name)"
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Ternedal/ModelRig/releases/download/$SourceTag/$($row.Name)" -OutFile $file -TimeoutSec 900
    if ((Get-SHA256 $file) -cne $Assets[$row.Name].Source) { throw "Downloaded $($row.Name) does not match v$SourceVersion's SHA256SUMS. Nothing on the rig was changed." }
    Assert-ReleaseProvenance $Assets[$row.Name].Source
    Write-Host "verified $($row.Name): checksum and provenance"
}

# ---------------------------------------------------------------- mutate, under the updater lock
# Any failure from here on - a backup, the journal archive, a swap, a hash, starting the task, or
# backend and worker not reporting 2.0.12 in time - rolls the rig back to exactly what it was:
# the v2.0.20 executables (verified), the journal files at their original paths (verified), the
# task started, and health waited for. Only if that rollback itself cannot be verified does the
# script stop with the task NOT started and updater.lock KEPT, so no updater run can act on a
# half-restored rig; the message names the folder that holds both sets and the journal.
function Wait-Health([string]$Server, [string]$Worker) {
    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    while ($true) {
        $script:serverVersion = Get-HealthVersion $ServerHealth
        $script:workerVersion = Get-HealthVersion $WorkerHealth
        if ($script:serverVersion -ceq $Server -and $script:workerVersion -ceq $Worker) { return $true }
        if ([DateTime]::UtcNow -ge $deadline) { return $false }
        Start-Sleep -Seconds 3
    }
}

# The updater's liveness proof (internal/heartbeat ProveLooping): the supervisor writes Unix
# milliseconds to logs\supervisor-heartbeat every tick; a value at or after the restart must appear
# within the settle time and then advance within two ticks.
function Read-Heartbeat {
    try {
        $text = [IO.File]::ReadAllText((Join-Path (Join-Path $RigRoot 'logs') 'supervisor-heartbeat')).Trim()
        return [long]::Parse($text, [Globalization.CultureInfo]::InvariantCulture)
    } catch { return $null }
}
function Test-SupervisorLooping([long]$AfterMs) {
    $deadline = [DateTime]::UtcNow.AddSeconds($HeartbeatSettleSeconds)
    $first = $null
    while ($null -eq $first) {
        $beat = Read-Heartbeat
        if ($null -ne $beat -and $beat -ge $AfterMs) { $first = $beat; break }
        if ([DateTime]::UtcNow -ge $deadline) { return $false }
        Start-Sleep -Milliseconds 250
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(2 * $SupervisorIntervalSeconds + 2)
    while ([DateTime]::UtcNow -lt $deadline) {
        $beat = Read-Heartbeat
        if ($null -ne $beat -and $beat -gt $first) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return $false
}
function Start-Supervisor {
    $heartbeat = Join-Path (Join-Path $RigRoot 'logs') 'supervisor-heartbeat'
    if (Test-Path -LiteralPath $heartbeat) { Remove-Item -LiteralPath $heartbeat -Force }
    $at = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $script:taskRunning = $true
    Start-ScheduledTask -TaskName $SupervisorTask
    return $at
}

$serverBefore = $serverVersion
$workerBefore = $workerVersion
$guard = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
$swapped = @()
$archived = @()
$taskRunning = $false
$keepLock = $false
try {
    $lockBytes = [Text.Encoding]::UTF8.GetBytes("pid $PID started $([DateTime]::UtcNow.ToString('o'))")
    $guard.Write($lockBytes, 0, $lockBytes.Length)
    $guard.Flush()

    Write-Host "stopping supervisor task and the running set"
    Stop-RunningSet
    try {
        foreach ($row in $replace) {
            $live = Get-LivePath $row.Name
            $copy = Join-Path $previous $row.Name
            Copy-Item -LiteralPath $live -Destination $copy
            if ((Get-SHA256 $copy) -cne $Assets[$row.Name].Target) { throw "Backup of $($row.Name) does not verify." }
        }
        foreach ($path in $journals) {
            $entry = [pscustomobject]@{ Path = $path; Archive = (Join-Path $work (Split-Path -Leaf $path)); Sha = (Get-SHA256 $path) }
            Move-Item -LiteralPath $entry.Path -Destination $entry.Archive
            $archived += $entry
        }
        foreach ($row in $replace) {
            $live = Get-LivePath $row.Name
            $swapped += $row.Name
            Set-Executable (Join-Path $staged $row.Name) $live
            if ((Get-SHA256 $live) -cne $Assets[$row.Name].Source) { throw "Installed $($row.Name) does not verify as v$SourceVersion." }
            Write-Host "installed v$SourceVersion $($row.Name)"
        }
        Write-Host "starting supervisor task"
        $startedAt = Start-Supervisor
        if (-not (Wait-Health $SourceVersion $SourceVersion)) {
            throw "backend '$serverVersion' and worker '$workerVersion' did not both report $SourceVersion within $HealthTimeoutSeconds s"
        }
        if (-not (Test-SupervisorLooping $startedAt)) {
            throw "the v$SourceVersion supervisor did not prove it is looping (no advancing heartbeat after the restart)"
        }
        foreach ($name in $Assets.Keys) {
            if ((Get-SHA256 (Get-LivePath $name)) -cne $Assets[$name].Source) { throw "$name is not v$SourceVersion after the restore" }
        }
        if ((Get-SHA256 $updater) -cne $UpdaterSha) { throw "the live updater changed during the restore" }
        foreach ($name in @('update-transaction.json', 'update-transaction.json.tmp')) {
            if (Test-Path -LiteralPath (Join-Path $RigRoot $name)) { throw "$name exists after the restore" }
        }
    } catch {
        $failure = [string]$_
        Write-Host "restore failed ($failure); rolling back to v$TargetVersion and the original journal"
        try {
            if ($taskRunning) { Stop-RunningSet; $taskRunning = $false }
            foreach ($name in $swapped) { Set-Executable (Join-Path $previous $name) (Get-LivePath $name) }
            foreach ($name in $swapped) {
                if ((Get-SHA256 (Get-LivePath $name)) -cne $Assets[$name].Target) { throw "$name is not v$TargetVersion after the rollback" }
            }
            foreach ($entry in $archived) {
                if (Test-Path -LiteralPath $entry.Path) { throw "$($entry.Path) reappeared during the restore" }
                Move-Item -LiteralPath $entry.Archive -Destination $entry.Path
                if ((Get-SHA256 $entry.Path) -cne $entry.Sha) { throw "$($entry.Path) does not match the original after the rollback" }
            }
        } catch {
            $keepLock = $true
            throw "ROLLBACK DID NOT VERIFY: $_. This script will not start the supervisor task, and updater.lock is KEPT. Both executable sets and the original journal are in $work. Restore by hand from there before removing the lock. Cause of the failed restore: $failure"
        }
        Write-Host "rolled back: v$TargetVersion executables and the original journal are in place; starting supervisor task"
        $rolledBackAt = Start-Supervisor
        $healthBack = Wait-Health $serverBefore $workerBefore
        $loopingBack = $healthBack -and (Test-SupervisorLooping $rolledBackAt)
        $state = if (-not $healthBack) { ', NOT yet back to the versions before the restore' } elseif (-not $loopingBack) { ', supervisor NOT proven looping' } else { ', supervisor looping' }
        throw "Restore aborted and rolled back to v$TargetVersion with the original journal (backend '$serverVersion', worker '$workerVersion'$state). Downloads and copies are in $work. Cause: $failure"
    }
} finally {
    $guard.Dispose()
    if (-not $keepLock) {
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        if (-not $taskRunning) { Start-ScheduledTask -TaskName $SupervisorTask -ErrorAction SilentlyContinue }
    }
}

# ---------------------------------------------------------------- final state
Write-Host "backend_version=$serverVersion"
Write-Host "worker_version=$workerVersion"
Write-Host "updater_version=$TargetVersion"
Write-Host "journal_absent=true"
Write-Host "backup=$work"
Write-Host "Stage B source ready: signed v$SourceVersion appliance, signed v$TargetVersion updater."
