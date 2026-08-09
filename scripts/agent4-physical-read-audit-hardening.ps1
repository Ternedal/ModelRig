[CmdletBinding()]
param(
    [string]$ReceiptPath,
    [string]$RepoRoot,
    [string]$OutputPath,
    [switch]$RequireRemoteRefs,
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ShaPattern = '^sha256:[0-9a-f]{64}$'
$RequiredTrials = @(
    "default_off_feature_locked", "default_off_no_worker_fallback",
    "paired_without_grant_403", "paired_without_grant_locked_no_stale",
    "grant_same_token_200", "campaign_paging_no_loss",
    "timeline_paging_no_loss", "evidence_paging_no_loss",
    "detail_verification_matches", "no_write_controls",
    "stale_campaign_record_422", "stale_summary_422",
    "revoke_same_token_403", "revoke_clears_data",
    "restart_does_not_restore_grant", "regrant_same_token_200",
    "backend_restart_recovery", "worker_restart_recovery",
    "network_recovery", "malformed_schema_fail_closed",
    "not_found_fail_closed"
)
$UiObservationTrials = @(
    "default_off_feature_locked", "default_off_no_worker_fallback",
    "paired_without_grant_locked_no_stale", "campaign_paging_no_loss",
    "timeline_paging_no_loss", "evidence_paging_no_loss",
    "detail_verification_matches", "no_write_controls",
    "stale_campaign_record_422", "stale_summary_422",
    "revoke_clears_data", "malformed_schema_fail_closed"
)

function Get-PropertyValue {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-ObjectWithoutProperty {
    param($Object, [string]$ExcludedName)
    $copy = [ordered]@{}
    foreach ($property in $Object.PSObject.Properties) {
        if ($property.Name -ne $ExcludedName) { $copy[$property.Name] = $property.Value }
    }
    return $copy
}

function Get-Sha256ForText {
    param([string]$Text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        $hash = $algorithm.ComputeHash($bytes)
    }
    finally { $algorithm.Dispose() }
    return "sha256:$(([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant())"
}

function Assert-Sha256 {
    param($Value, [string]$Label)
    if (-not ($Value -is [string]) -or $Value -notmatch $ShaPattern) {
        throw "$Label skal være sha256:<64 lowercase hex>."
    }
}

function Assert-SafeRelativePath {
    param($Value, [string]$Label)
    if (
        -not ($Value -is [string]) -or
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value.Contains('\') -or
        $Value.StartsWith('/') -or
        $Value -match '(^|/)\.\.(/|$)'
    ) {
        throw "$Label er ikke en sikker relativ repository-path."
    }
}

function Assert-MutationDigests {
    param($Mutations)
    $items = @($Mutations)
    if ($items.Count -ne 2) { throw "Der skal være præcis to mutation receipts." }
    foreach ($item in $items) {
        $mode = [string](Get-PropertyValue $item "mode")
        $claimed = Get-PropertyValue $item "receipt_sha256"
        Assert-Sha256 $claimed "Mutation $mode receipt_sha256"
        $without = Get-ObjectWithoutProperty -Object $item -ExcludedName "receipt_sha256"
        $actual = Get-Sha256ForText (($without | ConvertTo-Json -Depth 20 -Compress))
        if ($actual -ne $claimed) {
            throw "Mutation $mode digest matcher ikke indholdet."
        }
    }
}

function Assert-ExactTrialSet {
    param($Trials)
    if ($null -eq $Trials) { throw "Trials mangler." }
    $actual = @($Trials.PSObject.Properties.Name | Sort-Object)
    $expected = @($RequiredTrials | Sort-Object)
    if ($actual.Count -ne $expected.Count) {
        throw "Trials skal indeholde præcis 21 checkpoints; fandt $($actual.Count)."
    }
    for ($index = 0; $index -lt $expected.Count; $index++) {
        if ($actual[$index] -ne $expected[$index]) {
            throw "Trials indeholder manglende eller ukendte checkpoints."
        }
    }
}

function Assert-ScreenshotReceipt {
    param($Screenshot, [string]$TrialName, [string]$RepoRootResolved)
    if ($null -eq $Screenshot) { return $false }
    $path = Get-PropertyValue $Screenshot "path"
    Assert-SafeRelativePath $path "Screenshot path for $TrialName"
    if (-not ([string]$path).StartsWith('validation/agent4-physical-runtime/')) {
        throw "Screenshot for $TrialName ligger uden for validation runtime."
    }
    $claimed = Get-PropertyValue $Screenshot "sha256"
    Assert-Sha256 $claimed "Screenshot hash for $TrialName"
    $file = Join-Path $RepoRootResolved ([string]$path).Replace('/', '\')
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Screenshot mangler for $TrialName: $path"
    }
    $item = Get-Item -LiteralPath $file
    if ([int64](Get-PropertyValue $Screenshot "size_bytes") -ne [int64]$item.Length) {
        throw "Screenshot-størrelsen afviger for $TrialName."
    }
    $actual = "sha256:$((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant())"
    if ($actual -ne $claimed) { throw "Screenshot-hashen afviger for $TrialName." }
    return $true
}

function Assert-UiEvidence {
    param($Trials, [string]$RepoRootResolved)
    foreach ($name in $UiObservationTrials) {
        $entry = Get-PropertyValue $Trials $name
        $hasScreenshot = Assert-ScreenshotReceipt `
            -Screenshot (Get-PropertyValue $entry "screenshot") `
            -TrialName $name `
            -RepoRootResolved $RepoRootResolved
        $note = [string](Get-PropertyValue $entry "note")
        if (-not $hasScreenshot -and [string]::IsNullOrWhiteSpace($note)) {
            throw "$name mangler både redigeret screenshot og menneskelig UI-observation."
        }
    }
}

function Assert-SafetyHardening {
    param($Receipt, [string]$RepoRootResolved)
    $safety = Get-PropertyValue $Receipt "safety_hardening"
    if ([string](Get-PropertyValue $safety "schema") -ne "modelrig-agent4/physical-read-safety-evidence/v1") {
        throw "safety_hardening mangler eller har forkert schema."
    }
    foreach ($name in @("physical_pixel", "artifacts_hashed_after_prestop")) {
        if ((Get-PropertyValue $safety $name) -ne $true) { throw "safety_hardening.$name skal være true." }
    }
    foreach ($name in @("wildcard_binding", "public_network", "production_activation")) {
        if ((Get-PropertyValue $safety $name) -ne $false) { throw "safety_hardening.$name skal være false." }
    }
    if ([string](Get-PropertyValue $safety "pixel_manufacturer") -ne "Google") {
        throw "Safety evidence dokumenterer ikke Google hardware."
    }
    $model = [string](Get-PropertyValue $safety "pixel_model")
    if ($model -notmatch '^Pixel\b' -or $model -match '(?i)emulator|qemu|sdk_gphone|generic') {
        throw "Safety evidence dokumenterer ikke en fysisk Pixel."
    }
    Assert-Sha256 (Get-PropertyValue $safety "pixel_serial_sha256") "Pixel serial hash"
    $backendAddress = [string](Get-PropertyValue $safety "backend_bound_address")
    if ($backendAddress -ne [string](Get-PropertyValue $safety "lan_address")) {
        throw "Backend bind matcher ikke safety LAN-adressen."
    }
    if ([string](Get-PropertyValue $safety "worker_bound_address") -ne "127.0.0.1") {
        throw "Worker er ikke dokumenteret som loopback-only."
    }
    if ([string](Get-PropertyValue $safety "firewall_remote_scope") -ne "LocalSubnet") {
        throw "Firewall scope er ikke LocalSubnet."
    }
    if ([string](Get-PropertyValue $safety "network_profile") -eq "Public") {
        throw "Public netværksprofil er ikke tilladt."
    }

    $binding = Get-PropertyValue $safety "binding_file"
    $bindingPath = Get-PropertyValue $binding "path"
    Assert-SafeRelativePath $bindingPath "Safety binding path"
    if ([string]$bindingPath -ne "validation/agent4-physical-runtime/safety-binding.json") {
        throw "Safety binding har forkert path."
    }
    Assert-Sha256 (Get-PropertyValue $binding "sha256") "Safety binding hash"
    $bindingFile = Join-Path $RepoRootResolved ([string]$bindingPath).Replace('/', '\')
    if (-not (Test-Path -LiteralPath $bindingFile -PathType Leaf)) {
        throw "Safety binding-filen mangler."
    }
    $actual = "sha256:$((Get-FileHash -LiteralPath $bindingFile -Algorithm SHA256).Hash.ToLowerInvariant())"
    if ($actual -ne [string](Get-PropertyValue $binding "sha256")) {
        throw "Safety binding-hashen afviger."
    }

    $pixel = Get-PropertyValue $Receipt "pixel"
    if ([string](Get-PropertyValue $pixel "model") -ne $model) {
        throw "Pixel-model i receipt og safety evidence matcher ikke."
    }
}

if ($SelfTest) {
    $required = @($RequiredTrials | Sort-Object)
    if ($required.Count -ne 21) { throw "Hardening self-test checkpoint count fejlede." }
    if ((Get-Sha256ForText "a") -notmatch $ShaPattern) { throw "Hardening self-test SHA fejlede." }
    Write-Host "A4-18 receipt hardening self-test: PASS" -ForegroundColor Green
    exit 0
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
$repoRootResolved = (Resolve-Path $RepoRoot).Path
if ([string]::IsNullOrWhiteSpace($ReceiptPath)) {
    $ReceiptPath = Join-Path $repoRootResolved "validation\agent4-physical-read-latest.json"
}
if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
    throw "Receipt mangler: $ReceiptPath"
}
$receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-ExactTrialSet (Get-PropertyValue $receipt "trials")
Assert-MutationDigests (Get-PropertyValue $receipt "mutations")
Assert-SafetyHardening -Receipt $receipt -RepoRootResolved $repoRootResolved
Assert-UiEvidence -Trials (Get-PropertyValue $receipt "trials") -RepoRootResolved $repoRootResolved

$legacy = Join-Path $PSScriptRoot "agent4-physical-read-audit.ps1"
if (-not (Test-Path -LiteralPath $legacy -PathType Leaf)) {
    throw "Den eksisterende A4-18 auditor mangler."
}
$forward = @()
if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) { $forward += @("-ReceiptPath", $ReceiptPath) }
if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) { $forward += @("-RepoRoot", $RepoRoot) }
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) { $forward += @("-OutputPath", $OutputPath) }
if ($RequireRemoteRefs) { $forward += "-RequireRemoteRefs" }
& $legacy @forward
exit $LASTEXITCODE
