$script:repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:runtimeDir = Join-Path $script:repoRoot "validation\agent4-physical-runtime"
$script:statePath = Join-Path $script:runtimeDir "operator-state.json"
$script:observationsPath = Join-Path $script:runtimeDir "observations.json"
$script:fixtureRoot = Join-Path $script:runtimeDir "fixture-data"
$script:fixtureManifest = Join-Path $script:runtimeDir "fixture-manifest.json"
$script:pairingData = Join-Path $script:runtimeDir "modelrig-data.json"
$script:backendExe = Join-Path $script:runtimeDir "modelrig-server-a4-physical.exe"
$script:grantExe = Join-Path $script:runtimeDir "modelrig-agent4-grants-a4-physical.exe"
$script:backendCmd = Join-Path $script:runtimeDir "backend.cmd"
$script:workerCmd = Join-Path $script:runtimeDir "worker.cmd"
$script:backendLog = Join-Path $script:runtimeDir "backend.log"
$script:workerLog = Join-Path $script:runtimeDir "worker.log"
$script:adminKeyFile = Join-Path $script:runtimeDir "admin-key.txt"
$script:receiptPath = Join-Path $script:repoRoot "validation\agent4-physical-read-latest.json"
$script:firewallRule = "ModelRig Agent 4 physical read 8080"
$script:packageName = "dk.ternedal.modelrig"

function Assert-WindowsAdministrator {
    if ($env:OS -ne "Windows_NT") {
        throw "A4-18-operatoren må kun køres på Windows-riggen."
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
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
    $head = (& git -C $script:repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($head)) {
        throw "Kunne ikke læse repository HEAD."
    }
    return $head
}

function Assert-ExactCleanHead {
    param([Parameter(Mandatory = $true)][string]$RequiredSha)
    if ($RequiredSha -notmatch "^[0-9a-f]{40}$") {
        throw "Expected SHA skal være en fuld lowercase Git SHA."
    }
    $head = Get-ExactHead
    if ($head -ne $RequiredSha) {
        throw "Forkert checkout. Forventede $RequiredSha, men HEAD er $head."
    }
    $dirty = @(& git -C $script:repoRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "Kunne ikke kontrollere working tree." }
    if ($dirty.Count -ne 0) {
        throw "Working tree er ikke ren. A4-18 må kun køres fra exact clean head."
    }
}

function Read-OperatorState {
    if (-not (Test-Path -LiteralPath $script:statePath -PathType Leaf)) {
        throw "A4-18 state mangler. Kør PrepareOff først."
    }
    return Get-Content -LiteralPath $script:statePath -Raw | ConvertFrom-Json
}

function Write-OperatorState {
    param([Parameter(Mandatory = $true)]$State)
    $State.updated_at = (Get-Date).ToUniversalTime().ToString("o")
    $State | ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $script:statePath -Encoding UTF8
}

function Get-Sha256HexForBytes {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $hash = $algorithm.ComputeHash($Bytes) }
    finally { $algorithm.Dispose() }
    return ([BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
}

function Get-RelativeRepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $root = [IO.Path]::GetFullPath($script:repoRoot).TrimEnd('\') + '\'
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Receipt-filen ligger uden for repository: $full"
    }
    return $full.Substring($root.Length).Replace('\', '/')
}

function Get-FileReceipt {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = Get-RelativeRepoPath -Path $item.FullName
        size_bytes = [int64]$item.Length
        sha256 = "sha256:$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
}

function Get-FirstMatchingLine {
    param([string[]]$Lines, [string]$Pattern)
    $match = $Lines | Select-String -Pattern $Pattern | Select-Object -First 1
    if ($null -eq $match) { return $null }
    return [string]$match.Line
}

function Get-AdbProperty {
    param([Parameter(Mandatory = $true)][string]$Name)
    try { return ((& adb shell getprop $Name) -join "").Trim() }
    catch { return $null }
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
    try { return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop }
    catch { return $null }
}

function Test-ExpectedProcess {
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
                    [IO.Path]::GetFullPath($script:backendExe),
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
        $commandLine -match "--host\s+127\.0\.0\.1" -and
        $commandLine -match "--port\s+8099"
    )
}

function Remove-TestFirewall {
    Get-NetFirewallRule -DisplayName $script:firewallRule -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Stop-ExpectedListener {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("backend", "worker")][string]$Kind,
        [Parameter(Mandatory = $true)][int]$RecordedPid,
        [Parameter(Mandatory = $true)][int]$Port
    )
    if ($RecordedPid -le 0) { return $false }
    $listenerPid = Get-ListenerPid -Port $Port
    if ($listenerPid -ne $RecordedPid) { return $false }
    if (-not (Test-ExpectedProcess -ProcessId $RecordedPid -Kind $Kind)) { return $false }
    Stop-Process -Id $RecordedPid -Force -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(20)
    while ($null -ne (Get-ListenerPid -Port $Port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if ($null -ne (Get-ListenerPid -Port $Port)) {
        throw "Port $Port blev ikke frigivet efter stop af $Kind."
    }
    return $true
}

function Stop-RecordedStack {
    param([switch]$PreserveAdminKey)
    $cleanup = [ordered]@{
        backend_stopped = $false
        worker_stopped = $false
        unknown_process_preserved = $false
        firewall_removed = $false
    }
    if (Test-Path -LiteralPath $script:statePath -PathType Leaf) {
        try {
            $state = Get-Content -LiteralPath $script:statePath -Raw | ConvertFrom-Json
            $cleanup.backend_stopped = Stop-ExpectedListener -Kind backend -RecordedPid ([int]$state.backend_pid) -Port 8080
            $cleanup.worker_stopped = Stop-ExpectedListener -Kind worker -RecordedPid ([int]$state.worker_pid) -Port 8099
            foreach ($port in @(8080, 8099)) {
                if ($null -ne (Get-ListenerPid -Port $port)) {
                    $cleanup.unknown_process_preserved = $true
                }
            }
        }
        catch {
            Write-Warning "Recorded stack kunne ikke stoppes fuldt: $($_.Exception.Message)"
            $cleanup.unknown_process_preserved = $true
        }
    }
    Remove-TestFirewall
    $cleanup.firewall_removed = $true
    if (-not $PreserveAdminKey) {
        Remove-Item -LiteralPath $script:adminKeyFile -Force -ErrorAction SilentlyContinue
    }
    return [pscustomobject]$cleanup
}

function Stop-CurrentExpectedListeners {
    foreach ($entry in @(
        @{ Kind = "backend"; Port = 8080 },
        @{ Kind = "worker"; Port = 8099 }
    )) {
        $pidValue = Get-ListenerPid -Port $entry.Port
        if ($null -ne $pidValue -and (Test-ExpectedProcess -ProcessId $pidValue -Kind $entry.Kind)) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-TestFirewall
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
            Where-Object { $_.IPAddress -notmatch "^(127\.|169\.254\.)" -and $_.AddressState -eq "Preferred" }
    )) {
        $ip = [string]$address.IPAddress
        $alias = [string]$address.InterfaceAlias
        $score = 0
        if ($ip -match "^10\." -or $ip -match "^192\.168\." -or $ip -match "^172\.(1[6-9]|2[0-9]|3[01])\.") { $score += 200 }
        if ($defaultInterfaces -contains [int]$address.InterfaceIndex) { $score += 100 }
        if ($alias -notmatch "(?i)tailscale|vethernet|wsl|hyper-v|docker|loopback") { $score += 50 }
        [pscustomobject]@{ Address = $ip; Alias = $alias; Score = $score }
    }
    $selected = $candidates | Sort-Object Score -Descending | Select-Object -First 1
    if ($null -eq $selected) { throw "Kunne ikke finde riggens aktive LAN-IP." }
    return [string]$selected.Address
}

function Escape-CmdValue {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value -match '[\r\n"]') { throw "En runtime-værdi indeholder ugyldige tegn." }
    return $Value.Replace('%', '%%')
}

function New-AdminKey {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) }
    finally { $rng.Dispose() }
    $value = [Convert]::ToBase64String($bytes)
    [IO.File]::WriteAllText($script:adminKeyFile, $value, [Text.Encoding]::ASCII)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $script:adminKeyFile /inheritance:r /grant:r "${identity}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $script:adminKeyFile -Force -ErrorAction SilentlyContinue
        throw "Kunne ikke beskytte admin-key-filen med en brugerbundet ACL."
    }
}

function Get-AdminKey {
    if (-not (Test-Path -LiteralPath $script:adminKeyFile -PathType Leaf)) {
        throw "Admin-key-filen mangler. Kør PrepareOff igen."
    }
    $value = (Get-Content -LiteralPath $script:adminKeyFile -Raw).Trim()
    if ($value.Length -lt 32) { throw "Admin-key-filen er ugyldig." }
    return $value
}

function Write-CommandFiles {
    param([Parameter(Mandatory = $true)][ValidateSet("off", "enabled")][string]$Mode)
    $escapedRepo = Escape-CmdValue $script:repoRoot
    $escapedRuntime = Escape-CmdValue $script:runtimeDir
    $escapedFixture = Escape-CmdValue $script:fixtureRoot
    $escapedPairing = Escape-CmdValue $script:pairingData
    $escapedKeyFile = Escape-CmdValue $script:adminKeyFile
    $escapedBackendLog = Escape-CmdValue $script:backendLog
    $escapedWorkerLog = Escape-CmdValue $script:workerLog
    $operatorFlag = if ($Mode -eq "enabled") { "1" } else { "0" }
    $grantFlag = if ($Mode -eq "enabled") { "1" } else { "0" }
    $fixtureEnv = if ($Mode -eq "enabled") {
        "set `"KALIV_AGENT4_DATA_ROOT=$escapedFixture`""
    }
    else { "set `"KALIV_AGENT4_DATA_ROOT=`"" }

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
"@ | Set-Content -LiteralPath $script:workerCmd -Encoding ASCII

    @"
@echo off
cd /d "$escapedRuntime"
set "MODELRIG_HOST=0.0.0.0"
set "MODELRIG_PORT=8080"
set "MODELRIG_DATA=$escapedPairing"
set "MODELRIG_WORKER_URL=http://127.0.0.1:8099"
set "KALIV_AGENT4_OPERATOR_API=$operatorFlag"
set "KALIV_AGENT4_GRANT_ADMIN=$grantFlag"
set "MODELRIG_ADMIN_KEY="
for /f "usebackq delims=" %%A in ("$escapedKeyFile") do set "MODELRIG_ADMIN_KEY=%%A"
if not defined MODELRIG_ADMIN_KEY exit /b 41
"$script:backendExe" >> "$escapedBackendLog" 2>&1
"@ | Set-Content -LiteralPath $script:backendCmd -Encoding ASCII
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
    New-NetFirewallRule -DisplayName $script:firewallRule -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080 -RemoteAddress LocalSubnet -Profile Any | Out-Null
    try {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $script:workerCmd + '"') -WorkingDirectory $script:repoRoot | Out-Null
        Wait-Endpoint -Url "http://127.0.0.1:8099/healthz"
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $script:backendCmd + '"') -WorkingDirectory $script:runtimeDir | Out-Null
        Wait-Endpoint -Url "http://127.0.0.1:8080/healthz"

        $workerPid = Get-ListenerPid -Port 8099
        $backendPid = Get-ListenerPid -Port 8080
        if ($null -eq $workerPid -or -not (Test-ExpectedProcess -ProcessId $workerPid -Kind worker)) {
            throw "Port 8099 ejes ikke af den forventede A4-18-worker."
        }
        if ($null -eq $backendPid -or -not (Test-ExpectedProcess -ProcessId $backendPid -Kind backend)) {
            throw "Port 8080 ejes ikke af den forventede A4-18-backend."
        }
        $backendHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8080/healthz" -TimeoutSec 10
        $workerHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8099/healthz" -TimeoutSec 10
        $State.mode = $Mode
        $State.backend_pid = [int]$backendPid
        $State.worker_pid = [int]$workerPid
        $State.backend_version = [string]$backendHealth.version
        $State.worker_version = [string]$workerHealth.version
        $State.phase = if ($Mode -eq "off") { "default_off" } else { "enabled_no_grant" }
        Write-OperatorState -State $State
    }
    catch {
        Stop-CurrentExpectedListeners
        throw
    }
}

function Build-And-InstallPhysicalArtifacts {
    Assert-Tool -Name python
    Assert-Tool -Name go
    Assert-Tool -Name adb
    $gradle = Join-Path $script:repoRoot "android\gradlew.bat"
    if (-not (Test-Path -LiteralPath $gradle -PathType Leaf)) {
        throw "Android Gradle-wrapperen mangler."
    }
    & python (Join-Path $PSScriptRoot "agent4-physical-fixture.py") --data-root $script:fixtureRoot --manifest $script:fixtureManifest --replace
    if ($LASTEXITCODE -ne 0) { throw "Agent 4 fixture-generation fejlede." }

    Push-Location (Join-Path $script:repoRoot "backend")
    try {
        & go build -o $script:backendExe .\cmd\modelrig-server
        if ($LASTEXITCODE -ne 0) { throw "Backend-build fejlede." }
        & go build -o $script:grantExe .\cmd\modelrig-agent4-grants
        if ($LASTEXITCODE -ne 0) { throw "Grant CLI-build fejlede." }
    }
    finally { Pop-Location }

    Push-Location (Join-Path $script:repoRoot "android")
    try {
        & .\gradlew.bat :app:assembleDebug
        if ($LASTEXITCODE -ne 0) { throw "Android-build fejlede." }
    }
    finally { Pop-Location }

    $apk = Join-Path $script:repoRoot "android\app\build\outputs\apk\debug\app-debug.apk"
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw "Debug APK mangler." }
    $devices = @(& adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "\tdevice$" })
    if ($devices.Count -ne 1) {
        throw "Præcis én adb-enhed skal være tilsluttet; fandt $($devices.Count)."
    }
    & adb install -r $apk
    if ($LASTEXITCODE -ne 0) { throw "APK-installation på Pixel fejlede." }
    return $apk
}

function Restart-ExpectedProcess {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("backend", "worker")][string]$Kind,
        [Parameter(Mandatory = $true)]$State
    )
    $port = if ($Kind -eq "backend") { 8080 } else { 8099 }
    $pidValue = if ($Kind -eq "backend") { [int]$State.backend_pid } else { [int]$State.worker_pid }
    if (-not (Stop-ExpectedListener -Kind $Kind -RecordedPid $pidValue -Port $port)) {
        throw "Den registrerede $Kind-proces kunne ikke stoppes sikkert."
    }
    $cmd = if ($Kind -eq "backend") { $script:backendCmd } else { $script:workerCmd }
    $work = if ($Kind -eq "backend") { $script:runtimeDir } else { $script:repoRoot }
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $cmd + '"') -WorkingDirectory $work | Out-Null
    Wait-Endpoint -Url "http://127.0.0.1:$port/healthz"
    $newPid = Get-ListenerPid -Port $port
    if ($null -eq $newPid -or -not (Test-ExpectedProcess -ProcessId $newPid -Kind $Kind)) {
        throw "Den genstartede $Kind-proces kunne ikke verificeres."
    }
    if ($Kind -eq "backend") { $State.backend_pid = [int]$newPid }
    else { $State.worker_pid = [int]$newPid }
    Write-OperatorState -State $State
}

function Invoke-PhysicalFixtureMutation {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("campaign-record", "summary")][string]$Mode,
        [Parameter(Mandatory = $true)]$State
    )
    if (-not (Stop-ExpectedListener -Kind worker -RecordedPid ([int]$State.worker_pid) -Port 8099)) {
        throw "Worker kunne ikke stoppes sikkert før fixture-mutation."
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $receipt = Join-Path $script:runtimeDir "mutation-$Mode-$stamp.json"
    try {
        & python (Join-Path $PSScriptRoot "agent4-physical-mutate-fixture.py") --data-root $script:fixtureRoot --mode $Mode --receipt $receipt
        if ($LASTEXITCODE -ne 0) { throw "Fixture-mutation fejlede." }
    }
    finally {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $script:workerCmd + '"') -WorkingDirectory $script:repoRoot | Out-Null
        Wait-Endpoint -Url "http://127.0.0.1:8099/healthz"
        $workerPid = Get-ListenerPid -Port 8099
        if ($null -eq $workerPid -or -not (Test-ExpectedProcess -ProcessId $workerPid -Kind worker)) {
            throw "Worker kunne ikke verificeres efter fixture-mutation."
        }
        $State.worker_pid = [int]$workerPid
    }
    $receipts = @($State.mutation_receipts)
    $State.mutation_receipts = @($receipts + $receipt)
    $State.last_mutation = $Mode
    Write-OperatorState -State $State
    return $receipt
}
