[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ReceiptPath,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$OutputPath
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
$UiEvidenceTrials = @(
    "default_off_feature_locked",
    "paired_without_grant_locked_no_stale",
    "no_write_controls",
    "revoke_clears_data"
)
$Findings = New-Object System.Collections.ArrayList

function Add-Finding {
    param([string]$Code, [string]$Message)
    [void]$script:Findings.Add([ordered]@{ code = $Code; message = $Message })
}

function Get-PropertyValue {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
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

function Test-Sha256 {
    param($Value)
    return $Value -is [string] -and $Value -match $script:ShaPattern
}

function Get-ObjectWithoutProperty {
    param($Object, [string]$ExcludedName)
    $copy = [ordered]@{}
    foreach ($property in $Object.PSObject.Properties) {
        if ($property.Name -ne $ExcludedName) { $copy[$property.Name] = $property.Value }
    }
    return $copy
}

function Test-SafeRelativePath {
    param($Value)
    if (-not ($Value -is [string]) -or [string]::IsNullOrWhiteSpace($Value)) { return $false }
    if ($Value.Contains('\') -or $Value.StartsWith('/') -or $Value -match '(^|/)\.\.(/|$)') { return $false }
    return $true
}

function Validate-FileReceipt {
    param($Entry, [string]$CodePrefix)
    if ($null -eq $Entry) { Add-Finding "$CodePrefix.missing" "Filreceipt mangler"; return }
    $path = [string](Get-PropertyValue $Entry "path")
    if (-not (Test-SafeRelativePath $path)) { Add-Finding "$CodePrefix.path" "Usikker filsti: $path"; return }
    $full = Join-Path $script:RepoRootResolved ($path.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { Add-Finding "$CodePrefix.file" "Filen mangler: $path"; return }
    $item = Get-Item -LiteralPath $full
    if ([int64](Get-PropertyValue $Entry "size_bytes") -ne [int64]$item.Length) { Add-Finding "$CodePrefix.size" "Filstørrelsen matcher ikke: $path" }
    $expected = [string](Get-PropertyValue $Entry "sha256")
    $actual = "sha256:$((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant())"
    if (-not (Test-Sha256 $expected) -or $expected -ne $actual) { Add-Finding "$CodePrefix.hash" "Filhash matcher ikke: $path" }
}

function Validate-MutationDigests {
    param($Mutations)
    foreach ($mutation in @($Mutations)) {
        $mode = [string](Get-PropertyValue $mutation "mode")
        $claimed = [string](Get-PropertyValue $mutation "receipt_sha256")
        if (-not (Test-Sha256 $claimed)) { Add-Finding "mutation.$mode.digest-format" "Mutation digest mangler eller er ugyldig"; continue }
        $without = Get-ObjectWithoutProperty -Object $mutation -ExcludedName "receipt_sha256"
        $compact = $without | ConvertTo-Json -Depth 30 -Compress
        $actual = Get-Sha256ForText $compact
        if ($actual -ne $claimed) { Add-Finding "mutation.$mode.digest-mismatch" "Mutation digest matcher ikke indholdet" }
    }
}

function Validate-ExactTrialInventory {
    param($Trials)
    if ($null -eq $Trials) { Add-Finding "trials.missing" "Trials mangler"; return }
    $observed = @($Trials.PSObject.Properties | ForEach-Object { $_.Name })
    foreach ($name in $script:RequiredTrials) {
        if ($observed -notcontains $name) { Add-Finding "trials.required" "Manglende checkpoint: $name" }
    }
    foreach ($name in $observed) {
        if ($script:RequiredTrials -notcontains $name) { Add-Finding "trials.unknown" "Ukendt checkpoint: $name" }
    }
    if ($observed.Count -ne $script:RequiredTrials.Count) {
        Add-Finding "trials.count" "Checkpoint-inventory skal være præcis 21"
    }
}

function Validate-ScreenshotEvidence {
    param($Trials)
    $validated = 0
    foreach ($name in $script:RequiredTrials) {
        $trial = Get-PropertyValue $Trials $name
        if ($null -eq $trial) { continue }
        $screenshot = Get-PropertyValue $trial "screenshot"
        if ($null -ne $screenshot) {
            Validate-FileReceipt -Entry $screenshot -CodePrefix "trial.$name.screenshot"
            $validated++
        }
    }
    foreach ($name in $script:UiEvidenceTrials) {
        $trial = Get-PropertyValue $Trials $name
        if ($null -eq $trial) { continue }
        $screenshot = Get-PropertyValue $trial "screenshot"
        $note = [string](Get-PropertyValue $trial "note")
        if ($null -eq $screenshot -and [string]::IsNullOrWhiteSpace($note)) {
            Add-Finding "trial.$name.ui-evidence" "$name mangler både screenshot og konkret UI-note"
        }
    }
    if ($validated -eq 0) { Add-Finding "screenshots.none" "Mindst ét redigeret screenshot-bevis er obligatorisk" }
}

function Test-PrivateIpv4 {
    param([string]$Address)
    return (
        $Address -match '^10\.' -or
        $Address -match '^192\.168\.' -or
        $Address -match '^172\.(1[6-9]|2[0-9]|3[01])\.'
    )
}

function Validate-SafetyHardening {
    param($Safety, $Pixel)
    if ($null -eq $Safety) { Add-Finding "safety.missing" "safety_hardening mangler"; return }
    if ([string](Get-PropertyValue $Safety "schema") -ne "modelrig-agent4/physical-read-safety-evidence/v1") { Add-Finding "safety.schema" "Forkert safety schema" }
    foreach ($name in @("physical_pixel", "artifacts_hashed_after_prestop")) {
        if ((Get-PropertyValue $Safety $name) -ne $true) { Add-Finding "safety.$name" "$name skal være true" }
    }
    foreach ($name in @("wildcard_binding", "public_network", "production_activation")) {
        if ((Get-PropertyValue $Safety $name) -ne $false) { Add-Finding "safety.$name" "$name skal være false" }
    }
    $serialHash = Get-PropertyValue $Safety "pixel_serial_sha256"
    if (-not (Test-Sha256 $serialHash)) { Add-Finding "safety.pixel-serial" "Pixel serial-hash er ugyldig" }
    $model = [string](Get-PropertyValue $Safety "pixel_model")
    if ($model -notmatch '^Pixel\b') { Add-Finding "safety.pixel-model" "Safety-beviset dokumenterer ikke en Pixel" }
    if ($null -ne $Pixel -and $model -ne [string](Get-PropertyValue $Pixel "model")) { Add-Finding "safety.pixel-mismatch" "Top-level Pixel og safety-bevis er forskellige" }
    $backend = [string](Get-PropertyValue $Safety "backend_bound_address")
    $firewall = [string](Get-PropertyValue $Safety "firewall_local_address")
    if (-not (Test-PrivateIpv4 $backend) -or $backend -ne $firewall) { Add-Finding "safety.backend-bind" "Backend/firewall er ikke bundet til samme private IPv4" }
    if ([string](Get-PropertyValue $Safety "worker_bound_address") -ne "127.0.0.1") { Add-Finding "safety.worker-bind" "Worker er ikke dokumenteret på loopback" }
    if ([string](Get-PropertyValue $Safety "firewall_remote_scope") -ne "LocalSubnet") { Add-Finding "safety.firewall-scope" "Firewall scope er ikke LocalSubnet" }
    if ([string](Get-PropertyValue $Safety "network_profile") -eq "Public") { Add-Finding "safety.network-profile" "Public netværksprofil er ikke tilladt" }
    Validate-FileReceipt -Entry (Get-PropertyValue $Safety "binding_file") -CodePrefix "safety.binding-file"
}

try {
    $script:RepoRootResolved = (Resolve-Path -LiteralPath $RepoRoot).Path
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Validate-MutationDigests (Get-PropertyValue $receipt "mutations")
    $trials = Get-PropertyValue $receipt "trials"
    Validate-ExactTrialInventory $trials
    Validate-ScreenshotEvidence $trials
    Validate-SafetyHardening (Get-PropertyValue $receipt "safety_hardening") (Get-PropertyValue $receipt "pixel")

    $errors = @($Findings)
    $report = [ordered]@{
        schema = "modelrig-agent4/physical-read-audit-hardening/v1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        verdict = if ($errors.Count -eq 0) { "PASS" } else { "FAIL" }
        error_count = $errors.Count
        findings = $errors
        receipt_sha256 = "sha256:$((Get-FileHash -LiteralPath $ReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant())"
        credential_data_included = $false
        production_activation = $false
    }
    $parent = Split-Path -Parent $OutputPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Write-Host "A4-18 RECEIPT HARDENING AUDIT: $($report.verdict)" -ForegroundColor $(if ($errors.Count -eq 0) { "Green" } else { "Red" })
    foreach ($finding in $errors) { Write-Host "[ERROR] $($finding.code): $($finding.message)" }
    if ($errors.Count -ne 0) { exit 2 }
    exit 0
}
catch {
    Write-Error "A4-18 hardening-auditoren kunne ikke gennemføre: $($_.Exception.Message)"
    exit 3
}
