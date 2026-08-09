[CmdletBinding(DefaultParameterSetName = "Action")]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet(
        "PrepareOff",
        "Enable",
        "Grant",
        "Revoke",
        "Regrant",
        "RestartWorker",
        "RestartBackend",
        "Record",
        "Finalize",
        "Stop",
        "Status"
    )]
    [string]$Action,

    [string]$ExpectedSha,

    [string]$DeviceId,

    [ValidateSet(
        "default_off_feature_locked",
        "default_off_no_worker_fallback",
        "paired_without_grant_403",
        "paired_without_grant_locked_no_stale",
        "grant_same_token_200",
        "campaign_paging_no_loss",
        "timeline_paging_no_loss",
        "evidence_paging_no_loss",
        "detail_verification_matches",
        "no_write_controls",
        "stale_campaign_record_422",
        "stale_summary_422",
        "revoke_same_token_403",
        "revoke_clears_data",
        "restart_does_not_restore_grant",
        "regrant_same_token_200",
        "backend_restart_recovery",
        "worker_restart_recovery",
        "network_recovery",
        "malformed_schema_fail_closed",
        "not_found_fail_closed"
    )]
    [string]$Checkpoint,

    [ValidateSet("Pass", "Fail")]
    [string]$Result,

    [string]$Note,

    [ValidateSet("GO", "NO-GO")]
    [string]$Decision = "NO-GO"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot "validation\agent4-physical-runtime"
$statePath = Join-Path $runtimeDir "operator-state.json"
$observationsPath = Join-Path $runtimeDir "observations.json"
$fixtureRoot = Join-Path $runtimeDir "fixture-data"
$fixtureManifest = Join-Path $runtimeDir "fixture-manifest.json"
$pairingData = Join-Path $runtimeDir "modelrig-data.json"
$backendExe = Join-Path $runtimeDir "modelrig-server-a4-physical.exe"
$grantExe = Join-Path $runtimeDir "modelrig-agent4-grants-a4-physical.exe"
$backendCmd = Join-Path $runtimeDir "backend.cmd"
$workerCmd = Join-Path $runtimeDir "worker.cmd"
$backendLog = Join-Path $runtimeDir "backend.log"
$workerLog = Join-Path $runtimeDir "worker.log"
$adminKeyFile = Join-Path $runtimeDir "admin-key.txt"
$receiptPath = Join-Path $repoRoot "validation\agent4-physical-read-latest.json"
$firewallRule = "ModelRig Agent 4 physical read 8080"
$packageName = "dk.ternedal.modelrig"
$requiredCheckpoints = @(
    "default_off_feature_locked",
    "default_off_no_worker_fallback",
    "paired_without_grant_403",
    "paired_without_grant_locked_no_stale",
    "grant_same_token_200",
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "detail_verification_matches",
    "no_write_controls",
    "stale_campaign_record_422",
    "stale_summary_422",
    "revoke_same_token_403",
    "revoke_clears_data",
    "restart_does_not_restore_grant",
    "regrant_same_token_200",
    "backend_restart_recovery",
    "worker_restart_recovery",
    "network_recovery",
    "malformed_schema_fail_closed",
    "not_found_fail_closed"
)

function Assert-WindowsAdministrator {
    if ($env:OS -ne "Windows_NT") {
        throw "A4-18-operatoren må kun køres på Windows-riggen."
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Højreklik på launcheren og vælg 'Kør som administrator'."
    }
}

function Assert-Tool {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name blev ikke fundet på PATH."
    }
}

function Get-ExactHead {
    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($head)) {
        throw "Kunne ikke læse repository HEAD."
    }
    return $head
}

function Assert-ExactCleanHead {
    param([string]$RequiredSha)
    if ([string]::IsNullOrWhiteSpace($RequiredSha)) {
        throw "-ExpectedSha er påkrævet for denne handling."
    }
    if ($RequiredSha -notmatch "^[0-9a-f]{40}$") {
        throw "-ExpectedSha skal være en fuld lowercase Git SHA."
    }
    $head = Get-ExactHead
    if ($head -ne $RequiredSha) {
        throw "Forkert checkout. Forventede $RequiredSha, men HEAD er $head."
    }
    $dirty = @(& git -C $repoRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "Kunne ikke kontrollere working tree." }
    if ($dirty.Count -ne 0) {
        throw "Working tree er ikke ren. A4-18 må kun køres fra exact clean head."
    }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "A4-18 state mangler. Kør PrepareOff først."
    }
    return Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}

function Write-State {
    param([Parameter(Mandatory = $true)]$State)
    $State.updated_at = (Get-Date).ToUniversalTime().ToString("o")
    $State | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Get-ListenerPid {
    param([Parameter(Mandatory = $true)][int]$Port)
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return [int]$listener.OwningProcess
}

function Get-ProcessInfo {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Test-RecordedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][ValidateSet("backend", "worker")][string]$Kind
    )
    $process = Get-ProcessInfo -ProcessId $ProcessId
    if ($null -eq $process) { return $false }
    if ($Kind -eq "backend") {
        try {
            return (
                -not [string]::IsNullOrWhiteSpace([string]$process.ExecutablePath) -and
                [string]::Equals(
                    [IO.Path]::GetFullPath([string]$process.ExecutablePath),
                    [IO.Path]::GetFullPath($backendExe),
                    [StringComparison]::OrdinalIgnoreCase
                )
            )
        }
        catch { return $false }
    }
    $commandLine = [string]$process.CommandLine
    return (
        [string]$process.Name -ieq "python.exe" -and
        $commandLine -match "uvicorn\s+app\.entrypoint:app" -and
        $commandLine -match "--port\s+8099"
    )
}

function Remove-TestFirewall {
    Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Stop-RecordedStack {
    param([switch]$PreserveState)
    $cleanup = [ordered]@{
        backend_stopped = $false
        worker_stopped = $false
        unknown_process_preserved = $false
        firewall_removed = $false
    }
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            foreach ($entry in @(
                @{ Kind = "backend"; Port = 8080; ProcessId = [int]$state.backend_pid },
                @{ Kind = "worker"; Port = 8099; ProcessId = [int]$state.worker_pid }
            )) {
                if ($entry.ProcessId -le 0) { continue }
                $listenerPid = Get-ListenerPid -Port $entry.Port
                if (
                    $listenerPid -eq $entry.ProcessId -and
                    (Test-RecordedProcess -ProcessId $entry.ProcessId -Kind $entry.Kind)
                ) {
                    Stop-Process -Id $entry.ProcessId -Force -ErrorAction Stop
                    $cleanup["$($entry.Kind)_stopped"] = $true
                }
                elseif ($null -ne $listenerPid) {
                    $cleanup.unknown_process_preserved = $true
                }
            }
        }
        catch {
            Write-Warning "Recorded stack kunne ikke stoppes fuldt: $($_.Exception.Message)"
        }
    }
    Remove-TestFirewall
    $cleanup.firewall_removed = $true
    if (-not $PreserveState) {
        Remove-Item -LiteralPath $adminKeyFile -Force -ErrorAction SilentlyContinue
    }
    return [pscustomobject]$cleanup
}

function Assert-PortFree {
    param([Parameter(Mandatory = $true)][int]$Port, [string]$Label)
    $processId = Get-ListenerPid -Port $Port
    if ($null -eq $processId) { return }
    $process = Get-ProcessInfo -ProcessId $processId
    $name = if ($process) { [string]$process.Name } else { "ukendt proces" }
    throw "$Label kan ikke startes: port $Port bruges af $name (PID $processId)."
}

function Wait-Endpoint {
    param([Parameter(Mandatory = $true)][string]$Url, [int]$Seconds = 90)
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return }
        }
        catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Tjenesten blev ikke klar: $Url"
}

function Resolve-LanAddress {
    $defaultInterfaces = @(
        Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
            Where-Object { $_.NextHop -ne "0.0.0.0" } |
            Sort-Object RouteMetric |
            ForEach-Object { [int]$_.InterfaceIndex }
    )
    $candidates = foreach ($address in @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -notmatch "^(127\.|169\.254\.)" -and
                $_.AddressState -eq "Preferred"
            }
    )) {
        $ip = [string]$address.IPAddress
        $alias = [string]$address.InterfaceAlias
        $score = 0
        if ($ip -match "^10\." -or $ip -match "^192\.168\." -or $ip -match "^172\.(1[6-9]|2[0-9]|3[01])\.") {
            $score += 200
        }
        if ($defaultInterfaces -contains [int]$address.InterfaceIndex) { $score += 100 }
        if ($alias -notmatch "(?i)tailscale|vethernet|wsl|hyper-v|docker|loopback") { $score += 50 }
        [pscustomobject]@{ Address = $ip; Alias = $alias; Score = $score }
    }
    $selected = $candidates | Sort-Object Score -Descending | Select-Object -First 1
    if ($null -eq $selected) {
        throw "Kunne ikke finde riggens aktive LAN-IP."
    }
    return [string]$selected.Address
}

function Escape-CmdValue {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value -match '[\r\n"]') {
        throw "En runtime-værdi indeholder ugyldige tegn."
    }
    return $Value.Replace('%', '%%')
}

function New-AdminKey {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) }
    finally { $rng.Dispose() }
    $value = [Convert]::ToBase64String($bytes)
    [IO.File]::WriteAllText($adminKeyFile, $value, [Text.Encoding]::ASCII)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $adminKeyFile /inheritance:r /grant:r "${identity}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $adminKeyFile -Force -ErrorAction SilentlyContinue
        throw "Kunne ikke beskytte admin-key-filen med en brugerbundet ACL."
    }
}

function Get-AdminKey {
    if (-not (Test-Path -LiteralPath $adminKeyFile -PathType Leaf)) {
        throw "Admin-key-filen mangler. Kør PrepareOff igen."
    }
    $value = (Get-Content -LiteralPath $adminKeyFile -Raw).Trim()
    if ($value.Length -lt 32) { throw "Admin-key-filen er ugyldig." }
    return $value
}

function Write-CommandFiles {
    param([Parameter(Mandatory = $true)][ValidateSet("off", "enabled")][string]$Mode)
    $escapedRepo = Escape-CmdValue $repoRoot
    $escapedRuntime = Escape-CmdValue $runtimeDir
    $escapedFixture = Escape-CmdValue $fixtureRoot
    $escapedPairing = Escape-CmdValue $pairingData
    $escapedAdminKey = Escape-CmdValue (Get-AdminKey)
    $escapedBackendLog = Escape-CmdValue $backendLog
    $escapedWorkerLog = Escape-CmdValue $workerLog
    $operatorFlag = if ($Mode -eq "enabled") { "1" } else { "0" }
    $grantFlag = if ($Mode -eq "enabled") { "1" } else { "0" }
    $fixtureEnv = if ($Mode -eq "enabled") {
        "set `"KALIV_AGENT4_DATA_ROOT=$escapedFixture`""
    }
    else {
        "set `"KALIV_AGENT4_DATA_ROOT=`""
    }

    @"
@echo off
cd /d "$escapedRepo"
set "PYTHONPATH=$escapedRepo\worker"
set "PYTHONDONTWRITEBYTECODE=1"
set "KALIV_AGENT3_ENABLED=0"
set "KALIV_TOOLS_ENABLED=0"
set "KALIV_SCHEDULER=0"
set "KALIV_AGENT4_OPERATOR_API=$operatorFlag"
$fixtureEnv
python -u -m uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099 >> "$escapedWorkerLog" 2>&1
"@ | Set-Content -LiteralPath $workerCmd -Encoding ASCII

    @"
@echo off
cd /d "$escapedRuntime"
set "MODELRIG_HOST=0.0.0.0"
set "MODELRIG_PORT=8080"
set "MODELRIG_DATA=$escapedPairing"
set "MODELRIG_WORKER_URL=http://127.0.0.1:8099"
set "KALIV_AGENT4_OPERATOR_API=$operatorFlag"
set "KALIV_AGENT4_GRANT_ADMIN=$grantFlag"
set "MODELRIG_ADMIN_KEY=$escapedAdminKey"
"$backendExe" >> "$escapedBackendLog" 2>&1
"@ | Set-Content -LiteralPath $backendCmd -Encoding ASCII
}

function Start-Stack {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("off", "enabled")][string]$Mode,
        [Parameter(Mandatory = $true)]$State
    )
    Assert-PortFree -Port 8080 -Label "Backend"
    Assert-PortFree -Port 8099 -Label "Worker"
    Write-CommandFiles -Mode $Mode
    Remove-TestFirewall
    New-NetFirewallRule `
        -DisplayName $firewallRule `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 8080 `
        -RemoteAddress LocalSubnet `
        -Profile Any | Out-Null

    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $workerCmd + '"') -WorkingDirectory $repoRoot | Out-Null
    Wait-Endpoint -Url "http://127.0.0.1:8099/healthz"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $backendCmd + '"') -WorkingDirectory $runtimeDir | Out-Null
    Wait-Endpoint -Url "http://127.0.0.1:8080/healthz"

    $workerPid = Get-ListenerPid -Port 8099
    $backendPid = Get-ListenerPid -Port 8080
    if ($null -eq $workerPid -or -not (Test-RecordedProcess -ProcessId $workerPid -Kind "worker")) {
        throw "Port 8099 ejes ikke af den forventede A4-18-worker."
    }
    if ($null -eq $backendPid -or -not (Test-RecordedProcess -ProcessId $backendPid -Kind "backend")) {
        throw "Port 8080 ejes ikke af den forventede A4-18-backend."
    }
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/healthz" -TimeoutSec 10
    $State.mode = $Mode
    $State.backend_pid = [int]$backendPid
    $State.worker_pid = [int]$workerPid
    $State.backend_version = [string]$health.version
    $State.phase = if ($Mode -eq "off") { "default_off" } else { "enabled_no_grant" }
    Write-State -State $State
}

function Build-And-Install {
    Assert-Tool -Name "python"
    Assert-Tool -Name "go"
    Assert-Tool -Name "adb"
    $gradle = Join-Path $repoRoot "android\gradlew.bat"
    if (-not (Test-Path -LiteralPath $gradle -PathType Leaf)) {
        throw "Android Gradle-wrapperen mangler."
    }

    & python (Join-Path $PSScriptRoot "agent4-physical-fixture.py") `
        --data-root $fixtureRoot `
        --manifest $fixtureManifest `
        --replace
    if ($LASTEXITCODE -ne 0) { throw "Agent 4 fixture-generation fejlede." }

    Push-Location (Join-Path $repoRoot "backend")
    try {
        & go build -o $backendExe .\cmd\modelrig-server
        if ($LASTEXITCODE -ne 0) { throw "Backend-build fejlede." }
        & go build -o $grantExe .\cmd\modelrig-agent4-grants
        if ($LASTEXITCODE -ne 0) { throw "Grant CLI-build fejlede." }
    }
    finally { Pop-Location }

    Push-Location (Join-Path $repoRoot "android")
    try {
        & .\gradlew.bat :app:assembleDebug
        if ($LASTEXITCODE -ne 0) { throw "Android-build fejlede." }
    }
    finally { Pop-Location }

    $apk = Join-Path $repoRoot "android\app\build\outputs\apk\debug\app-debug.apk"
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw "Debug APK mangler." }
    $devices = @(
        & adb devices |
            Select-Object -Skip 1 |
            Where-Object { $_ -match "\tdevice$" }
    )
    if ($devices.Count -ne 1) {
        throw "Præcis én adb-enhed skal være tilsluttet; fandt $($devices.Count)."
    }
    & adb install -r $apk
    if ($LASTEXITCODE -ne 0) { throw "APK-installation på Pixel fejlede." }
    return $apk
}

function Initialize-Observations {
    $items = [ordered]@{}
    foreach ($name in $requiredCheckpoints) {
        $items[$name] = [ordered]@{
            status = "pending"
            observed_at = $null
            note = $null
        }
    }
    [ordered]@{
        schema = "modelrig-agent4/physical-read-observations/v1"
        expected_sha = Get-ExactHead
        checkpoints = $items
        production_activation = $false
    } | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $observationsPath -Encoding UTF8
}

function Resolve-DeviceId {
    param([string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return $Requested.Trim() }
    if (-not (Test-Path -LiteralPath $pairingData -PathType Leaf)) {
        throw "Pairing-store mangler."
    }
    $store = Get-Content -LiteralPath $pairingData -Raw | ConvertFrom-Json
    $devices = @($store.devices)
    if ($devices.Count -ne 1) {
        throw "Der skal være præcis én parret fysisk enhed; fandt $($devices.Count). Brug -DeviceId ved et bevidst valg."
    }
    return [string]$devices[0].id
}

function Set-ReadGrant {
    param([Parameter(Mandatory = $true)][bool]$Enabled, [string]$RequestedDeviceId)
    $state = Read-State
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    if ([string]$state.mode -ne "enabled") {
        throw "Grant kan kun ændres efter Enable."
    }
    $resolvedDevice = Resolve-DeviceId -Requested $RequestedDeviceId
    $adminKey = Get-AdminKey
    try {
        $env:MODELRIG_ADMIN_KEY = $adminKey
        if ($Enabled) {
            & $grantExe -grant $resolvedDevice -url "http://127.0.0.1:8080"
        }
        else {
            & $grantExe -revoke $resolvedDevice -url "http://127.0.0.1:8080"
        }
        if ($LASTEXITCODE -ne 0) { throw "Grant CLI afviste ændringen." }
    }
    finally {
        Remove-Item Env:MODELRIG_ADMIN_KEY -ErrorAction SilentlyContinue
    }
    $state.device_id = $resolvedDevice
    $state.phase = if ($Enabled) { "granted" } else { "revoked" }
    Write-State -State $state
}

function Restart-RecordedProcess {
    param([Parameter(Mandatory = $true)][ValidateSet("backend", "worker")][string]$Kind)
    $state = Read-State
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    $port = if ($Kind -eq "backend") { 8080 } else { 8099 }
    $recordedPid = if ($Kind -eq "backend") { [int]$state.backend_pid } else { [int]$state.worker_pid }
    $listenerPid = Get-ListenerPid -Port $port
    if ($listenerPid -ne $recordedPid -or -not (Test-RecordedProcess -ProcessId $recordedPid -Kind $Kind)) {
        throw "Den registrerede $Kind-proces ejer ikke længere port $port; ukendt proces stoppes ikke."
    }
    Stop-Process -Id $recordedPid -Force -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(20)
    while ($null -ne (Get-ListenerPid -Port $port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if ($null -ne (Get-ListenerPid -Port $port)) { throw "Port $port blev ikke frigivet." }
    $cmd = if ($Kind -eq "backend") { $backendCmd } else { $workerCmd }
    $work = if ($Kind -eq "backend") { $runtimeDir } else { $repoRoot }
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $cmd + '"') -WorkingDirectory $work | Out-Null
    Wait-Endpoint -Url "http://127.0.0.1:$port/healthz"
    $newPid = Get-ListenerPid -Port $port
    if ($null -eq $newPid -or -not (Test-RecordedProcess -ProcessId $newPid -Kind $Kind)) {
        throw "Den genstartede $Kind-proces kunne ikke verificeres."
    }
    if ($Kind -eq "backend") { $state.backend_pid = [int]$newPid }
    else { $state.worker_pid = [int]$newPid }
    Write-State -State $state
}

function Record-Checkpoint {
    if ([string]::IsNullOrWhiteSpace($Checkpoint) -or [string]::IsNullOrWhiteSpace($Result)) {
        throw "Record kræver både -Checkpoint og -Result Pass|Fail."
    }
    $state = Read-State
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    if (-not (Test-Path -LiteralPath $observationsPath -PathType Leaf)) {
        throw "Observationsfilen mangler."
    }
    $safeNote = if ([string]::IsNullOrWhiteSpace($Note)) { $null } else { $Note.Trim() }
    if ($null -ne $safeNote) {
        $adminKey = Get-AdminKey
        if (
            $safeNote.Contains($adminKey) -or
            $safeNote -match "(?i)authorization\s*:|bearer\s+[A-Za-z0-9+/=_-]+"
        ) {
            throw "Noten ligner credential-data og må ikke gemmes."
        }
    }
    $observations = Get-Content -LiteralPath $observationsPath -Raw | ConvertFrom-Json
    $entry = $observations.checkpoints.$Checkpoint
    $entry.status = $Result.ToLowerInvariant()
    $entry.observed_at = (Get-Date).ToUniversalTime().ToString("o")
    $entry.note = $safeNote
    $observations | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath $observationsPath -Encoding UTF8
}

function Get-FileReceipt {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = [IO.Path]::GetRelativePath($repoRoot, $item.FullName).Replace('\', '/')
        size_bytes = [int64]$item.Length
        sha256 = "sha256:$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
}

function Get-AdbProperty {
    param([string]$Name)
    try { return ((& adb shell getprop $Name) -join "").Trim() }
    catch { return $null }
}

function Finalize-Receipt {
    $state = Read-State
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    $observations = Get-Content -LiteralPath $observationsPath -Raw | ConvertFrom-Json
    $checkpointResults = [ordered]@{}
    $allPassed = $true
    foreach ($name in $requiredCheckpoints) {
        $entry = $observations.checkpoints.$name
        $checkpointResults[$name] = [ordered]@{
            status = [string]$entry.status
            observed_at = $entry.observed_at
            note = $entry.note
        }
        if ([string]$entry.status -ne "pass") { $allPassed = $false }
    }
    if ($Decision -eq "GO" -and -not $allPassed) {
        $Decision = "NO-GO"
    }

    $preCleanupFiles = @(
        Get-FileReceipt -Path $fixtureManifest
        Get-FileReceipt -Path $backendLog
        Get-FileReceipt -Path $workerLog
        Get-FileReceipt -Path $pairingData
    ) | Where-Object { $null -ne $_ }

    $cleanup = Stop-RecordedStack
    $portsFree = (
        $null -eq (Get-ListenerPid -Port 8080) -and
        $null -eq (Get-ListenerPid -Port 8099)
    )
    $cleanupPassed = (
        [bool]$cleanup.firewall_removed -and
        -not [bool]$cleanup.unknown_process_preserved -and
        $portsFree -and
        -not (Test-Path -LiteralPath $adminKeyFile -PathType Leaf)
    )
    if (-not $cleanupPassed) {
        $Decision = "NO-GO"
        $allPassed = $false
    }

    $appDump = @(& adb shell dumpsys package $packageName 2>$null)
    $versionName = ($appDump | Select-String -Pattern "versionName=" | Select-Object -First 1).Line
    $versionCode = ($appDump | Select-String -Pattern "versionCode=" | Select-Object -First 1).Line
    $receipt = [ordered]@{
        schema = "modelrig-agent4/physical-read-receipt/v1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        expected_sha = [string]$state.expected_sha
        observed_head = Get-ExactHead
        branch = [string]$state.branch
        backend_version = [string]$state.backend_version
        fixture = Get-Content -LiteralPath $fixtureManifest -Raw | ConvertFrom-Json
        pixel = [ordered]@{
            model = Get-AdbProperty -Name "ro.product.model"
            android_release = Get-AdbProperty -Name "ro.build.version.release"
            sdk = Get-AdbProperty -Name "ro.build.version.sdk"
            app_package = $packageName
            version_name_line = $versionName
            version_code_line = $versionCode
        }
        trials = $checkpointResults
        artifacts = $preCleanupFiles
        cleanup = [ordered]@{
            backend_stopped = [bool]$cleanup.backend_stopped
            worker_stopped = [bool]$cleanup.worker_stopped
            unknown_process_preserved = [bool]$cleanup.unknown_process_preserved
            firewall_removed = [bool]$cleanup.firewall_removed
            ports_free = $portsFree
            admin_key_deleted = -not (Test-Path -LiteralPath $adminKeyFile -PathType Leaf)
            passed = $cleanupPassed
        }
        all_required_observations_passed = $allPassed
        human_decision = $Decision
        credential_data_included = $false
        public_network = $false
        production_activation = $false
    }
    $withoutDigest = $receipt | ConvertTo-Json -Depth 20 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($withoutDigest)
    $sha = [Security.Cryptography.SHA256]::HashData($bytes)
    $receipt["receipt_sha256"] = "sha256:$([Convert]::ToHexString($sha).ToLowerInvariant())"
    $receipt | ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $receiptPath -Encoding UTF8

    $state.phase = "finalized"
    $state.backend_pid = 0
    $state.worker_pid = 0
    $state.human_decision = $Decision
    $state.receipt = $receiptPath
    Write-State -State $state

    Write-Host "A4-18 receipt: $receiptPath" -ForegroundColor Cyan
    Write-Host "Beslutning: $Decision" -ForegroundColor $(if ($Decision -eq "GO") { "Green" } else { "Yellow" })
    if ($Decision -ne "GO") {
        throw "A4-18 sluttede NO-GO. Se receipt og observationsfil."
    }
}

function Show-Status {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        Write-Host "A4-18 er ikke forberedt."
        return
    }
    $state = Read-State
    $summary = [ordered]@{
        expected_sha = [string]$state.expected_sha
        phase = [string]$state.phase
        mode = [string]$state.mode
        lan_url = [string]$state.lan_url
        backend_pid = [int]$state.backend_pid
        worker_pid = [int]$state.worker_pid
        device_id = $state.device_id
        receipt = $state.receipt
        production_activation = $false
    }
    $summary | ConvertTo-Json -Depth 6
}

Assert-WindowsAdministrator
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

switch ($Action) {
    "PrepareOff" {
        Assert-ExactCleanHead -RequiredSha $ExpectedSha
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            Stop-RecordedStack | Out-Null
        }
        Remove-Item -LiteralPath $runtimeDir -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        New-AdminKey
        $apk = Build-And-Install
        $lanAddress = Resolve-LanAddress
        $state = [pscustomobject][ordered]@{
            schema = "modelrig-agent4/physical-read-operator-state/v1"
            created_at = (Get-Date).ToUniversalTime().ToString("o")
            updated_at = (Get-Date).ToUniversalTime().ToString("o")
            expected_sha = $ExpectedSha
            branch = (& git -C $repoRoot branch --show-current).Trim()
            phase = "preparing"
            mode = "off"
            lan_url = "http://${lanAddress}:8080"
            pairing_code = $null
            pairing_expires_at = $null
            backend_pid = 0
            worker_pid = 0
            backend_version = $null
            device_id = $null
            apk = $apk
            receipt = $null
            human_decision = $null
            production_activation = $false
        }
        Write-State -State $state
        Initialize-Observations
        Start-Stack -Mode "off" -State $state
        $state = Read-State
        $pairing = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/start" -TimeoutSec 10
        $state.pairing_code = [string]$pairing.code
        $state.pairing_expires_at = [string]$pairing.expires_at
        Write-State -State $state
        Write-Host ""
        Write-Host "A4-18 DEFAULT-OFF STACK ER KLAR" -ForegroundColor Green
        Write-Host "Server-URL:   $($state.lan_url)" -ForegroundColor Cyan
        Write-Host "Parringskode: $($state.pairing_code)" -ForegroundColor Yellow
        Write-Host "Par Pixel, åbn Agent 4 og registrér de to default-off checkpoints."
    }
    "Enable" {
        $state = Read-State
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Stop-RecordedStack -PreserveState | Out-Null
        Start-Stack -Mode "enabled" -State $state
        Write-Host "Agent 4 er enabled, men enheden har stadig intet grant." -ForegroundColor Green
        Write-Host "Bekræft 403/locked-state og registrér checkpoints før Grant."
    }
    "Grant" {
        Set-ReadGrant -Enabled $true -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er tildelt lokalt. Test samme Pixel-token uden re-pairing." -ForegroundColor Green
    }
    "Revoke" {
        Set-ReadGrant -Enabled $false -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er fjernet. Næste Pixel-request skal være 403 og rydde data." -ForegroundColor Yellow
    }
    "Regrant" {
        Set-ReadGrant -Enabled $true -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er tildelt igen uden re-pairing." -ForegroundColor Green
    }
    "RestartWorker" {
        Restart-RecordedProcess -Kind "worker"
        Write-Host "Worker er genstartet og verificeret på loopback:8099." -ForegroundColor Green
    }
    "RestartBackend" {
        Restart-RecordedProcess -Kind "backend"
        Write-Host "Backend er genstartet og verificeret på port 8080." -ForegroundColor Green
    }
    "Record" {
        Record-Checkpoint
        Write-Host "Checkpoint $Checkpoint = $Result registreret." -ForegroundColor Green
    }
    "Finalize" {
        Finalize-Receipt
    }
    "Stop" {
        $cleanup = Stop-RecordedStack
        $cleanup | ConvertTo-Json -Depth 5
    }
    "Status" {
        Show-Status
    }
}
