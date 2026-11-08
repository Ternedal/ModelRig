# Read-only diagnosis of the appliance updater, to run BEFORE Recover-UpdaterV2018.ps1.
#
# It changes nothing: no file is written, moved, renamed or deleted, no lock is taken, and no
# rig executable is started. It only hashes files, reads text files, lists processes and, unless
# -SkipHealth, sends GET requests to the local health endpoints.
#
# It answers: which release is each installed executable (by SHA-256 against the published
# SHA256SUMS), is the updater stranded (old executable, verified v2.0.18 .pending, updater.lock),
# who holds the lock, and is an updater, a replacement helper or an appliance transaction active.
# The Verdict says whether Recover-UpdaterV2018.ps1 applies; it never runs it.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Get-UpdaterState.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Get-UpdaterState.ps1 -RigRoot 'D:\Rig\ModelRig' -Json
[CmdletBinding()]
param(
    [string]$RigRoot = 'C:\Rig\ModelRig',
    [switch]$SkipHealth,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# SHA-256 of the published Windows executables, from each release's SHA256SUMS.txt.
$Known = @{
    'modelrig-updater-windows-x64.exe' = @{
        'c15c90c71f8d8dad9e04d987a00ea6c22dff75c109cb4fd0018df92d0a9165fe' = '2.0.12'
        'adf0179da4e55352ba3e4954a241d3ea8467c162d3472494e2ff10ba214ddf23' = '2.0.15'
        'b45bfd193e4c196bff997a2583cb13389f929407a110b41615e3cecd0f5f66c8' = '2.0.16'
        'c9447fde06b339e4162a1a3b0b08c994596b777d5fc15beecb2e60e9f20731bb' = '2.0.17'
        'a62716e195d5fb4a33f14f045a7e7217ec8d5797f12d1a7eb8bd0db092b41b2d' = '2.0.18'
    }
    'modelrig-server-windows-x64.exe' = @{
        '0af13cb40220f757cd7782d00a82de32e92f7faaf9510720f93ef04bf1415269' = '2.0.12'
        'fa737bebb1da108ee1d7daa7e1ae890a232225575dee02b5d91f314d34e5c987' = '2.0.15'
        '98a09f59929de863964143fc9468c1ffcd0ab90ff61320e88573905148cd2a7c' = '2.0.16'
        'f70f680592b22b9304ebeb99d950801d63b53a8b564e4ee949ff1d8f0114be8d' = '2.0.17'
        '025a38cf09eac0dbb9531f8ac9d89837a7915d3ea43bdee31df2b951957ef99a' = '2.0.18'
    }
    'modelrig-worker-windows-x64.exe' = @{
        '05148f125801b471ea504918cffbd76c6609342ccce39a3eb50d470c208a65b2' = '2.0.12'
        '52c81f1238f1c256d24df33b72e8ca57280fcf5bdc17d43fab22cdae882128d3' = '2.0.15'
        'db930db697a25afd0c693b63cb7c0d470d8520ee7238491df060770bfd0cb1d8' = '2.0.16'
        '9a7cfbaa2e69565e30fab387076d1e099d9d65173218e0cf677ce84a7f1ddea6' = '2.0.17'
        'd2504f971c8e2c5bae968bcacefa163d514cf796c0628df42d6544de8fd497d7' = '2.0.18'
    }
    'modelrig-supervisor-windows-x64.exe' = @{
        'f4007a07c9259902bf5dfdd711e1a772c94d47244597da62e91ac4f762cc2a70' = '2.0.12'
        '109136188216825db5436c080ce3b5dde0ed69cb9aa3e2fe696f77223c7e3ba7' = '2.0.15'
        '3d674483c86f88d58ba68c2172cf790d022f6d79334250e57b9a01607362b10c' = '2.0.16'
        '511e0b515f01e0d7d735f849641299ba35ea645d20c1d2643bbacde73fabb7bf' = '2.0.17'
        '7a9965b610878a8c557328daa6591864136d918fe29a22823b8d385fc76fdde1' = '2.0.18'
    }
}
$UpdaterName = 'modelrig-updater-windows-x64.exe'
$V2018Updater = 'a62716e195d5fb4a33f14f045a7e7217ec8d5797f12d1a7eb8bd0db092b41b2d'

function Get-Release([string]$Name, [string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return [pscustomobject]@{ Present = $false; Sha256 = $null; Release = $null } }
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $release = 'unknown'
    if ($Known.ContainsKey($Name) -and $Known[$Name].ContainsKey($hash)) { $release = $Known[$Name][$hash] }
    return [pscustomobject]@{ Present = $true; Sha256 = $hash; Release = $release }
}

$RigRoot = [IO.Path]::GetFullPath($RigRoot)
$state = [ordered]@{ RigRoot = $RigRoot; Executables = [ordered]@{}; Pending = $null; Lock = $null;
                     Transactions = @(); UpdaterProcesses = @(); HelperProcesses = @(); Health = [ordered]@{};
                     Verdict = $null; Advice = $null }

foreach ($name in $Known.Keys | Sort-Object) {
    $state.Executables[$name] = Get-Release $name (Join-Path $RigRoot $name)
}
$live = Join-Path $RigRoot $UpdaterName
$pendingPath = $live + '.pending'
$pending = Get-Release $UpdaterName $pendingPath
$state.Pending = $pending

$lockPath = Join-Path $RigRoot 'updater.lock'
if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
    $text = ([IO.File]::ReadAllText($lockPath)).Trim()
    $ownerId = $null; $ownerAlive = $null
    if ($text -match '^pid ([0-9]+) started \S+$') {
        $ownerId = [int]$Matches[1]
        $ownerAlive = [bool](Get-Process -Id $ownerId -ErrorAction SilentlyContinue)
    }
    $state.Lock = [pscustomobject]@{ Present = $true; Text = $text; OwnerPid = $ownerId; OwnerAlive = $ownerAlive }
} else {
    $state.Lock = [pscustomobject]@{ Present = $false; Text = $null; OwnerPid = $null; OwnerAlive = $null }
}

foreach ($name in @('update-transaction.json', 'update-transaction.json.tmp')) {
    $path = Join-Path $RigRoot $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $journalState = 'unreadable'
        try { $journalState = [string](([IO.File]::ReadAllText($path) | ConvertFrom-Json).state) } catch { }
        $state.Transactions += [pscustomobject]@{ File = $name; State = $journalState }
    }
}

# The same process view Recover-UpdaterV2018.ps1 uses.
foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='modelrig-updater-windows-x64.exe' OR Name='powershell.exe' OR Name='pwsh.exe'")) {
    if ($process.ProcessId -eq $PID) { continue }
    if ($process.Name -ieq $UpdaterName) { $state.UpdaterProcesses += [int]$process.ProcessId; continue }
    $command = [string]$process.CommandLine
    if ($command -match 'modelrig-updater-windows-x64\.exe' -and $command -match '\.pending' -and $command -match 'Wait-Process|Move-Item|\[IO\.File\]::Replace') {
        $state.HelperProcesses += [int]$process.ProcessId
    }
}

if (-not $SkipHealth) {
    foreach ($item in @(@{ Name = 'server'; Url = 'http://127.0.0.1:8080/healthz' }, @{ Name = 'worker'; Url = 'http://127.0.0.1:8099/healthz' })) {
        try {
            $reply = Invoke-RestMethod -Method Get -Uri $item.Url -TimeoutSec 3 -UseBasicParsing
            $version = $null
            if ($reply -and ($reply.PSObject.Properties.Name -contains 'version')) { $version = [string]$reply.version }
            $state.Health[$item.Name] = "up, version $version"
        } catch {
            $state.Health[$item.Name] = 'not reachable'
        }
    }
}

# The verdict mirrors Recover-UpdaterV2018.ps1's own refusals, in its order.
$updater = $state.Executables[$UpdaterName]
$open = @($state.Transactions | Where-Object { $_.State -notin @('committed', 'rolled_back') })
if ($state.UpdaterProcesses.Count -gt 0) {
    $state.Verdict = 'updater_running'; $state.Advice = 'An updater is running. Wait for it to finish; run this again.'
} elseif ($state.HelperProcesses.Count -gt 0) {
    $state.Verdict = 'helper_running'; $state.Advice = 'A replacement helper is running. Wait; run this again.'
} elseif ($open.Count -gt 0) {
    $state.Verdict = 'transaction_unfinished'; $state.Advice = 'An appliance transaction is unfinished. Do not run the recovery; report this output.'
} elseif (-not $updater.Present) {
    $state.Verdict = 'updater_missing'; $state.Advice = 'No installed updater at this RigRoot. Check -RigRoot.'
} elseif ($state.Lock.Present -and $null -eq $state.Lock.OwnerPid) {
    $state.Verdict = 'lock_unrecognized'; $state.Advice = 'updater.lock has unknown content. Do not run the recovery; report this output.'
} elseif ($state.Lock.Present -and $state.Lock.OwnerAlive) {
    $state.Verdict = 'lock_owner_alive'; $state.Advice = 'The lock owner is alive. Do not run the recovery; report this output.'
} elseif ($updater.Sha256 -ceq $V2018Updater) {
    if ($state.Lock.Present) {
        $state.Verdict = 'installed_v2018_stale_lock'; $state.Advice = 'Updater 2.0.18 is installed; a dead owner left updater.lock. The recovery would archive the lock, not replace anything.'
    } else {
        $state.Verdict = 'installed_v2018'; $state.Advice = 'Updater 2.0.18 is installed and not stranded. No recovery needed.'
    }
} elseif ($pending.Present -and $pending.Sha256 -ceq $V2018Updater) {
    $state.Verdict = 'stranded_v2018_pending'; $state.Advice = "Stranded: updater $($updater.Release) with the verified 2.0.18 .pending. Recover-UpdaterV2018.ps1 applies."
} elseif ($pending.Present) {
    $state.Verdict = 'pending_unknown'; $state.Advice = 'The .pending file is not the verified 2.0.18 updater. Do not run the recovery; report this output.'
} else {
    $state.Verdict = 'not_staged'; $state.Advice = "Updater $($updater.Release) with no .pending: no update was staged. The recovery does not apply."
}

if ($Json) {
    [pscustomobject]$state | ConvertTo-Json -Depth 5
} else {
    Write-Host "RigRoot: $RigRoot"
    foreach ($name in $state.Executables.Keys) {
        $e = $state.Executables[$name]
        if ($e.Present) { Write-Host ("  {0}: {1} ({2})" -f $name, $e.Release, $e.Sha256) } else { Write-Host ("  {0}: missing" -f $name) }
    }
    if ($pending.Present) { Write-Host ("  .pending: {0} ({1})" -f $pending.Release, $pending.Sha256) } else { Write-Host '  .pending: none' }
    if ($state.Lock.Present) { Write-Host ("  updater.lock: '{0}', owner alive: {1}" -f $state.Lock.Text, $state.Lock.OwnerAlive) } else { Write-Host '  updater.lock: none' }
    foreach ($t in $state.Transactions) { Write-Host ("  {0}: {1}" -f $t.File, $t.State) }
    Write-Host ("  updater processes: {0}; helper processes: {1}" -f $state.UpdaterProcesses.Count, $state.HelperProcesses.Count)
    foreach ($k in $state.Health.Keys) { Write-Host ("  health {0}: {1}" -f $k, $state.Health[$k]) }
    Write-Host "VERDICT: $($state.Verdict)"
    Write-Host $state.Advice
}
