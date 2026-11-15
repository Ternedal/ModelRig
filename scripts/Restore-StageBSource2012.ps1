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
#   5. replaces the three executables, verifies their hashes, and puts the backup back if any step fails;
#   6. starts the supervisor task and waits until backend and worker report 2.0.12.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File Restore-StageBSource2012.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File Restore-StageBSource2012.ps1 -Apply
[CmdletBinding()]
param(
    [string]$RigRoot = 'C:\Rig\ModelRig',
    [switch]$Apply,
    [string]$SupervisorTask = 'KalivSupervisor',
    [int]$HealthTimeoutSeconds = 300
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
$ServerHealth = 'http://127.0.0.1:8080/healthz'
$WorkerHealth = 'http://127.0.0.1:8099/healthz'

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
    while ($true) {
        try { Copy-Item -LiteralPath $From -Destination $To -Force; return }
        catch {
            $cause = $_.Exception
            while ($cause.InnerException) { $cause = $cause.InnerException }
            $code = $cause.HResult -band 0xffff
            if ($code -notin @(32, 33) -or [DateTime]::UtcNow -ge $deadline) { throw }
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
    $path = Join-Path $RigRoot $name
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
$guard = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
$swapped = @()
$started = $false
try {
    $lockBytes = [Text.Encoding]::UTF8.GetBytes("pid $PID started $([DateTime]::UtcNow.ToString('o'))")
    $guard.Write($lockBytes, 0, $lockBytes.Length)
    $guard.Flush()

    Write-Host "stopping supervisor task and the running set"
    Stop-RunningSet
    try {
        foreach ($row in $replace) {
            $live = Join-Path $RigRoot $row.Name
            $copy = Join-Path $previous $row.Name
            Copy-Item -LiteralPath $live -Destination $copy
            if ((Get-SHA256 $copy) -cne $Assets[$row.Name].Target) { throw "Backup of $($row.Name) does not verify." }
        }
        foreach ($path in $journals) { Move-Item -LiteralPath $path -Destination (Join-Path $work (Split-Path -Leaf $path)) }
        foreach ($row in $replace) {
            $live = Join-Path $RigRoot $row.Name
            $swapped += $row.Name
            Set-Executable (Join-Path $staged $row.Name) $live
            if ((Get-SHA256 $live) -cne $Assets[$row.Name].Source) { throw "Installed $($row.Name) does not verify as v$SourceVersion." }
            Write-Host "installed v$SourceVersion $($row.Name)"
        }
    } catch {
        $failure = $_
        Write-Host "restore failed ($failure); putting the v$TargetVersion executables back"
        foreach ($name in $swapped) { Set-Executable (Join-Path $previous $name) (Join-Path $RigRoot $name) }
        foreach ($name in $swapped) {
            if ((Get-SHA256 (Join-Path $RigRoot $name)) -cne $Assets[$name].Target) { throw "ROLLBACK DID NOT VERIFY for $name. Backup is in $previous. Supervisor NOT started." }
        }
        Start-ScheduledTask -TaskName $SupervisorTask
        $started = $true
        throw "Restore aborted and rolled back to v$TargetVersion. Archived journals and backups are in $work. Cause: $failure"
    }

    $heartbeat = Join-Path (Join-Path $RigRoot 'logs') 'supervisor-heartbeat'
    if (Test-Path -LiteralPath $heartbeat) { Remove-Item -LiteralPath $heartbeat -Force }
    Write-Host "starting supervisor task"
    Start-ScheduledTask -TaskName $SupervisorTask
    $started = $true
    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    while ($true) {
        $serverVersion = Get-HealthVersion $ServerHealth
        $workerVersion = Get-HealthVersion $WorkerHealth
        if ($serverVersion -ceq $SourceVersion -and $workerVersion -ceq $SourceVersion) { break }
        if ([DateTime]::UtcNow -ge $deadline) {
            throw "Backend '$serverVersion' and worker '$workerVersion' did not both report $SourceVersion within $HealthTimeoutSeconds s. The v$TargetVersion executables are in $previous; the normal updater (-dir $RigRoot) moves the rig forward to the latest signed release."
        }
        Start-Sleep -Seconds 3
    }
} finally {
    $guard.Dispose()
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    if (-not $started) { Start-ScheduledTask -TaskName $SupervisorTask -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------------- final state
foreach ($name in $Assets.Keys) {
    if ((Get-SHA256 (Join-Path $RigRoot $name)) -cne $Assets[$name].Source) { throw "$name is not v$SourceVersion after the restore." }
}
if ((Get-SHA256 $updater) -cne $UpdaterSha) { throw "The live updater changed during the restore." }
foreach ($name in @('update-transaction.json', 'update-transaction.json.tmp')) {
    if (Test-Path -LiteralPath (Join-Path $RigRoot $name)) { throw "$name exists after the restore." }
}
Write-Host "backend_version=$serverVersion"
Write-Host "worker_version=$workerVersion"
Write-Host "updater_version=$TargetVersion"
Write-Host "journal_absent=true"
Write-Host "backup=$work"
Write-Host "Stage B source ready: signed v$SourceVersion appliance, signed v$TargetVersion updater."
