[CmdletBinding()]
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
        "MutateCampaignSnapshot",
        "MutateSummarySnapshot",
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
    [Nullable[int]]$HttpStatus,
    [string]$Route,
    [string]$RequestId,
    [string]$PayloadSha256,
    [string]$CursorSha256,
    [string]$ScreenshotPath,

    [ValidateSet("GO", "NO-GO")]
    [string]$Decision = "NO-GO"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "agent4-physical-read-common.ps1")

$script:requiredCheckpoints = @(
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

$script:expectedHttpStatus = @{
    default_off_feature_locked = 404
    paired_without_grant_403 = 403
    grant_same_token_200 = 200
    campaign_paging_no_loss = 200
    timeline_paging_no_loss = 200
    evidence_paging_no_loss = 200
    detail_verification_matches = 200
    stale_campaign_record_422 = 422
    stale_summary_422 = 422
    revoke_same_token_403 = 403
    restart_does_not_restore_grant = 403
    regrant_same_token_200 = 200
    backend_restart_recovery = 200
    worker_restart_recovery = 200
    network_recovery = 200
    malformed_schema_fail_closed = 200
    not_found_fail_closed = 404
}

$script:checkpointPhases = @{
    default_off_feature_locked = @("default_off")
    default_off_no_worker_fallback = @("default_off")
    paired_without_grant_403 = @("enabled_no_grant")
    paired_without_grant_locked_no_stale = @("enabled_no_grant")
    grant_same_token_200 = @("granted")
    campaign_paging_no_loss = @("granted")
    timeline_paging_no_loss = @("granted")
    evidence_paging_no_loss = @("granted")
    detail_verification_matches = @("granted")
    no_write_controls = @("granted")
    stale_campaign_record_422 = @("granted")
    stale_summary_422 = @("granted")
    revoke_same_token_403 = @("revoked")
    revoke_clears_data = @("revoked")
    restart_does_not_restore_grant = @("revoked")
    regrant_same_token_200 = @("regranted")
    backend_restart_recovery = @("granted", "regranted")
    worker_restart_recovery = @("granted", "regranted")
    network_recovery = @("granted", "regranted")
    malformed_schema_fail_closed = @("granted", "regranted")
    not_found_fail_closed = @("granted", "regranted")
}

function Read-Observations {
    if (-not (Test-Path -LiteralPath $script:observationsPath -PathType Leaf)) {
        throw "A4-18 observationsfil mangler. Kør PrepareOff først."
    }
    return Get-Content -LiteralPath $script:observationsPath -Raw | ConvertFrom-Json
}

function Write-Observations {
    param([Parameter(Mandatory = $true)]$Observations)
    $Observations | ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $script:observationsPath -Encoding UTF8
}

function Initialize-Observations {
    $items = [ordered]@{}
    foreach ($name in $script:requiredCheckpoints) {
        $items[$name] = [ordered]@{
            status = "pending"
            observed_at = $null
            note = $null
            http_status = $null
            route = $null
            request_id = $null
            payload_sha256 = $null
            cursor_sha256 = $null
            screenshot = $null
        }
    }
    [ordered]@{
        schema = "modelrig-agent4/physical-read-observations/v2"
        expected_sha = Get-ExactHead
        checkpoints = $items
        production_activation = $false
    } | ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $script:observationsPath -Encoding UTF8
}

function Get-CheckpointStatus {
    param([Parameter(Mandatory = $true)]$Observations, [Parameter(Mandatory = $true)][string]$Name)
    return [string]$Observations.checkpoints.$Name.status
}

function Assert-CheckpointsPassed {
    param([Parameter(Mandatory = $true)][string[]]$Names)
    $observations = Read-Observations
    $missing = @()
    foreach ($name in $Names) {
        if ((Get-CheckpointStatus -Observations $observations -Name $name) -ne "pass") {
            $missing += $name
        }
    }
    if ($missing.Count -gt 0) {
        throw "Fasen er låst. Disse checkpoints er ikke bestået: $($missing -join ', ')."
    }
}

function Assert-StatePhase {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string[]]$Allowed)
    if ($Allowed -notcontains [string]$State.phase) {
        throw "Handling er ikke tilladt i fase '$($State.phase)'. Forventede: $($Allowed -join ', ')."
    }
}

function Resolve-DeviceId {
    param([string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return $Requested.Trim() }
    if (-not (Test-Path -LiteralPath $script:pairingData -PathType Leaf)) {
        throw "Pairing-store mangler."
    }
    $store = Get-Content -LiteralPath $script:pairingData -Raw | ConvertFrom-Json
    $devices = @($store.devices)
    if ($devices.Count -ne 1) {
        throw "Der skal være præcis én parret fysisk enhed; fandt $($devices.Count). Brug -DeviceId ved et bevidst valg."
    }
    return [string]$devices[0].id
}

function Assert-OnePairedDevice {
    [void](Resolve-DeviceId -Requested $null)
}

function Set-ReadGrantTransition {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("grant", "revoke", "regrant")][string]$Transition,
        [string]$RequestedDeviceId
    )
    $state = Read-OperatorState
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    switch ($Transition) {
        "grant" {
            Assert-StatePhase -State $state -Allowed @("enabled_no_grant")
            Assert-CheckpointsPassed -Names @("paired_without_grant_403", "paired_without_grant_locked_no_stale")
            $enabled = $true
            $nextPhase = "granted"
        }
        "revoke" {
            Assert-StatePhase -State $state -Allowed @("granted")
            Assert-CheckpointsPassed -Names @(
                "grant_same_token_200",
                "campaign_paging_no_loss",
                "timeline_paging_no_loss",
                "evidence_paging_no_loss",
                "detail_verification_matches",
                "no_write_controls",
                "stale_campaign_record_422",
                "stale_summary_422"
            )
            $enabled = $false
            $nextPhase = "revoked"
        }
        "regrant" {
            Assert-StatePhase -State $state -Allowed @("revoked")
            Assert-CheckpointsPassed -Names @(
                "revoke_same_token_403",
                "revoke_clears_data",
                "restart_does_not_restore_grant"
            )
            $enabled = $true
            $nextPhase = "regranted"
        }
    }

    $resolvedDevice = Resolve-DeviceId -Requested $RequestedDeviceId
    $adminKey = Get-AdminKey
    try {
        $env:MODELRIG_ADMIN_KEY = $adminKey
        if ($enabled) {
            & $script:grantExe -grant $resolvedDevice -url "http://127.0.0.1:8080"
        }
        else {
            & $script:grantExe -revoke $resolvedDevice -url "http://127.0.0.1:8080"
        }
        if ($LASTEXITCODE -ne 0) { throw "Grant CLI afviste ændringen." }
    }
    finally {
        Remove-Item Env:MODELRIG_ADMIN_KEY -ErrorAction SilentlyContinue
    }
    $state.device_id = $resolvedDevice
    $state.phase = $nextPhase
    Write-OperatorState -State $state
}

function Test-SensitiveText {
    param([string]$Value, $State)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    $adminKey = Get-AdminKey
    if ($Value.Contains($adminKey)) { return $true }
    if ($null -ne $State.pairing_code -and -not [string]::IsNullOrWhiteSpace([string]$State.pairing_code)) {
        if ($Value.Contains([string]$State.pairing_code)) { return $true }
    }
    return ($Value -match "(?i)authorization\s*:|x-admin-key\s*:|bearer\s+[A-Za-z0-9+/=_-]+")
}

function Assert-ReceiptHash {
    param([string]$Value, [string]$Label)
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    if ($Value -notmatch "^sha256:[0-9a-f]{64}$") {
        throw "$Label skal være sha256:<64 lowercase hex>."
    }
}

function Get-ScreenshotReceipt {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    $runtimePrefix = [IO.Path]::GetFullPath($script:runtimeDir).TrimEnd('\') + '\'
    $full = [IO.Path]::GetFullPath($resolved)
    if (-not $full.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Screenshots skal ligge under validation/agent4-physical-runtime."
    }
    return Get-FileReceipt -Path $full
}

function Record-Checkpoint {
    if ([string]::IsNullOrWhiteSpace($Checkpoint) -or [string]::IsNullOrWhiteSpace($Result)) {
        throw "Record kræver både -Checkpoint og -Result Pass|Fail."
    }
    $state = Read-OperatorState
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    $allowed = @($script:checkpointPhases[$Checkpoint])
    Assert-StatePhase -State $state -Allowed $allowed

    if ($Checkpoint -eq "stale_campaign_record_422" -and [string]$state.last_mutation -ne "campaign-record") {
        throw "Campaign-stale-checkpoint kræver først MutateCampaignSnapshot."
    }
    if ($Checkpoint -eq "stale_summary_422" -and [string]$state.last_mutation -ne "summary") {
        throw "Summary-stale-checkpoint kræver først MutateSummarySnapshot."
    }

    if ($Result -eq "Pass" -and $script:expectedHttpStatus.ContainsKey($Checkpoint)) {
        $expected = [int]$script:expectedHttpStatus[$Checkpoint]
        if (-not $HttpStatus.HasValue -or $HttpStatus.Value -ne $expected) {
            throw "Checkpoint $Checkpoint kræver HTTP $expected for Pass."
        }
    }
    if ($HttpStatus.HasValue -and ([string]::IsNullOrWhiteSpace($Route) -or $Route -notmatch "^/")) {
        throw "HTTP-observationer kræver en redigeret relativ route."
    }
    if (-not [string]::IsNullOrWhiteSpace($Route)) {
        if ($Route -match "[?]" -or $Route -match "://" -or (Test-SensitiveText -Value $Route -State $state)) {
            throw "Route skal være redigeret og må ikke indeholde query eller credential-data."
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($RequestId) -and $RequestId -notmatch "^[A-Za-z0-9._:-]{1,200}$") {
        throw "RequestId indeholder ugyldige tegn."
    }
    Assert-ReceiptHash -Value $PayloadSha256 -Label "PayloadSha256"
    Assert-ReceiptHash -Value $CursorSha256 -Label "CursorSha256"
    if (Test-SensitiveText -Value $Note -State $state) {
        throw "Noten ligner credential-data og må ikke gemmes."
    }

    $observations = Read-Observations
    $entry = $observations.checkpoints.$Checkpoint
    $entry.status = $Result.ToLowerInvariant()
    $entry.observed_at = (Get-Date).ToUniversalTime().ToString("o")
    $entry.note = if ([string]::IsNullOrWhiteSpace($Note)) { $null } else { $Note.Trim() }
    $entry.http_status = if ($HttpStatus.HasValue) { $HttpStatus.Value } else { $null }
    $entry.route = if ([string]::IsNullOrWhiteSpace($Route)) { $null } else { $Route.Trim() }
    $entry.request_id = if ([string]::IsNullOrWhiteSpace($RequestId)) { $null } else { $RequestId.Trim() }
    $entry.payload_sha256 = if ([string]::IsNullOrWhiteSpace($PayloadSha256)) { $null } else { $PayloadSha256 }
    $entry.cursor_sha256 = if ([string]::IsNullOrWhiteSpace($CursorSha256)) { $null } else { $CursorSha256 }
    $entry.screenshot = Get-ScreenshotReceipt -Path $ScreenshotPath
    Write-Observations -Observations $observations
}

function Get-ArtifactReceipts {
    param($State)
    $paths = @(
        $script:fixtureManifest,
        $script:backendLog,
        $script:workerLog,
        $script:pairingData,
        $script:backendExe,
        $script:grantExe,
        [string]$State.apk,
        (Join-Path $script:repoRoot "worker\app\entrypoint.py"),
        (Join-Path $script:repoRoot "worker\app\agent4\production_bootstrap.py"),
        (Join-Path $script:repoRoot "worker\app\agent4\operator_api.py"),
        (Join-Path $script:repoRoot "worker\app\agent4\campaign_list_query.py"),
        (Join-Path $script:repoRoot "android\app\src\main\java\dk\ternedal\modelrig\net\Agent4OperatorClient.kt"),
        (Join-Path $script:repoRoot "android\app\src\main\java\dk\ternedal\modelrig\ui\Agent4OperatorScreen.kt"),
        (Join-Path $script:repoRoot "android\app\src\main\java\dk\ternedal\modelrig\ui\Agent4CampaignDetailScreen.kt")
    ) + @($State.mutation_receipts)
    return @($paths | ForEach-Object { Get-FileReceipt -Path $_ } | Where-Object { $null -ne $_ })
}

function Finalize-PhysicalReceipt {
    $state = Read-OperatorState
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    Assert-StatePhase -State $state -Allowed @("regranted")
    $observations = Read-Observations
    $checkpointResults = [ordered]@{}
    $allPassed = $true
    foreach ($name in $script:requiredCheckpoints) {
        $entry = $observations.checkpoints.$name
        $checkpointResults[$name] = [ordered]@{
            status = [string]$entry.status
            observed_at = $entry.observed_at
            note = $entry.note
            http_status = $entry.http_status
            route = $entry.route
            request_id = $entry.request_id
            payload_sha256 = $entry.payload_sha256
            cursor_sha256 = $entry.cursor_sha256
            screenshot = $entry.screenshot
        }
        if ([string]$entry.status -ne "pass") { $allPassed = $false }
    }
    if ($Decision -eq "GO" -and -not $allPassed) { $Decision = "NO-GO" }

    $artifacts = Get-ArtifactReceipts -State $state
    $mutations = @($state.mutation_receipts | ForEach-Object {
        if (Test-Path -LiteralPath $_ -PathType Leaf) {
            Get-Content -LiteralPath $_ -Raw | ConvertFrom-Json
        }
    })
    $cleanup = Stop-RecordedStack
    $portsFree = $null -eq (Get-ListenerPid -Port 8080) -and $null -eq (Get-ListenerPid -Port 8099)
    $cleanupPassed = (
        [bool]$cleanup.firewall_removed -and
        -not [bool]$cleanup.unknown_process_preserved -and
        $portsFree -and
        -not (Test-Path -LiteralPath $script:adminKeyFile -PathType Leaf)
    )
    if (-not $cleanupPassed) {
        $Decision = "NO-GO"
        $allPassed = $false
    }

    $appDump = @(& adb shell dumpsys package $script:packageName 2>$null)
    $receipt = [ordered]@{
        schema = "modelrig-agent4/physical-read-receipt/v2"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        expected_sha = [string]$state.expected_sha
        observed_head = Get-ExactHead
        branch = [string]$state.branch
        backend_version = [string]$state.backend_version
        worker_version = [string]$state.worker_version
        fixture = Get-Content -LiteralPath $script:fixtureManifest -Raw | ConvertFrom-Json
        mutations = $mutations
        pixel = [ordered]@{
            model = Get-AdbProperty -Name "ro.product.model"
            android_release = Get-AdbProperty -Name "ro.build.version.release"
            sdk = Get-AdbProperty -Name "ro.build.version.sdk"
            app_package = $script:packageName
            version_name_line = Get-FirstMatchingLine -Lines $appDump -Pattern "versionName="
            version_code_line = Get-FirstMatchingLine -Lines $appDump -Pattern "versionCode="
        }
        trials = $checkpointResults
        artifacts = $artifacts
        cleanup = [ordered]@{
            backend_stopped = [bool]$cleanup.backend_stopped
            worker_stopped = [bool]$cleanup.worker_stopped
            unknown_process_preserved = [bool]$cleanup.unknown_process_preserved
            firewall_removed = [bool]$cleanup.firewall_removed
            ports_free = $portsFree
            admin_key_deleted = -not (Test-Path -LiteralPath $script:adminKeyFile -PathType Leaf)
            passed = $cleanupPassed
        }
        all_required_observations_passed = $allPassed
        human_decision = $Decision
        credential_data_included = $false
        public_network = $false
        production_activation = $false
    }
    $withoutDigest = $receipt | ConvertTo-Json -Depth 30 -Compress
    $receipt.receipt_sha256 = "sha256:$(Get-Sha256HexForBytes -Bytes ([Text.Encoding]::UTF8.GetBytes($withoutDigest)))"
    $receipt | ConvertTo-Json -Depth 30 |
        Set-Content -LiteralPath $script:receiptPath -Encoding UTF8

    $state.phase = "finalized"
    $state.backend_pid = 0
    $state.worker_pid = 0
    $state.human_decision = $Decision
    $state.receipt = $script:receiptPath
    Write-OperatorState -State $state
    Write-Host "A4-18 receipt: $script:receiptPath" -ForegroundColor Cyan
    Write-Host "Beslutning: $Decision" -ForegroundColor $(if ($Decision -eq "GO") { "Green" } else { "Yellow" })
    if ($Decision -ne "GO") { throw "A4-18 sluttede NO-GO. Se receipt og observationsfil." }
}

function Show-PhysicalStatus {
    if (-not (Test-Path -LiteralPath $script:statePath -PathType Leaf)) {
        Write-Host "A4-18 er ikke forberedt."
        return
    }
    $state = Read-OperatorState
    $observations = Read-Observations
    $passed = @($script:requiredCheckpoints | Where-Object {
        (Get-CheckpointStatus -Observations $observations -Name $_) -eq "pass"
    }).Count
    [ordered]@{
        expected_sha = [string]$state.expected_sha
        phase = [string]$state.phase
        mode = [string]$state.mode
        lan_url = [string]$state.lan_url
        backend_pid = [int]$state.backend_pid
        worker_pid = [int]$state.worker_pid
        device_id = $state.device_id
        passed_checkpoints = $passed
        total_checkpoints = $script:requiredCheckpoints.Count
        last_mutation = $state.last_mutation
        receipt = $state.receipt
        production_activation = $false
    } | ConvertTo-Json -Depth 8
}

Assert-WindowsAdministrator
New-Item -ItemType Directory -Path $script:runtimeDir -Force | Out-Null

switch ($Action) {
    "PrepareOff" {
        if ([string]::IsNullOrWhiteSpace($ExpectedSha)) { throw "PrepareOff kræver -ExpectedSha." }
        Assert-ExactCleanHead -RequiredSha $ExpectedSha
        if (Test-Path -LiteralPath $script:statePath -PathType Leaf) {
            Stop-RecordedStack | Out-Null
        }
        Remove-Item -LiteralPath $script:runtimeDir -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $script:runtimeDir -Force | Out-Null
        New-AdminKey
        $apk = Build-And-InstallPhysicalArtifacts
        $lanAddress = Resolve-LanAddress
        $state = [pscustomobject][ordered]@{
            schema = "modelrig-agent4/physical-read-operator-state/v2"
            created_at = (Get-Date).ToUniversalTime().ToString("o")
            updated_at = (Get-Date).ToUniversalTime().ToString("o")
            expected_sha = $ExpectedSha
            branch = (& git -C $script:repoRoot branch --show-current).Trim()
            phase = "preparing"
            mode = "off"
            lan_url = "http://${lanAddress}:8080"
            pairing_code = $null
            pairing_expires_at = $null
            backend_pid = 0
            worker_pid = 0
            backend_version = $null
            worker_version = $null
            device_id = $null
            apk = $apk
            mutation_receipts = @()
            last_mutation = $null
            receipt = $null
            human_decision = $null
            production_activation = $false
        }
        Write-OperatorState -State $state
        Initialize-Observations
        Start-Stack -Mode off -State $state
        $state = Read-OperatorState
        $pairing = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/start" -TimeoutSec 10
        $state.pairing_code = [string]$pairing.code
        $state.pairing_expires_at = [string]$pairing.expires_at
        Write-OperatorState -State $state
        Write-Host "A4-18 DEFAULT-OFF STACK ER KLAR" -ForegroundColor Green
        Write-Host "Server-URL:   $($state.lan_url)" -ForegroundColor Cyan
        Write-Host "Parringskode: $($state.pairing_code)" -ForegroundColor Yellow
    }
    "Enable" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("default_off")
        Assert-CheckpointsPassed -Names @("default_off_feature_locked", "default_off_no_worker_fallback")
        Assert-OnePairedDevice
        Stop-RecordedStack -PreserveAdminKey | Out-Null
        Start-Stack -Mode enabled -State $state
        Write-Host "Agent 4 er enabled; Pixel har stadig intet grant." -ForegroundColor Green
    }
    "Grant" {
        Set-ReadGrantTransition -Transition grant -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er tildelt uden re-pairing." -ForegroundColor Green
    }
    "Revoke" {
        Set-ReadGrantTransition -Transition revoke -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er fjernet; næste Pixel-request skal være 403." -ForegroundColor Yellow
    }
    "Regrant" {
        Set-ReadGrantTransition -Transition regrant -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er tildelt igen uden re-pairing." -ForegroundColor Green
    }
    "RestartWorker" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("enabled_no_grant", "granted", "revoked", "regranted")
        Restart-ExpectedProcess -Kind worker -State $state
    }
    "RestartBackend" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("enabled_no_grant", "granted", "revoked", "regranted")
        Restart-ExpectedProcess -Kind backend -State $state
    }
    "MutateCampaignSnapshot" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("granted")
        Assert-CheckpointsPassed -Names @("grant_same_token_200")
        $receipt = Invoke-PhysicalFixtureMutation -Mode campaign-record -State $state
        Write-Host "Campaign-snapshot muteret: $receipt" -ForegroundColor Yellow
    }
    "MutateSummarySnapshot" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("granted")
        Assert-CheckpointsPassed -Names @("stale_campaign_record_422")
        $receipt = Invoke-PhysicalFixtureMutation -Mode summary -State $state
        Write-Host "Summary-snapshot muteret: $receipt" -ForegroundColor Yellow
    }
    "Record" {
        Record-Checkpoint
        Write-Host "Checkpoint $Checkpoint = $Result registreret." -ForegroundColor Green
    }
    "Finalize" { Finalize-PhysicalReceipt }
    "Stop" {
        $cleanup = Stop-RecordedStack
        if (Test-Path -LiteralPath $script:statePath -PathType Leaf) {
            $state = Read-OperatorState
            $state.phase = "stopped"
            $state.backend_pid = 0
            $state.worker_pid = 0
            Write-OperatorState -State $state
        }
        $cleanup | ConvertTo-Json -Depth 6
    }
    "Status" { Show-PhysicalStatus }
}
