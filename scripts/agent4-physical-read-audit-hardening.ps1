[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ReceiptPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$requiredTrials = @(
    "default_off_feature_locked", "default_off_no_worker_fallback", "paired_without_grant_403",
    "paired_without_grant_locked_no_stale", "grant_same_token_200", "campaign_paging_no_loss",
    "timeline_paging_no_loss", "evidence_paging_no_loss", "detail_verification_matches",
    "no_write_controls", "stale_campaign_record_422", "stale_summary_422", "revoke_same_token_403",
    "revoke_clears_data", "restart_does_not_restore_grant", "regrant_same_token_200",
    "backend_restart_recovery", "worker_restart_recovery", "network_recovery",
    "malformed_schema_fail_closed", "not_found_fail_closed"
)

function Get-Sha256ForText {
    param([Parameter(Mandatory = $true)][string]$Text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        $hash = $algorithm.ComputeHash($bytes)
    }
    finally { $algorithm.Dispose() }
    return "sha256:$(([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant())"
}

function Get-WithoutReceiptDigest {
    param([Parameter(Mandatory = $true)]$Object)
    $copy = [ordered]@{}
    foreach ($property in $Object.PSObject.Properties) {
        if ($property.Name -ne "receipt_sha256") {
            $copy[$property.Name] = $property.Value
        }
    }
    return $copy
}

if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
    throw "Receipt mangler: $ReceiptPath"
}

$receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
$trialNames = @($receipt.trials.PSObject.Properties | ForEach-Object { $_.Name })
$unexpected = @($trialNames | Where-Object { $requiredTrials -notcontains $_ })
$missing = @($requiredTrials | Where-Object { $trialNames -notcontains $_ })
if ($unexpected.Count -ne 0) {
    throw "Receipt indeholder ukendte checkpoints: $($unexpected -join ', ')"
}
if ($missing.Count -ne 0 -or $trialNames.Count -ne $requiredTrials.Count) {
    throw "Receiptens checkpoint-sæt er ikke præcis de 21 autoriserede checkpoints."
}

$sdk = [string]$receipt.pixel.sdk
if ($sdk -notmatch '^[0-9]+$') {
    throw "Pixel SDK skal være numerisk."
}

$mutations = @($receipt.mutations)
if ($mutations.Count -ne 2) {
    throw "Der skal være præcis to mutation receipts."
}
foreach ($mutation in $mutations) {
    $claimed = [string]$mutation.receipt_sha256
    if ($claimed -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "Mutation receipt_sha256 mangler eller er ugyldig."
    }
    $withoutDigest = Get-WithoutReceiptDigest -Object $mutation
    $canonical = $withoutDigest | ConvertTo-Json -Depth 30 -Compress
    $actual = Get-Sha256ForText -Text $canonical
    if ($actual -ne $claimed) {
        throw "Mutation receipt digest mismatch for mode '$([string]$mutation.mode)'."
    }
}

Write-Host "A4-18 RECEIPT AUDIT HARDENING: PASS" -ForegroundColor Green
exit 0
