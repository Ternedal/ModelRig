[CmdletBinding()]
param(
    [ValidateSet("Finalize")]
    [string]$Action = "Finalize",

    [ValidateSet("GO", "NO-GO")]
    [string]$Decision = "NO-GO"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "agent4-physical-read-common.ps1")

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

function Test-RecordedProcessGone {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    return $null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

Assert-WindowsAdministrator
$state = Read-OperatorState
Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
if ([string]$state.phase -ne "regranted") {
    throw "Finalize kræver regranted-fasen; nuværende fase er '$($state.phase)'."
}
if (-not (Test-Path -LiteralPath $script:observationsPath -PathType Leaf)) {
    throw "A4-18 observationsfil mangler."
}
$observations = Get-Content -LiteralPath $script:observationsPath -Raw | ConvertFrom-Json
$checkpointResults = [ordered]@{}
$allPassed = $true
foreach ($name in $requiredCheckpoints) {
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
$mutations = @(
    @($state.mutation_receipts) | ForEach-Object {
        if (Test-Path -LiteralPath $_ -PathType Leaf) {
            Get-Content -LiteralPath $_ -Raw | ConvertFrom-Json
        }
    }
)
$recordedBackendPid = [int]$state.backend_pid
$recordedWorkerPid = [int]$state.worker_pid
$cleanup = Stop-RecordedStack
$portsFree = $null -eq (Get-ListenerPid -Port 8080) -and $null -eq (Get-ListenerPid -Port 8099)

# The mandatory safety wrapper deliberately performs a verified pre-stop before
# this finalizer hashes artifacts. In that path Stop-RecordedStack is idempotent
# and may report false because the expected listeners are already gone. Count
# that as successful only when the original recorded PID is also absent and both
# ports remain free. A reused or still-running PID therefore fails closed.
$backendStopped = [bool]$cleanup.backend_stopped
if (
    -not $backendStopped -and
    $portsFree -and
    (Test-RecordedProcessGone -ProcessId $recordedBackendPid)
) {
    $backendStopped = $true
}
$workerStopped = [bool]$cleanup.worker_stopped
if (
    -not $workerStopped -and
    $portsFree -and
    (Test-RecordedProcessGone -ProcessId $recordedWorkerPid)
) {
    $workerStopped = $true
}

$cleanupPassed = (
    $backendStopped -and
    $workerStopped -and
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
        backend_stopped = $backendStopped
        worker_stopped = $workerStopped
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
$receipt["receipt_sha256"] = "sha256:$(Get-Sha256HexForBytes -Bytes ([Text.Encoding]::UTF8.GetBytes($withoutDigest)))"
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
if ($Decision -ne "GO") {
    throw "A4-18 sluttede NO-GO. Se receipt og observationsfil."
}
