param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("PASS", "FAIL")]
    [string]$Decision,
    [Parameter(Mandatory = $true)]
    [string]$Reviewer,
    [switch]$Navigation,
    [switch]$WindowChrome,
    [switch]$PairingLabels,
    [switch]$TokenMasking,
    [switch]$LightMode,
    [switch]$ActionLog,
    [switch]$ControlCenter,
    [string]$JarPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-AuthorityValue {
    param([hashtable]$Map, [string]$Key)
    if (-not $Map.ContainsKey($Key) -or [string]::IsNullOrWhiteSpace([string]$Map[$Key])) {
        throw "Missing authority field: $Key"
    }
    return [string]$Map[$Key]
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$authorityPath = Join-Path $root "REVIEW_AUTHORITY.txt"
if (-not (Test-Path -LiteralPath $authorityPath -PathType Leaf)) {
    throw "REVIEW_AUTHORITY.txt is missing from the review kit."
}

$authority = @{}
foreach ($line in Get-Content -LiteralPath $authorityPath -Encoding UTF8) {
    if ($line -match '^([a-zA-Z0-9_]+)=(.*)$') {
        $authority[$matches[1]] = $matches[2].Trim()
    }
}

$expectedSha = Require-AuthorityValue $authority "exact_candidate_sha"
$expectedTree = Require-AuthorityValue $authority "exact_candidate_tree"
$expectedJarHash = (Require-AuthorityValue $authority "jar_sha256").ToLowerInvariant()

if ($expectedSha -ne "4a39edcfc857dbd3efae27caec02ec7a47507db7") {
    throw "Review authority is not the expected ModelRig #1370 candidate SHA."
}
if ($expectedTree -ne "1934fbfb65aa4532d6d4ac2ec213d26b5951fdab") {
    throw "Review authority is not the expected ModelRig #1370 candidate tree."
}
if ($expectedJarHash -notmatch '^[0-9a-f]{64}$') {
    throw "Review authority contains an invalid JAR SHA-256."
}
foreach ($field in @("production_activation", "promotion_authority", "release_authority", "merge_authority")) {
    if ((Require-AuthorityValue $authority $field) -ne "false") {
        throw "Review kit unexpectedly carries $field authority."
    }
}

if ([string]::IsNullOrWhiteSpace($JarPath)) {
    $jars = @(Get-ChildItem -LiteralPath $root -Filter "Kaliv-windows-x64-*-review-*.jar" -File)
    if ($jars.Count -ne 1) {
        throw "Expected exactly one review JAR in the kit; found $($jars.Count)."
    }
    $JarPath = $jars[0].FullName
} else {
    $JarPath = (Resolve-Path -LiteralPath $JarPath).Path
}

$actualJarHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $JarPath).Hash.ToLowerInvariant()
if ($actualJarHash -ne $expectedJarHash) {
    throw "JAR SHA-256 mismatch. This review cannot authorize another artifact."
}
if ([string]::IsNullOrWhiteSpace($Reviewer)) {
    throw "Reviewer must be non-empty."
}

$checks = [ordered]@{
    navigation_reachable = [bool]$Navigation
    native_window_chrome_only = [bool]$WindowChrome
    pairing_controls_labelled = [bool]$PairingLabels
    device_token_masked_by_default = [bool]$TokenMasking
    light_mode_readable = [bool]$LightMode
    action_log_human_readable = [bool]$ActionLog
    control_center_identifies_attention = [bool]$ControlCenter
}

$allPassed = $true
foreach ($value in $checks.Values) {
    if ($value -ne $true) { $allPassed = $false }
}
if ($Decision -eq "PASS" -and -not $allPassed) {
    throw "PASS requires all seven original #779 acceptance checks. Record FAIL or complete every check."
}

$authorized = ($Decision -eq "PASS" -and $allPassed)
$receipt = [ordered]@{
    format = "modelrig-windows-human-ux-review"
    version = 1
    recorded_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    reviewer = $Reviewer.Trim()
    decision = $Decision
    source_pr = 1370
    source_issue = 779
    exact_candidate_sha = $expectedSha
    exact_candidate_tree = $expectedTree
    artifact_name = [IO.Path]::GetFileName($JarPath)
    artifact_sha256 = $actualJarHash
    checks = $checks
    all_required_checks_passed = $allPassed
    human_ux_review_recorded = $true
    human_ux_review_authorized = $authorized
    exact_head_software_qualification_required_separately = $true
    merge_authority = $false
    release_authority = $false
    production_activation = $false
}

$receiptPath = Join-Path $root "HUMAN_UX_REVIEW_RECEIPT.json"
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receiptHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $receiptPath).Hash.ToLowerInvariant()
Write-Host "Human UX review receipt: $receiptPath"
Write-Host "Receipt SHA-256: $receiptHash"
Write-Host "Human UX authorized: $authorized"

if ($Decision -eq "FAIL") { exit 2 }
