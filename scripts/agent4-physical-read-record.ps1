[CmdletBinding()]
param(
    [ValidateSet("Record")]
    [string]$Action = "Record",

    [Parameter(Mandatory = $true)]
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

    [Parameter(Mandatory = $true)]
    [ValidateSet("Pass", "Fail")]
    [string]$Result,

    [string]$Note,
    [int]$HttpStatus = -1,
    [string]$Route,
    [string]$RequestId,
    [string]$PayloadSha256,
    [string]$CursorSha256,
    [string]$ScreenshotPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "agent4-physical-read-common.ps1")

$expectedHttpStatus = @{
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

$checkpointPhases = @{
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

function Test-SensitiveText {
    param([string]$Value, $State)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    $adminKey = Get-AdminKey
    if ($Value.Contains($adminKey)) { return $true }
    $pairingCode = [string]$State.pairing_code
    if (-not [string]::IsNullOrWhiteSpace($pairingCode) -and $Value.Contains($pairingCode)) {
        return $true
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
    $candidate = if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $script:repoRoot $Path }
    $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
    $runtimePrefix = [IO.Path]::GetFullPath($script:runtimeDir).TrimEnd('\') + '\'
    $full = [IO.Path]::GetFullPath($resolved)
    if (-not $full.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Screenshots skal ligge under validation/agent4-physical-runtime."
    }
    return Get-FileReceipt -Path $full
}

Assert-WindowsAdministrator
$state = Read-OperatorState
Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
$allowed = @($checkpointPhases[$Checkpoint])
if ($allowed -notcontains [string]$state.phase) {
    throw "Checkpoint $Checkpoint er ikke tilladt i fase '$($state.phase)'."
}
if ($Checkpoint -eq "stale_campaign_record_422" -and [string]$state.last_mutation -ne "campaign-record") {
    throw "Campaign-stale-checkpoint kræver først MutateCampaignSnapshot."
}
if ($Checkpoint -eq "stale_summary_422" -and [string]$state.last_mutation -ne "summary") {
    throw "Summary-stale-checkpoint kræver først MutateSummarySnapshot."
}

$httpStatusProvided = $PSBoundParameters.ContainsKey("HttpStatus")
if ($Result -eq "Pass" -and $expectedHttpStatus.ContainsKey($Checkpoint)) {
    $expected = [int]$expectedHttpStatus[$Checkpoint]
    if (-not $httpStatusProvided -or $HttpStatus -ne $expected) {
        throw "Checkpoint $Checkpoint kræver HTTP $expected for Pass."
    }
}
if ($httpStatusProvided -and ([string]::IsNullOrWhiteSpace($Route) -or $Route -notmatch "^/")) {
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

if (-not (Test-Path -LiteralPath $script:observationsPath -PathType Leaf)) {
    throw "A4-18 observationsfil mangler."
}
$observations = Get-Content -LiteralPath $script:observationsPath -Raw | ConvertFrom-Json
$entry = $observations.checkpoints.$Checkpoint
$entry.status = $Result.ToLowerInvariant()
$entry.observed_at = (Get-Date).ToUniversalTime().ToString("o")
$entry.note = if ([string]::IsNullOrWhiteSpace($Note)) { $null } else { $Note.Trim() }
$entry.http_status = if ($httpStatusProvided) { $HttpStatus } else { $null }
$entry.route = if ([string]::IsNullOrWhiteSpace($Route)) { $null } else { $Route.Trim() }
$entry.request_id = if ([string]::IsNullOrWhiteSpace($RequestId)) { $null } else { $RequestId.Trim() }
$entry.payload_sha256 = if ([string]::IsNullOrWhiteSpace($PayloadSha256)) { $null } else { $PayloadSha256 }
$entry.cursor_sha256 = if ([string]::IsNullOrWhiteSpace($CursorSha256)) { $null } else { $CursorSha256 }
$entry.screenshot = Get-ScreenshotReceipt -Path $ScreenshotPath
$observations | ConvertTo-Json -Depth 20 |
    Set-Content -LiteralPath $script:observationsPath -Encoding UTF8
Write-Host "Checkpoint $Checkpoint = $Result registreret." -ForegroundColor Green
