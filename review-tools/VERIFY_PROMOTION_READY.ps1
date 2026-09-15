param(
    [string]$ReceiptPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$expectedSha = "4a39edcfc857dbd3efae27caec02ec7a47507db7"
$expectedTree = "1934fbfb65aa4532d6d4ac2ec213d26b5951fdab"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-NumericExact {
    param([AllowNull()]$Value, [double]$Expected)
    if ($null -eq $Value -or $Value -is [bool]) { return $false }
    try { $typeCode = [Type]::GetTypeCode($Value.GetType()) } catch { return $false }
    $numericTypes = @(
        [TypeCode]::Byte,[TypeCode]::Decimal,[TypeCode]::Double,[TypeCode]::Int16,
        [TypeCode]::Int32,[TypeCode]::Int64,[TypeCode]::SByte,[TypeCode]::Single,
        [TypeCode]::UInt16,[TypeCode]::UInt32,[TypeCode]::UInt64
    )
    if ($numericTypes -notcontains $typeCode) { return $false }
    $number = [double]$Value
    return (-not [double]::IsNaN($number)) -and (-not [double]::IsInfinity($number)) -and $number -eq $Expected
}

function Require-StrictBool {
    param([AllowNull()]$Value, [bool]$Expected, [string]$Label)
    if ($Value -isnot [bool] -or [bool]$Value -ne $Expected) {
        throw "$Label must be strict boolean $Expected."
    }
}

function Read-Authority {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing review authority: $Path" }
    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match '^([a-zA-Z0-9_]+)=(.*)$') { $map[$matches[1]] = $matches[2].Trim() }
    }
    return $map
}

if ([string]::IsNullOrWhiteSpace($ReceiptPath)) {
    $ReceiptPath = Join-Path $root "HUMAN_UX_REVIEW_RECEIPT.json"
}
$ReceiptPath = (Resolve-Path -LiteralPath $ReceiptPath).Path
$receiptDir = Split-Path -Parent $ReceiptPath

try {
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20
} catch {
    throw "Human UX receipt is unreadable JSON: $ReceiptPath"
}
if ([string]$receipt.format -ne "modelrig-windows-human-ux-review" -or -not (Test-NumericExact -Value $receipt.version -Expected 1)) {
    throw "Human UX receipt format/version mismatch."
}
if ([string]$receipt.exact_candidate_sha -ne $expectedSha -or [string]$receipt.exact_candidate_tree -ne $expectedTree) {
    throw "Human UX receipt targets another candidate."
}
Require-StrictBool -Value $receipt.human_ux_review_recorded -Expected $true -Label "human_ux_review_recorded"
Require-StrictBool -Value $receipt.human_ux_review_authorized -Expected $true -Label "human_ux_review_authorized"
Require-StrictBool -Value $receipt.all_required_checks_passed -Expected $true -Label "all_required_checks_passed"
Require-StrictBool -Value $receipt.exact_head_software_qualification_required_separately -Expected $true -Label "exact_head_software_qualification_required_separately"
Require-StrictBool -Value $receipt.merge_authority -Expected $false -Label "merge_authority"
Require-StrictBool -Value $receipt.release_authority -Expected $false -Label "release_authority"
Require-StrictBool -Value $receipt.production_activation -Expected $false -Label "production_activation"
if ([string]$receipt.decision -ne "PASS") { throw "Human UX receipt does not contain PASS." }

foreach ($checkName in @(
    "navigation_reachable",
    "native_window_chrome_only",
    "pairing_controls_labelled",
    "device_token_masked_by_default",
    "light_mode_readable",
    "action_log_human_readable",
    "control_center_identifies_attention"
)) {
    $property = $receipt.checks.PSObject.Properties[$checkName]
    if ($null -eq $property) { throw "Human UX receipt is missing required check: $checkName" }
    Require-StrictBool -Value $property.Value -Expected $true -Label "checks.$checkName"
}

$artifactName = [string]$receipt.artifact_name
if ([string]::IsNullOrWhiteSpace($artifactName) -or [IO.Path]::GetFileName($artifactName) -ne $artifactName) {
    throw "Human UX receipt contains an invalid artifact_name."
}
$artifactPath = Join-Path $receiptDir $artifactName
if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
    throw "Reviewed JAR is missing: $artifactPath"
}
$receiptArtifactHash = ([string]$receipt.artifact_sha256).ToLowerInvariant()
if ($receiptArtifactHash -notmatch '^[0-9a-f]{64}$') { throw "Human UX receipt has invalid artifact_sha256." }
$actualArtifactHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifactPath).Hash.ToLowerInvariant()
if ($actualArtifactHash -ne $receiptArtifactHash) {
    throw "Reviewed JAR no longer matches the human UX receipt."
}

$authority = Read-Authority -Path (Join-Path $receiptDir "REVIEW_AUTHORITY.txt")
foreach ($key in @("exact_candidate_sha","exact_candidate_tree","jar_sha256","merge_authority","release_authority","promotion_authority","production_activation")) {
    if (-not $authority.ContainsKey($key)) { throw "Review authority is missing $key." }
}
if ([string]$authority.exact_candidate_sha -ne $expectedSha -or [string]$authority.exact_candidate_tree -ne $expectedTree) {
    throw "Review authority targets another candidate."
}
if (([string]$authority.jar_sha256).ToLowerInvariant() -ne $actualArtifactHash) {
    throw "Reviewed JAR no longer matches REVIEW_AUTHORITY.txt."
}
foreach ($field in @("merge_authority","release_authority","promotion_authority","production_activation")) {
    if ([string]$authority[$field] -ne "false") { throw "Review authority unexpectedly carries $field." }
}

$runs = [ordered]@{
    ci = 35006152792
    exact_head_qualification = 35006152244
    agent3_diagnostics = 35006152121
    agent3_full_diagnostics = 35006152300
    windows_protected_store = 35006152183
    codeql = 35006152229
    loc_metrics = 35006152252
    agent4_a4_18r = 35006152295
    agent4_a4_25f = 35006152132
    control_center_a11y = 35006152209
}

$headers = @{
    Accept = "application/vnd.github+json"
    "User-Agent" = "ModelRig-promotion-verifier"
    "X-GitHub-Api-Version" = "2022-11-28"
}
if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
    $headers.Authorization = "Bearer $($env:GITHUB_TOKEN)"
}

$verifiedRuns = [ordered]@{}
foreach ($name in $runs.Keys) {
    $runId = [long]$runs[$name]
    $uri = "https://api.github.com/repos/Ternedal/ModelRig/actions/runs/$runId"
    try {
        $run = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers
    } catch {
        throw "Could not verify GitHub Actions run $name ($runId): $($_.Exception.Message)"
    }
    if ([string]$run.head_sha -ne $expectedSha) {
        throw "Run $name ($runId) belongs to another head: $($run.head_sha)"
    }
    if ([string]$run.status -ne "completed" -or [string]$run.conclusion -ne "success") {
        throw "Run $name ($runId) is not successful: status=$($run.status) conclusion=$($run.conclusion)"
    }
    $verifiedRuns[$name] = [ordered]@{
        run_id = $runId
        status = [string]$run.status
        conclusion = [string]$run.conclusion
        head_sha = [string]$run.head_sha
    }
}

$readiness = [ordered]@{
    format = "modelrig-promotion-readiness"
    version = 1
    verified_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    exact_candidate_sha = $expectedSha
    exact_candidate_tree = $expectedTree
    reviewed_artifact_name = $artifactName
    reviewed_artifact_sha256 = $actualArtifactHash
    software_qualification_complete = $true
    human_ux_review_complete = $true
    human_ux_review_receipt_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ReceiptPath).Hash.ToLowerInvariant()
    verified_runs = $verifiedRuns
    promotion_ready = $true
    merge_authority = $false
    release_authority = $false
    production_activation = $false
}

$out = Join-Path $receiptDir "PROMOTION_READINESS.json"
if (Test-Path -LiteralPath $out) { throw "Promotion readiness receipt already exists: $out" }
$readiness | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Host "Promotion readiness: $out"
Write-Host "SHA-256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $out).Hash.ToLowerInvariant())"
Write-Host "promotion_ready=true (human merge/release decision still required)"
