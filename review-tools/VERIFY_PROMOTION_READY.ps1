param(
    [string]$ReceiptPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$expectedSha = "4a39edcfc857dbd3efae27caec02ec7a47507db7"
$expectedTree = "1934fbfb65aa4532d6d4ac2ec213d26b5951fdab"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ReceiptPath)) {
    $ReceiptPath = Join-Path $root "HUMAN_UX_REVIEW_RECEIPT.json"
}
$ReceiptPath = (Resolve-Path -LiteralPath $ReceiptPath).Path

try {
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20
} catch {
    throw "Human UX receipt is unreadable JSON: $ReceiptPath"
}
if ([string]$receipt.format -ne "modelrig-windows-human-ux-review" -or [int]$receipt.version -ne 1) {
    throw "Human UX receipt format/version mismatch."
}
if ([string]$receipt.exact_candidate_sha -ne $expectedSha -or [string]$receipt.exact_candidate_tree -ne $expectedTree) {
    throw "Human UX receipt targets another candidate."
}
if ($receipt.human_ux_review_recorded -ne $true -or $receipt.human_ux_review_authorized -ne $true) {
    throw "Human UX review is not authorized."
}
if ($receipt.all_required_checks_passed -ne $true -or [string]$receipt.decision -ne "PASS") {
    throw "Human UX receipt does not contain a complete PASS."
}
if ($receipt.merge_authority -ne $false -or $receipt.release_authority -ne $false -or $receipt.production_activation -ne $false) {
    throw "Human UX receipt crossed its authority boundary."
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
    software_qualification_complete = $true
    human_ux_review_complete = $true
    human_ux_review_receipt_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ReceiptPath).Hash.ToLowerInvariant()
    verified_runs = $verifiedRuns
    promotion_ready = $true
    merge_authority = $false
    release_authority = $false
    production_activation = $false
}

$out = Join-Path $root "PROMOTION_READINESS.json"
$readiness | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Host "Promotion readiness: $out"
Write-Host "SHA-256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $out).Hash.ToLowerInvariant())"
Write-Host "promotion_ready=true (human merge/release decision still required)"
