param(
    [switch]$Apply,
    [switch]$ReplaceExistingProtection,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-Revision {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') { throw "$Label is not an exact Git revision." }
    return $normalized
}

function Invoke-GhJson {
    param(
        [Parameter(Mandatory = $true)][string]$ApiPath,
        [switch]$AllowFailure
    )
    $raw = @(& gh api $ApiPath 2>&1)
    if ($LASTEXITCODE -ne 0) {
        if ($AllowFailure) { return $null }
        throw "GitHub API read failed for repository-authority endpoint: $ApiPath"
    }
    try { return (($raw -join "`n") | ConvertFrom-Json -Depth 60) }
    catch { throw "GitHub API returned unreadable JSON for repository-authority endpoint: $ApiPath" }
}

if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ (pwsh) is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Repository-authority configuration must run from branch main."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Repository-authority configuration requires an exact clean main checkout."
}
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve ModelRig HEAD." }
$head = Need-Revision -Value ([string]$headRaw[0]) -Label "ModelRig HEAD"

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) { throw "GitHub CLI (gh) is required to configure repository authority." }
@(& gh auth status -h github.com 2>&1) | Out-Null
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated for github.com." }

if ([string]::IsNullOrWhiteSpace($Python)) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCmd) { throw "Python not found." }
    $Python = $pythonCmd.Source
}
$Python = (Resolve-Path -LiteralPath $Python).Path
$evaluator = [IO.Path]::GetFullPath((Join-Path $repoRoot "scripts\repository_authority.py"))
if (-not (Test-Path -LiteralPath $evaluator -PathType Leaf)) {
    throw "Repository-authority evaluator is missing from this checkout: $evaluator"
}

$policyCode = @'
import importlib.util, json, pathlib, sys
path = pathlib.Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location("modelrig_repository_authority", path)
if spec is None or spec.loader is None:
    raise SystemExit(2)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print(json.dumps({"app_id": m.REQUIRED_STATUS_CHECK_APP_ID, "checks": list(m.REQUIRED_STATUS_CHECKS)}, separators=(",", ":")))
'@
$policyRaw = @(& $Python -c $policyCode $evaluator 2>&1)
if ($LASTEXITCODE -ne 0 -or $policyRaw.Count -ne 1) { throw "Could not load the checkout-bound repository-authority policy." }
try { $policy = ([string]$policyRaw[0]) | ConvertFrom-Json -Depth 20 }
catch { throw "Repository-authority policy output was unreadable." }
$requiredStatusCheckAppId = [int]$policy.app_id
$requiredStatusChecks = @($policy.checks | ForEach-Object { [string]$_ })
if ($requiredStatusCheckAppId -ne 15368 -or $requiredStatusChecks.Count -lt 1) {
    throw "Repository-authority policy is invalid."
}

$branch = Invoke-GhJson -ApiPath "repos/Ternedal/ModelRig/branches/main"
$githubHead = Need-Revision -Value ([string]$branch.commit.sha) -Label "GitHub main HEAD"
if ([string]$branch.name -ne "main") { throw "GitHub branch payload is not main." }
if ($githubHead -cne $head) {
    throw "GitHub main does not match the exact local checkout. Expected $head, got $githubHead."
}

$rulesetPayload = Invoke-GhJson -ApiPath "repos/Ternedal/ModelRig/rulesets?includes_parents=true" -AllowFailure
$rulesets = if ($null -eq $rulesetPayload) { @() } else { @($rulesetPayload) }
if ($rulesets.Count -gt 0) {
    throw "Existing repository rulesets detected. Refusing to compose classic protection automatically; review them and use verify-repository-authority.ps1."
}

$classic = Invoke-GhJson -ApiPath "repos/Ternedal/ModelRig/branches/main/protection" -AllowFailure
if ($null -ne $classic -and -not $ReplaceExistingProtection) {
    throw "Classic branch protection already exists. Refusing to replace it without -ReplaceExistingProtection."
}

$checks = @()
foreach ($name in $requiredStatusChecks) {
    $checks += [ordered]@{ context = $name; app_id = $requiredStatusCheckAppId }
}

$payload = [ordered]@{
    required_status_checks = [ordered]@{ strict = $true; checks = $checks }
    enforce_admins = $true
    required_pull_request_reviews = [ordered]@{
        dismiss_stale_reviews = $false
        require_code_owner_reviews = $false
        required_approving_review_count = 0
        require_last_push_approval = $false
    }
    restrictions = $null
    required_linear_history = $false
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $false
    required_conversation_resolution = $true
    lock_branch = $false
    allow_fork_syncing = $false
}
$payloadJson = $payload | ConvertTo-Json -Depth 20

if (-not $Apply) {
    Write-Host "ModelRig repository authority configuration: DRY RUN"
    Write-Host "Repository: Ternedal/ModelRig"
    Write-Host "Branch:     main"
    Write-Host "Head:       $head"
    Write-Host "Mode:       classic branch protection"
    Write-Host "Required check source: GitHub Actions app $requiredStatusCheckAppId"
    Write-Host "Required approving reviews: 0 (PR still required)"
    Write-Host "Required checks:"
    foreach ($name in $requiredStatusChecks) { Write-Host "  - $name" }
    Write-Host "Payload:"
    Write-Host $payloadJson
    Write-Host "No repository setting was changed. Re-run with -Apply using a GitHub identity with repository Administration: write."
    exit 0
}

$tempPath = Join-Path ([IO.Path]::GetTempPath()) ("modelrig-repository-protection-" + [Guid]::NewGuid().ToString("N") + ".json")
try {
    $payloadJson | Set-Content -LiteralPath $tempPath -Encoding utf8NoBOM
    @(& gh api `
        --method PUT `
        -H "Accept: application/vnd.github+json" `
        -H "X-GitHub-Api-Version: 2026-03-10" `
        "repos/Ternedal/ModelRig/branches/main/protection" `
        --input $tempPath 2>&1) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub branch-protection update failed. The authenticated gh identity must have repository Administration: write."
    }
}
finally {
    if (Test-Path -LiteralPath $tempPath -PathType Leaf) { Remove-Item -LiteralPath $tempPath -Force }
}

$verifier = Join-Path $repoRoot "verify-repository-authority.ps1"
if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
    throw "Repository-authority verifier is missing after protection write: $verifier"
}
Write-Host "ModelRig repository protection write completed; running live checkout-bound verifier."
& $verifier -Python $Python
if ($LASTEXITCODE -ne 0) {
    throw "Protection was written, but verify-repository-authority.ps1 did not PASS. Do not infer repository authority."
}
Write-Host "ModelRig repository authority configuration: PASS"
Write-Host "Authority: repository settings only; no Agent 3, physical validation, release or production activation."
exit 0
