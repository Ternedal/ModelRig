[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet(
        "PrepareOff", "Enable", "Grant", "Revoke", "Regrant",
        "RestartWorker", "RestartBackend", "MutateCampaignSnapshot",
        "MutateSummarySnapshot", "Record", "Status", "Finalize", "Stop"
    )]
    [string]$Action,
    [Parameter(Mandatory = $true)][string]$ExpectedSha,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$LanAddress,
    [string]$Serial,
    [string]$ApkPath,
    [switch]$Replace,
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
    [ValidateSet("Pass", "Fail")][string]$Result,
    [string]$Note,
    [int]$HttpStatus = -1,
    [string]$Route,
    [string]$RequestId,
    [string]$PayloadSha256,
    [string]$CursorSha256,
    [ValidateSet("GO", "NO-GO")][string]$Decision = "NO-GO"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packageName = "dk.ternedal.modelrig.a425f"
$backendPort = 18180
$workerPort = 18199
$firewallRule = "ModelRig A4-18R isolated physical read"
$virtualInterfacePattern = "(?i)tailscale|vethernet|wsl|hyper-v|docker|loopback|vmware|virtualbox|npcap"
$fixtureScript = Join-Path $PSScriptRoot "agent4_a4_18r_physical_fixture.py"
$mutateScript = Join-Path $PSScriptRoot "agent4_a4_18r_physical_mutate.py"

$requiredCheckpoints = @(
    "default_off_feature_locked", "default_off_no_worker_fallback",
    "paired_without_grant_403", "paired_without_grant_locked_no_stale",
    "grant_same_token_200", "campaign_paging_no_loss", "timeline_paging_no_loss",
    "evidence_paging_no_loss", "detail_verification_matches", "no_write_controls",
    "stale_campaign_record_422", "stale_summary_422", "revoke_same_token_403",
    "revoke_clears_data", "restart_does_not_restore_grant", "regrant_same_token_200",
    "backend_restart_recovery", "worker_restart_recovery", "network_recovery",
    "malformed_schema_fail_closed", "not_found_fail_closed"
)
$expectedHttpStatus = @{
    default_off_feature_locked = 404; paired_without_grant_403 = 403; grant_same_token_200 = 200;
    campaign_paging_no_loss = 200; timeline_paging_no_loss = 200; evidence_paging_no_loss = 200;
    detail_verification_matches = 200; stale_campaign_record_422 = 422; stale_summary_422 = 422;
    revoke_same_token_403 = 403; restart_does_not_restore_grant = 403; regrant_same_token_200 = 200;
    backend_restart_recovery = 200; worker_restart_recovery = 200; network_recovery = 200;
    malformed_schema_fail_closed = 200; not_found_fail_closed = 404
}
$checkpointPhases = @{
    default_off_feature_locked = @("default_off"); default_off_no_worker_fallback = @("default_off");
    paired_without_grant_403 = @("enabled_no_grant"); paired_without_grant_locked_no_stale = @("enabled_no_grant");
    grant_same_token_200 = @("granted"); campaign_paging_no_loss = @("granted");
    timeline_paging_no_loss = @("granted"); evidence_paging_no_loss = @("granted");
    detail_verification_matches = @("granted"); no_write_controls = @("granted");
    stale_campaign_record_422 = @("granted"); stale_summary_422 = @("granted");
    revoke_same_token_403 = @("revoked"); revoke_clears_data = @("revoked");
    restart_does_not_restore_grant = @("revoked"); regrant_same_token_200 = @("regranted");
    backend_restart_recovery = @("granted", "regranted"); worker_restart_recovery = @("granted", "regranted");
    network_recovery = @("granted", "regranted"); malformed_schema_fail_closed = @("granted", "regranted");
    not_found_fail_closed = @("granted", "regranted")
}

function Resolve-ExternalOutputRoot {
    if ([string]::IsNullOrWhiteSpace($OutputRoot)) { throw "A4-18R kræver -OutputRoot uden for repositoryet." }
    if ([IO.Path]::IsPathRooted($OutputRoot)) {
        $full = [IO.Path]::GetFullPath($OutputRoot)
    } else {
        $full = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutputRoot))
    }
    $repo = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\')
    $repoPrefix = $repo + '\'
    if ($full.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        [string]::Equals($full.TrimEnd('\'), $repo, [StringComparison]::OrdinalIgnoreCase)) {
        throw "A4-18R output må ikke ligge i repositoryet."
    }
    if ([string]::Equals($full, [IO.Path]::GetPathRoot($full), [StringComparison]::OrdinalIgnoreCase)) {
        throw "A4-18R output må ikke være filesystem-roden."
    }
    return $full.TrimEnd('\')
}

$output = Resolve-ExternalOutputRoot
$statePath = Join-Path $output "a4-18r-operator-state.json"
$observationsPath = Join-Path $output "a4-18r-observations.json"
$markerPath = Join-Path $output ".modelrig-a4-18r-output.json"
$fixtureData = Join-Path $output "fixture-data"
$fixtureManifest = Join-Path $output "fixture-manifest.json"
$pairingData = Join-Path $output "modelrig-data.json"
$adminKeyFile = Join-Path $output "admin-key.txt"
$binDir = Join-Path $output "bin"
$logsDir = Join-Path $output "logs"
$backendExe = Join-Path $binDir "modelrig-a4-18r-backend.exe"
$grantExe = Join-Path $binDir "modelrig-a4-18r-grants.exe"
$physicalApk = Join-Path $binDir "modelrig-a4-18r.apk"
$receiptPath = Join-Path $output "a4-18r-physical-read-receipt.json"

function Assert-WindowsAdministrator {
    if ($env:OS -ne "Windows_NT") { throw "A4-18R operatoren må kun køres på Windows-riggen." }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Kør PowerShell som administrator; A4-18R styrer en snæver firewallregel."
    }
}

function Assert-Tool {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "$Name blev ikke fundet på PATH." }
}

function Get-ExactHead {
    $value = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $value -notmatch "^[0-9a-f]{40}$") { throw "Kunne ikke læse repository HEAD." }
    return $value
}

function Assert-ExactCleanHead {
    if ($ExpectedSha -notmatch "^[0-9a-f]{40}$") { throw "ExpectedSha skal være 40 lowercase hex." }
    $head = Get-ExactHead
    if ($head -ne $ExpectedSha) { throw "Forkert checkout: forventede $ExpectedSha, fik $head." }
    $dirty = @(& git -C $repoRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "Kunne ikke kontrollere working tree." }
    if ($dirty.Count -ne 0) { throw "A4-18R kræver exact clean head; working tree er ikke ren." }
}

function Test-PrivateIPv4 {
    param([Parameter(Mandatory = $true)][string]$Address)
    $ip = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$ip) -or $null -eq $ip) { return $false }
    if ($ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { return $false }
    $b = $ip.GetAddressBytes()
    return ($b[0] -eq 10) -or ($b[0] -eq 192 -and $b[1] -eq 168) -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31)
}

function Assert-PrivateLocalLanAddress {
    param([Parameter(Mandatory = $true)][string]$Address)
    if (-not (Test-PrivateIPv4 -Address $Address)) { throw "LanAddress skal være én konkret RFC1918 IPv4-adresse." }
    $matches = @(
        Get-NetIPAddress -AddressFamily IPv4 -IPAddress $Address -ErrorAction SilentlyContinue |
            Where-Object { $_.AddressState -eq "Preferred" -and [string]$_.InterfaceAlias -notmatch $virtualInterfacePattern }
    )
    if ($matches.Count -ne 1) { throw "LanAddress skal være entydigt bundet til en aktiv ikke-virtuel interface." }
    $profile = Get-NetConnectionProfile -InterfaceIndex ([int]$matches[0].InterfaceIndex) -ErrorAction Stop | Select-Object -First 1
    if ($null -eq $profile -or [string]$profile.NetworkCategory -ne "Private") { throw "A4-18R kræver Windows-netværksprofil Private." }
}

function Get-Sha256Text {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)) } finally { $sha.Dispose() }
    return "sha256:$(([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant())"
}

function Invoke-Adb {
    param([Parameter(Mandatory = $true)][string]$DeviceSerial, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = @(& adb -s $DeviceSerial @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }
        })
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $saved }
    if ($code -ne 0) { throw "adb fejlede: $($lines -join ' ')" }
    return $lines
}

function Get-AdbValue {
    param([Parameter(Mandatory = $true)][string]$DeviceSerial, [Parameter(Mandatory = $true)][string]$Property)
    return ((Invoke-Adb -DeviceSerial $DeviceSerial shell getprop $Property) -join "").Trim()
}

function Resolve-PhysicalPixel {
    Assert-Tool -Name "adb"
    $devices = @(& adb devices | Where-Object { $_ -match "^\S+\s+device$" } | ForEach-Object { ($_ -split "\s+")[0] })
    if ($LASTEXITCODE -ne 0) { throw "adb devices fejlede." }
    $device = $null
    if (-not [string]::IsNullOrWhiteSpace($Serial)) {
        if ($devices -notcontains $Serial) { throw "ADB-enheden '$Serial' er ikke online som device." }
        $device = $Serial
    } elseif ($devices.Count -eq 1) {
        $device = [string]$devices[0]
    } else {
        throw "Der skal være præcis én online ADB-enhed, eller angiv -Serial; fandt $($devices.Count)."
    }
    if ($device -match "^emulator-") { throw "A4-18R accepterer ikke Android-emulator." }
    $kernelQemu = Get-AdbValue -DeviceSerial $device -Property "ro.kernel.qemu"
    $bootQemu = Get-AdbValue -DeviceSerial $device -Property "ro.boot.qemu"
    $manufacturer = Get-AdbValue -DeviceSerial $device -Property "ro.product.manufacturer"
    $model = Get-AdbValue -DeviceSerial $device -Property "ro.product.model"
    if ($kernelQemu -eq "1" -or $bootQemu -eq "1") { throw "A4-18R kræver fysisk hardware; QEMU blev fundet." }
    if ($manufacturer -ne "Google" -or $model -notmatch "^Pixel\b") { throw "A4-18R kræver en fysisk Google Pixel; fandt '$manufacturer $model'." }
    return [pscustomobject][ordered]@{
        serial = $device
        serial_sha256 = Get-Sha256Text -Value $device
        manufacturer = $manufacturer
        model = $model
        android_release = Get-AdbValue -DeviceSerial $device -Property "ro.build.version.release"
        sdk = Get-AdbValue -DeviceSerial $device -Property "ro.build.version.sdk"
    }
}

function Resolve-PixelPrivateIp {
    param([Parameter(Mandatory = $true)][string]$DeviceSerial, [Parameter(Mandatory = $true)][string]$TargetAddress)
    $route = (Invoke-Adb -DeviceSerial $DeviceSerial shell ip route get $TargetAddress) -join " "
    $match = [regex]::Match($route, "\bsrc\s+(\d+\.\d+\.\d+\.\d+)\b")
    if (-not $match.Success) { throw "Kunne ikke udlede Pixelens LAN-IP fra adb route." }
    $value = $match.Groups[1].Value
    if (-not (Test-PrivateIPv4 -Address $value)) { throw "Pixelens route-IP er ikke privat: $value" }
    return $value
}

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "A4-18R state mangler. Kør PrepareOff først." }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ([string]$state.expected_sha -ne $ExpectedSha) { throw "A4-18R state tilhører en anden exact SHA." }
    return $state
}

function Write-State {
    param([Parameter(Mandatory = $true)]$State)
    $State.updated_at = (Get-Date).ToUniversalTime().ToString("o")
    $State | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Read-Observations {
    if (-not (Test-Path -LiteralPath $observationsPath -PathType Leaf)) { throw "A4-18R observationsfil mangler." }
    return Get-Content -LiteralPath $observationsPath -Raw | ConvertFrom-Json
}

function Initialize-Observations {
    $items = [ordered]@{}
    foreach ($name in $requiredCheckpoints) {
        $items[$name] = [ordered]@{
            status = "pending"; observed_at = $null; note = $null; http_status = $null;
            route = $null; request_id = $null; payload_sha256 = $null; cursor_sha256 = $null
        }
    }
    [ordered]@{
        schema = "modelrig-agent4/a4-18r-observations/v1"
        repository_sha = $ExpectedSha
        checkpoints = $items
        public_network = $false
        production_activation = $false
    } | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $observationsPath -Encoding UTF8
}

function Assert-StatePhase {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string[]]$Allowed)
    if ($Allowed -notcontains [string]$State.phase) { throw "A4-18R handling er ikke tilladt i fase '$($State.phase)'; forventede $($Allowed -join ', ')." }
}

function Get-ListenerRows {
    param([Parameter(Mandatory = $true)][int]$Port)
    return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Sort-Object LocalAddress, OwningProcess)
}

function Assert-PortFree {
    param([Parameter(Mandatory = $true)][int]$Port, [Parameter(Mandatory = $true)][string]$Label)
    $rows = @(Get-ListenerRows -Port $Port)
    if ($rows.Count -gt 0) { throw "$Label kan ikke startes: port $Port har $($rows.Count) listener(e). Ukendte processer bevares." }
}

function Get-ProcessInfo {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-ExpectedProcess {
    param([Parameter(Mandatory = $true)][int]$ProcessId, [Parameter(Mandatory = $true)][ValidateSet("backend", "worker")][string]$Kind)
    $process = Get-ProcessInfo -ProcessId $ProcessId
    if ($null -eq $process) { return $false }
    if ($Kind -eq "backend") {
        try {
            return -not [string]::IsNullOrWhiteSpace([string]$process.ExecutablePath) -and [string]::Equals(
                [IO.Path]::GetFullPath([string]$process.ExecutablePath), [IO.Path]::GetFullPath($backendExe), [StringComparison]::OrdinalIgnoreCase)
        } catch { return $false }
    }
    $command = [string]$process.CommandLine
    return [string]$process.Name -ieq "python.exe" -and $command -match "uvicorn\s+app\.entrypoint:app" -and $command -match "--host\s+127\.0\.0\.1" -and $command -match "--port\s+$workerPort"
}

function Stop-RecordedProcess {
    param([int]$ProcessId, [ValidateSet("backend", "worker")][string]$Kind)
    if ($ProcessId -le 0) { return }
    $process = Get-ProcessInfo -ProcessId $ProcessId
    if ($null -eq $process) { return }
    if (-not (Test-ExpectedProcess -ProcessId $ProcessId -Kind $Kind)) { throw "Recorded $Kind PID tilhører ikke A4-18R; processen bevares." }
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(20)
    while ($null -ne (Get-ProcessInfo -ProcessId $ProcessId) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if ($null -ne (Get-ProcessInfo -ProcessId $ProcessId)) { throw "Recorded $Kind PID stoppede ikke." }
}

function Wait-Http200 {
    param([Parameter(Mandatory = $true)][string]$Url, [int]$Seconds = 60)
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Endpoint blev ikke klar: $Url"
}

function Remove-A4FirewallRule {
    Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Install-A4FirewallRule {
    param([Parameter(Mandatory = $true)][string]$Address, [Parameter(Mandatory = $true)][string]$PixelIp)
    Remove-A4FirewallRule
    New-NetFirewallRule -DisplayName $firewallRule -Direction Inbound -Action Allow -Program $backendExe `
        -Protocol TCP -LocalAddress $Address -LocalPort $backendPort -RemoteAddress $PixelIp -Profile Private | Out-Null
}

function New-EphemeralAdminKey {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Write-ProtectedAdminKey {
    param([Parameter(Mandatory = $true)][string]$Value)
    [IO.File]::WriteAllText($adminKeyFile, $Value, [Text.Encoding]::ASCII)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $adminKeyFile /inheritance:r /grant:r "${identity}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $adminKeyFile -Force -ErrorAction SilentlyContinue
        throw "Kunne ikke beskytte A4-18R admin-key-filen."
    }
}

function Get-AdminKey {
    if (-not (Test-Path -LiteralPath $adminKeyFile -PathType Leaf)) { throw "A4-18R admin-key mangler; start forfra." }
    $value = (Get-Content -LiteralPath $adminKeyFile -Raw).Trim()
    if ($value.Length -lt 64) { throw "A4-18R admin-key er ugyldig." }
    return $value
}

function Invoke-WithEnvironment {
    param([Parameter(Mandatory = $true)][hashtable]$Values, [Parameter(Mandatory = $true)][scriptblock]$Operation)
    $saved = @{}
    foreach ($name in $Values.Keys) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, [string]$Values[$name], "Process")
    }
    try { & $Operation } finally {
        foreach ($name in $Values.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process") }
    }
}

function Start-Worker {
    param([Parameter(Mandatory = $true)][ValidateSet("off", "enabled")][string]$Mode)
    Assert-PortFree -Port $workerPort -Label "A4-18R worker"
    $python = (Get-Command python -ErrorAction Stop).Source
    $operatorFlag = if ($Mode -eq "enabled") { "1" } else { "0" }
    $dataRoot = if ($Mode -eq "enabled") { $fixtureData } else { "" }
    $stdout = Join-Path $logsDir "worker.stdout.log"
    $stderr = Join-Path $logsDir "worker.stderr.log"
    Invoke-WithEnvironment -Values @{
        PYTHONPATH = (Join-Path $repoRoot "worker")
        PYTHONDONTWRITEBYTECODE = "1"
        KALIV_AGENT3_ENABLED = "0"
        KALIV_TOOLS_ENABLED = "0"
        KALIV_SCHEDULER = "0"
        KALIV_AGENT4_OPERATOR_API = $operatorFlag
        KALIV_AGENT4_DATA_ROOT = $dataRoot
    } -Operation {
        Start-Process -FilePath $python -ArgumentList @("-u", "-m", "uvicorn", "app.entrypoint:app", "--host", "127.0.0.1", "--port", "$workerPort") `
            -WorkingDirectory (Join-Path $repoRoot "worker") -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
    }
    Wait-Http200 -Url "http://127.0.0.1:$workerPort/healthz"
    $rows = @(Get-ListenerRows -Port $workerPort)
    if ($rows.Count -ne 1 -or [string]$rows[0].LocalAddress -ne "127.0.0.1" -or -not (Test-ExpectedProcess -ProcessId ([int]$rows[0].OwningProcess) -Kind worker)) {
        throw "A4-18R worker er ikke en entydig loopback-listener."
    }
    return [int]$rows[0].OwningProcess
}

function Start-Backend {
    param(
        [Parameter(Mandatory = $true)][string]$HostAddress,
        [Parameter(Mandatory = $true)][bool]$OperatorEnabled,
        [Parameter(Mandatory = $true)][bool]$GrantAdmin,
        [Parameter(Mandatory = $true)][string]$LogLabel
    )
    Assert-PortFree -Port $backendPort -Label "A4-18R backend"
    $stdout = Join-Path $logsDir "$LogLabel.stdout.log"
    $stderr = Join-Path $logsDir "$LogLabel.stderr.log"
    $key = Get-AdminKey
    Invoke-WithEnvironment -Values @{
        MODELRIG_HOST = $HostAddress
        MODELRIG_PORT = "$backendPort"
        MODELRIG_DATA = $pairingData
        MODELRIG_WORKER_URL = "http://127.0.0.1:$workerPort"
        MODELRIG_ADMIN_KEY = $key
        KALIV_AGENT4_OPERATOR_API = $(if ($OperatorEnabled) { "1" } else { "0" })
        KALIV_AGENT4_GRANT_ADMIN = $(if ($GrantAdmin) { "1" } else { "0" })
    } -Operation {
        Start-Process -FilePath $backendExe -WorkingDirectory $output -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
    }
    Wait-Http200 -Url "http://${HostAddress}:$backendPort/healthz"
    $rows = @(Get-ListenerRows -Port $backendPort)
    if ($rows.Count -ne 1 -or [string]$rows[0].LocalAddress -ne $HostAddress -or -not (Test-ExpectedProcess -ProcessId ([int]$rows[0].OwningProcess) -Kind backend)) {
        throw "A4-18R backend er ikke entydigt bundet til $HostAddress."
    }
    return [int]$rows[0].OwningProcess
}

function Build-PhysicalArtifacts {
    Assert-Tool -Name "python"; Assert-Tool -Name "go"; Assert-Tool -Name "adb"
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    Push-Location (Join-Path $repoRoot "backend")
    try {
        & go build -o $backendExe .\cmd\modelrig-server
        if ($LASTEXITCODE -ne 0) { throw "A4-18R backend build fejlede." }
        & go build -o $grantExe .\cmd\modelrig-agent4-grants
        if ($LASTEXITCODE -ne 0) { throw "A4-18R grant CLI build fejlede." }
    } finally { Pop-Location }

    if (-not [string]::IsNullOrWhiteSpace($ApkPath)) {
        $source = (Resolve-Path -LiteralPath $ApkPath -ErrorAction Stop).Path
        if ([IO.Path]::GetExtension($source) -ine ".apk") { throw "-ApkPath skal være en APK." }
        Copy-Item -LiteralPath $source -Destination $physicalApk -Force
    } else {
        Push-Location (Join-Path $repoRoot "android")
        try {
            & .\gradlew.bat :app:assembleA425f --no-daemon --console=plain
            if ($LASTEXITCODE -ne 0) { throw "A4-18R A425f APK build fejlede." }
        } finally { Pop-Location }
        $apks = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "android\app\build\outputs\apk\a425f") -Filter "*.apk" -File -ErrorAction Stop)
        if ($apks.Count -ne 1) { throw "Forventede præcis én A425f APK; fandt $($apks.Count)." }
        Copy-Item -LiteralPath $apks[0].FullName -Destination $physicalApk -Force
    }
    return $physicalApk
}

function Invoke-FixtureBuild {
    & python $fixtureScript --output-root $output --data-root $fixtureData --manifest $fixtureManifest --expected-sha $ExpectedSha --replace
    if ($LASTEXITCODE -ne 0) { throw "A4-18R fixture-generation fejlede." }
}

function Install-PhysicalApp {
    param([Parameter(Mandatory = $true)][string]$DeviceSerial)
    Invoke-Adb -DeviceSerial $DeviceSerial install -r $physicalApk | Out-Null
}

function Start-LanStack {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][ValidateSet("off", "enabled")][string]$Mode)
    $State.worker_pid = Start-Worker -Mode $Mode
    try {
        $State.backend_pid = Start-Backend -HostAddress ([string]$State.lan_address) -OperatorEnabled:($Mode -eq "enabled") -GrantAdmin:$false -LogLabel "backend-lan"
    } catch {
        Stop-RecordedProcess -ProcessId ([int]$State.worker_pid) -Kind worker
        $State.worker_pid = 0
        throw
    }
    $State.mode = $Mode
    $State.phase = if ($Mode -eq "off") { "default_off" } else { "enabled_no_grant" }
    Write-State -State $State
}

function Stop-StackProcesses {
    param([Parameter(Mandatory = $true)]$State)
    Stop-RecordedProcess -ProcessId ([int]$State.backend_pid) -Kind backend
    Stop-RecordedProcess -ProcessId ([int]$State.worker_pid) -Kind worker
    $State.backend_pid = 0; $State.worker_pid = 0
    Write-State -State $State
}

function Resolve-SingleDeviceId {
    if (-not (Test-Path -LiteralPath $pairingData -PathType Leaf)) { throw "A4-18R pairing/device store mangler." }
    $store = Get-Content -LiteralPath $pairingData -Raw | ConvertFrom-Json
    $devices = @($store.devices)
    if ($devices.Count -ne 1) { throw "A4-18R kræver præcis én parret test-enhed; fandt $($devices.Count)." }
    $id = [string]$devices[0].id
    if ([string]::IsNullOrWhiteSpace($id)) { throw "Parret test-enhed mangler id." }
    return $id
}

function Assert-CheckpointsPassed {
    param([Parameter(Mandatory = $true)][string[]]$Names)
    $observations = Read-Observations
    $missing = @($Names | Where-Object { [string]$observations.checkpoints.$_.status -ne "pass" })
    if ($missing.Count -gt 0) { throw "Fasen er låst. Mangler pass: $($missing -join ', ')." }
}

function Invoke-GrantTransition {
    param([Parameter(Mandatory = $true)][ValidateSet("grant", "revoke")][string]$Transition, [Parameter(Mandatory = $true)]$State)
    $deviceId = Resolve-SingleDeviceId
    Stop-RecordedProcess -ProcessId ([int]$State.backend_pid) -Kind backend
    $State.backend_pid = 0; Write-State -State $State
    $adminPid = 0
    try {
        $adminPid = Start-Backend -HostAddress "127.0.0.1" -OperatorEnabled:$true -GrantAdmin:$true -LogLabel "backend-admin-loopback"
        $key = Get-AdminKey
        $saved = [Environment]::GetEnvironmentVariable("MODELRIG_ADMIN_KEY", "Process")
        try {
            [Environment]::SetEnvironmentVariable("MODELRIG_ADMIN_KEY", $key, "Process")
            if ($Transition -eq "grant") { & $grantExe -grant $deviceId -url "http://127.0.0.1:$backendPort" }
            else { & $grantExe -revoke $deviceId -url "http://127.0.0.1:$backendPort" }
            if ($LASTEXITCODE -ne 0) { throw "A4-18R grant CLI afviste $Transition." }
        } finally { [Environment]::SetEnvironmentVariable("MODELRIG_ADMIN_KEY", $saved, "Process") }
    } finally {
        if ($adminPid -gt 0) { Stop-RecordedProcess -ProcessId $adminPid -Kind backend }
    }
    $State.backend_pid = Start-Backend -HostAddress ([string]$State.lan_address) -OperatorEnabled:$true -GrantAdmin:$false -LogLabel "backend-lan"
    $State.device_id = $deviceId
    Write-State -State $State
}

function Invoke-Mutation {
    param([Parameter(Mandatory = $true)][ValidateSet("campaign-record", "summary")][string]$Mode, [Parameter(Mandatory = $true)]$State)
    Stop-RecordedProcess -ProcessId ([int]$State.worker_pid) -Kind worker
    $State.worker_pid = 0; Write-State -State $State
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $receipt = Join-Path $output "mutation-$Mode-$stamp.json"
    try {
        & python $mutateScript --output-root $output --data-root $fixtureData --fixture-manifest $fixtureManifest --mode $Mode --receipt $receipt --expected-sha $ExpectedSha
        if ($LASTEXITCODE -ne 0) { throw "A4-18R fixture-mutation fejlede." }
        $State.mutation_receipts = @($State.mutation_receipts) + @($receipt)
        $State.last_mutation = $Mode
    } finally {
        $State.worker_pid = Start-Worker -Mode enabled
        Write-State -State $State
    }
}

function Record-Checkpoint {
    param([Parameter(Mandatory = $true)]$State)
    if ([string]::IsNullOrWhiteSpace($Checkpoint) -or [string]::IsNullOrWhiteSpace($Result)) { throw "Record kræver -Checkpoint og -Result." }
    $allowed = @($checkpointPhases[$Checkpoint])
    if ($allowed -notcontains [string]$State.phase) { throw "Checkpoint $Checkpoint er ikke tilladt i fase '$($State.phase)'." }
    if ($Checkpoint -eq "stale_campaign_record_422" -and [string]$State.last_mutation -ne "campaign-record") { throw "Campaign stale-check kræver MutateCampaignSnapshot først." }
    if ($Checkpoint -eq "stale_summary_422" -and [string]$State.last_mutation -ne "summary") { throw "Summary stale-check kræver MutateSummarySnapshot først." }
    $providedHttp = $PSBoundParameters.ContainsKey("HttpStatus") -or $HttpStatus -ge 0
    if ($Result -eq "Pass" -and $expectedHttpStatus.ContainsKey($Checkpoint)) {
        $expected = [int]$expectedHttpStatus[$Checkpoint]
        if (-not $providedHttp -or $HttpStatus -ne $expected) { throw "Checkpoint $Checkpoint kræver HTTP $expected for Pass." }
    }
    if ($providedHttp -and ([string]::IsNullOrWhiteSpace($Route) -or $Route -notmatch "^/api/" -or $Route -match "[?#]" -or $Route -match "://")) {
        throw "HTTP-observationer kræver en redigeret relativ /api/-route uden query/fragment."
    }
    if (-not [string]::IsNullOrWhiteSpace($RequestId) -and $RequestId -notmatch "^[A-Za-z0-9._:-]{1,200}$") { throw "RequestId indeholder ugyldige tegn." }
    foreach ($pair in @(@($PayloadSha256, "PayloadSha256"), @($CursorSha256, "CursorSha256"))) {
        if (-not [string]::IsNullOrWhiteSpace([string]$pair[0]) -and [string]$pair[0] -notmatch "^sha256:[0-9a-f]{64}$") { throw "$($pair[1]) skal være sha256:<64 lowercase hex>." }
    }
    if (-not [string]::IsNullOrWhiteSpace($Note) -and ($Note -match "(?i)authorization\s*:|bearer\s+|pairing[_ -]?code\s*[:=]|device[_ -]?token\s*[:=]|admin[_ -]?key\s*[:=]|\b[A-Z0-9]{4}-[A-Z0-9]{4}\b|\b[0-9a-f]{64}\b")) {
        throw "Noten ligner credential-data og må ikke gemmes."
    }
    $observations = Read-Observations
    $entry = $observations.checkpoints.$Checkpoint
    $entry.status = $Result.ToLowerInvariant()
    $entry.observed_at = (Get-Date).ToUniversalTime().ToString("o")
    $entry.note = if ([string]::IsNullOrWhiteSpace($Note)) { $null } else { $Note.Trim() }
    $entry.http_status = if ($providedHttp) { $HttpStatus } else { $null }
    $entry.route = if ([string]::IsNullOrWhiteSpace($Route)) { $null } else { $Route.Trim() }
    $entry.request_id = if ([string]::IsNullOrWhiteSpace($RequestId)) { $null } else { $RequestId.Trim() }
    $entry.payload_sha256 = if ([string]::IsNullOrWhiteSpace($PayloadSha256)) { $null } else { $PayloadSha256 }
    $entry.cursor_sha256 = if ([string]::IsNullOrWhiteSpace($CursorSha256)) { $null } else { $CursorSha256 }
    $observations | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $observationsPath -Encoding UTF8
}

function Get-RelativeChildPath {
    param([Parameter(Mandatory = $true)][string]$RootPath, [Parameter(Mandatory = $true)][string]$Path)
    $rootFull = [IO.Path]::GetFullPath($RootPath).TrimEnd('\') + '\'
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) { throw "Artifact ligger uden for sin authority-root: $full" }
    return $full.Substring($rootFull.Length).Replace('\', '/')
}

function Get-FileReceipt {
    param([Parameter(Mandatory = $true)][ValidateSet("output", "repository")][string]$Scope, [Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Artifact mangler: $Path" }
    $base = if ($Scope -eq "output") { $output } else { $repoRoot }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        schema = "modelrig-file-receipt/v1"
        scope = $Scope
        path = Get-RelativeChildPath -RootPath $base -Path $item.FullName
        size_bytes = [int64]$item.Length
        sha256 = "sha256:$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
}

function Get-ArtifactReceipts {
    param([Parameter(Mandatory = $true)]$State)
    $repoPaths = @(
        "backend\internal\httpapi\agent4_operator.go",
        "backend\internal\httpapi\agent4_grants_admin.go",
        "worker\app\entrypoint.py",
        "worker\app\agent4\production_bootstrap.py",
        "worker\app\agent4\operator_api.py",
        "worker\app\agent4\campaign_list_query.py",
        "android\app\src\main\java\dk\ternedal\modelrig\net\Agent4OperatorClient.kt",
        "android\app\src\main\java\dk\ternedal\modelrig\ui\Agent4OperatorScreen.kt",
        "android\app\src\main\java\dk\ternedal\modelrig\ui\Agent4CampaignDetailScreen.kt",
        "android\app\build.gradle.kts"
    ) | ForEach-Object { Join-Path $repoRoot $_ }
    $outputPaths = @($backendExe, $grantExe, $physicalApk, $fixtureManifest) + @($State.mutation_receipts)
    $result = @()
    foreach ($path in $repoPaths) { $result += Get-FileReceipt -Scope repository -Path $path }
    foreach ($path in $outputPaths) { $result += Get-FileReceipt -Scope output -Path ([string]$path) }
    return $result
}

function Stop-Harness {
    param([Parameter(Mandatory = $true)]$State, [switch]$Uninstall)
    $unknown = $false
    try { Stop-RecordedProcess -ProcessId ([int]$State.backend_pid) -Kind backend } catch { $unknown = $true; throw }
    try { Stop-RecordedProcess -ProcessId ([int]$State.worker_pid) -Kind worker } catch { $unknown = $true; throw }
    $State.backend_pid = 0; $State.worker_pid = 0
    Remove-A4FirewallRule
    if ($Uninstall) {
        try { Invoke-Adb -DeviceSerial ([string]$State.adb_serial) uninstall $packageName | Out-Null } catch { throw "Kunne ikke afinstallere isoleret A4-18R testpakke." }
    }
    Remove-Item -LiteralPath $adminKeyFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pairingData -Force -ErrorAction SilentlyContinue
    $State.phase = "stopped"
    Write-State -State $State
    return [pscustomobject][ordered]@{
        backend_stopped = $null -eq (Get-ProcessInfo -ProcessId ([int]$State.backend_pid)
        worker_stopped = $null -eq (Get-ProcessInfo -ProcessId ([int]$State.worker_pid)
        firewall_removed = $null -eq (Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue)
        ports_free = @(Get-ListenerRows -Port $backendPort).Count -eq 0 -and @(Get-ListenerRows -Port $workerPort).Count -eq 0
        credential_file_deleted = -not (Test-Path -LiteralPath $adminKeyFile -PathType Leaf)
        pairing_store_deleted = -not (Test-Path -LiteralPath $pairingData -PathType Leaf)
        test_package_uninstalled = $Uninstall.IsPresent
        unknown_process_preserved = $unknown
    }
}

function Write-FinalReceipt {
    param([Parameter(Mandatory = $true)]$State)
    Assert-StatePhase -State $State -Allowed @("regranted")
    $observations = Read-Observations
    $trials = [ordered]@{}
    $allPassed = $true
    foreach ($name in $requiredCheckpoints) {
        $entry = $observations.checkpoints.$name
        $trials[$name] = [ordered]@{
            status = [string]$entry.status; observed_at = $entry.observed_at; note = $entry.note;
            http_status = $entry.http_status; route = $entry.route; request_id = $entry.request_id;
            payload_sha256 = $entry.payload_sha256; cursor_sha256 = $entry.cursor_sha256
        }
        if ([string]$entry.status -ne "pass") { $allPassed = $false }
    }
    if ($Decision -eq "GO" -and -not $allPassed) { throw "GO afvist: ikke alle 21 fysiske checkpoints er pass." }
    $appDump = @(& adb -s ([string]$State.adb_serial) shell dumpsys package $packageName 2>$null)
    $artifacts = Get-ArtifactReceipts -State $State
    $fixture = Get-Content -LiteralPath $fixtureManifest -Raw | ConvertFrom-Json
    $mutations = @(@($State.mutation_receipts) | ForEach-Object { Get-Content -LiteralPath ([string]$_) -Raw | ConvertFrom-Json })
    $cleanup = Stop-Harness -State $State -Uninstall
    foreach ($name in @("backend_stopped", "worker_stopped", "firewall_removed", "ports_free", "credential_file_deleted", "pairing_store_deleted", "test_package_uninstalled")) {
        if ($cleanup.$name -ne $true) { throw "A4-18R cleanup kunne ikke bevise $name." }
    }
    if ($cleanup.unknown_process_preserved -ne $false) { throw "A4-18R cleanup stødte på ukendt proces." }

    $receipt = [ordered]@{
        schema = "modelrig-agent4/a4-18r-physical-read-receipt/v1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        expected_sha = $ExpectedSha
        observed_head = Get-ExactHead
        fixture = $fixture
        mutations = $mutations
        pixel = [ordered]@{
            schema = "modelrig-agent4/a4-18r-pixel/v1"
            serial_sha256 = [string]$State.adb_serial_sha256
            manufacturer = [string]$State.pixel_manufacturer
            model = [string]$State.pixel_model
            android_release = [string]$State.pixel_android_release
            sdk = [string]$State.pixel_sdk
            package_name = $packageName
            version_name_line = [string](@($appDump | Select-String -Pattern "versionName=" | Select-Object -First 1).Line)
            version_code_line = [string](@($appDump | Select-String -Pattern "versionCode=" | Select-Object -First 1).Line)
        }
        trials = $trials
        artifacts = $artifacts
        cleanup = $cleanup
        all_required_observations_passed = $allPassed
        human_decision = $Decision
        credential_data_included = $false
        public_network = $false
        production_activation = $false
    }
    $tmp = Join-Path $output ".a4-18r-receipt-body.tmp.json"
    $receipt | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $tmp -Encoding UTF8
    try {
        $code = 'import hashlib,json,sys; v=json.load(open(sys.argv[1],encoding="utf-8-sig")); b=json.dumps(v,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(",",":")).encode("utf-8"); print("sha256:"+hashlib.sha256(b).hexdigest())'
        $digest = (& python -c $code $tmp).Trim()
        if ($LASTEXITCODE -ne 0 -or $digest -notmatch "^sha256:[0-9a-f]{64}$") { throw "Kunne ikke beregne canonical receipt-digest." }
    } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    $receipt["receipt_sha256"] = $digest
    $receipt | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    $State.phase = "finalized"; $State.human_decision = $Decision; Write-State -State $State
    Write-Host "A4-18R receipt: $receiptPath" -ForegroundColor Cyan
    Write-Host "Beslutning: $Decision" -ForegroundColor $(if ($Decision -eq "GO") { "Green" } else { "Yellow" })
}

Assert-WindowsAdministrator
Assert-Tool -Name "git"
Assert-Tool -Name "python"
Assert-ExactCleanHead

switch ($Action) {
    "PrepareOff" {
        if ([string]::IsNullOrWhiteSpace($LanAddress)) { throw "PrepareOff kræver -LanAddress." }
        Assert-PrivateLocalLanAddress -Address $LanAddress
        if (Test-Path -LiteralPath $output) {
            if (-not $Replace) { throw "A4-18R output findes allerede; brug en ny mappe eller -Replace." }
            if (Test-Path -LiteralPath $statePath -PathType Leaf) {
                try { $old = Read-State; Stop-Harness -State $old -Uninstall | Out-Null } catch { Write-Warning $_.Exception.Message }
            }
            Remove-Item -LiteralPath $output -Recurse -Force
        }
        New-Item -ItemType Directory -Path $output -Force | Out-Null
        New-Item -ItemType Directory -Path $binDir -Force | Out-Null
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
        [ordered]@{
            schema = "modelrig-agent4/a4-18r-output/v1"; repository_sha = $ExpectedSha;
            public_network = $false; production_activation = $false
        } | ConvertTo-Json | Set-Content -LiteralPath $markerPath -Encoding UTF8
        Invoke-FixtureBuild
        $apk = Build-PhysicalArtifacts
        $pixel = Resolve-PhysicalPixel
        Install-PhysicalApp -DeviceSerial ([string]$pixel.serial)
        $pixelIp = Resolve-PixelPrivateIp -DeviceSerial ([string]$pixel.serial) -TargetAddress $LanAddress
        Install-A4FirewallRule -Address $LanAddress -PixelIp $pixelIp
        Write-ProtectedAdminKey -Value (New-EphemeralAdminKey)
        Initialize-Observations
        $state = [pscustomobject][ordered]@{
            schema = "modelrig-agent4/a4-18r-operator-state/v1"
            created_at = (Get-Date).ToUniversalTime().ToString("o"); updated_at = (Get-Date).ToUniversalTime().ToString("o")
            expected_sha = $ExpectedSha; output_root = $output; phase = "preparing"; mode = "off"
            lan_address = $LanAddress; lan_url = "http://${LanAddress}:$backendPort"; pixel_ip = $pixelIp
            adb_serial = [string]$pixel.serial; adb_serial_sha256 = [string]$pixel.serial_sha256
            pixel_manufacturer = [string]$pixel.manufacturer; pixel_model = [string]$pixel.model
            pixel_android_release = [string]$pixel.android_release; pixel_sdk = [string]$pixel.sdk
            package_name = $packageName; apk_sha256 = "sha256:$((Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant())"
            backend_pid = 0; worker_pid = 0; device_id = $null; mutation_receipts = @(); last_mutation = $null
            public_network = $false; production_activation = $false
        }
        Write-State -State $state
        Start-LanStack -State $state -Mode off
        $state = Read-State
        $key = Get-AdminKey
        $pair = Invoke-RestMethod -Method Post -Uri "$($state.lan_url)/api/v1/pair/start" -Headers @{ "X-Admin-Key" = $key } -TimeoutSec 10
        $code = [string]$pair.code
        if ($code -notmatch "^[A-Z0-9]{4}-[A-Z0-9]{4}$") { throw "Backend returnerede ikke en gyldig pairing-kode." }
        Write-Host "A4-18R DEFAULT-OFF STACK ER KLAR" -ForegroundColor Green
        Write-Host "Server-URL: $($state.lan_url)" -ForegroundColor Cyan
        Write-Host "Parringskode (gemmes ikke i evidence): $code" -ForegroundColor Yellow
    }
    "Enable" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("default_off")
        Assert-CheckpointsPassed -Names @("default_off_feature_locked", "default_off_no_worker_fallback")
        [void](Resolve-SingleDeviceId)
        Stop-StackProcesses -State $state
        Start-LanStack -State $state -Mode enabled
    }
    "Grant" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("enabled_no_grant")
        Assert-CheckpointsPassed -Names @("paired_without_grant_403", "paired_without_grant_locked_no_stale")
        Invoke-GrantTransition -Transition grant -State $state
        $state.phase = "granted"; Write-State -State $state
    }
    "Revoke" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("granted")
        Assert-CheckpointsPassed -Names @("grant_same_token_200", "campaign_paging_no_loss", "timeline_paging_no_loss", "evidence_paging_no_loss", "detail_verification_matches", "no_write_controls", "stale_campaign_record_422", "stale_summary_422")
        Invoke-GrantTransition -Transition revoke -State $state
        $state.phase = "revoked"; Write-State -State $state
    }
    "Regrant" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("revoked")
        Assert-CheckpointsPassed -Names @("revoke_same_token_403", "revoke_clears_data", "restart_does_not_restore_grant")
        Invoke-GrantTransition -Transition grant -State $state
        $state.phase = "regranted"; Write-State -State $state
    }
    "RestartWorker" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("granted", "regranted")
        Stop-RecordedProcess -ProcessId ([int]$state.worker_pid) -Kind worker
        $state.worker_pid = Start-Worker -Mode enabled; Write-State -State $state
    }
    "RestartBackend" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("granted", "revoked", "regranted")
        Stop-RecordedProcess -ProcessId ([int]$state.backend_pid) -Kind backend
        $state.backend_pid = Start-Backend -HostAddress ([string]$state.lan_address) -OperatorEnabled:$true -GrantAdmin:$false -LogLabel "backend-lan"
        Write-State -State $state
    }
    "MutateCampaignSnapshot" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("granted"); Assert-CheckpointsPassed -Names @("grant_same_token_200")
        Invoke-Mutation -Mode campaign-record -State $state
    }
    "MutateSummarySnapshot" {
        $state = Read-State; Assert-StatePhase -State $state -Allowed @("granted"); Assert-CheckpointsPassed -Names @("stale_campaign_record_422")
        Invoke-Mutation -Mode summary -State $state
    }
    "Record" { $state = Read-State; Record-Checkpoint -State $state }
    "Status" {
        $state = Read-State; $observations = Read-Observations
        $passed = @($requiredCheckpoints | Where-Object { [string]$observations.checkpoints.$_.status -eq "pass" }).Count
        [ordered]@{
            schema = [string]$state.schema; expected_sha = [string]$state.expected_sha; phase = [string]$state.phase
            lan_url = [string]$state.lan_url; package_name = [string]$state.package_name
            backend_pid = [int]$state.backend_pid; worker_pid = [int]$state.worker_pid
            passed_checkpoints = $passed; total_checkpoints = $requiredCheckpoints.Count
            public_network = $false; production_activation = $false
        } | ConvertTo-Json -Depth 10
    }
    "Finalize" { $state = Read-State; Write-FinalReceipt -State $state }
    "Stop" { $state = Read-State; Stop-Harness -State $state -Uninstall | ConvertTo-Json -Depth 10 }
}
