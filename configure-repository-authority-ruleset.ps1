param(
    [switch]$Apply,
    [switch]$RemoveClassicProtection,
    [string]$Python = ""
)

# ADR-SYS-003 step 2/3: apply the versioned ruleset deploy/repository-authority/
# main-ruleset.json to Ternedal/ModelRig main, replacing classic branch
# protection with a merge-queue ruleset. Mirrors configure-repository-authority.ps1:
# exact clean main checkout, local HEAD == GitHub main, dry run by default,
# the live checkout-bound verifier runs after any write.
#
# Order of operations when applied (fail-closed in both directions):
#   1. the JSON is evaluated OFFLINE by scripts/repository_authority.py and must
#      PASS in ruleset mode without warnings -- a ruleset that would fail gate
#      10 is never sent;
#   2. the ruleset is created (or updated, if one with the same name exists);
#   3. classic protection is removed only with -RemoveClassicProtection, and
#      only after the ruleset write succeeded (a window with both is safe; a
#      window with neither is not);
#   4. verify-repository-authority.ps1 must PASS in ruleset mode.

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

# This script lives in the repository ROOT, beside configure-repository-authority.ps1
# and verify-repository-authority.ps1 (not under scripts/); $PSScriptRoot is the root.
$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Repository-authority ruleset configuration must run from branch main."
}
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Repository-authority ruleset configuration requires an exact clean main checkout."
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
$rulesetFile = [IO.Path]::GetFullPath((Join-Path $repoRoot "deploy\repository-authority\main-ruleset.json"))
if (-not (Test-Path -LiteralPath $rulesetFile -PathType Leaf)) {
    throw "Versioned ruleset is missing from this checkout: $rulesetFile"
}

# 1. Offline evaluation of the versioned ruleset with the checkout's own evaluator.
$offlineCode = @'
import importlib.util, json, pathlib, sys
evaluator = pathlib.Path(sys.argv[1]).resolve()
ruleset = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("modelrig_repository_authority", evaluator)
if spec is None or spec.loader is None:
    raise SystemExit(2)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
result = m.evaluate_rulesets([ruleset])
print(json.dumps({"passed": result["passed"], "merge_queue": result.get("merge_queue", False),
                  "errors": result["errors"], "warnings": result["warnings"],
                  "name": ruleset.get("name", ""), "bypass_actors": ruleset.get("bypass_actors", None)}, separators=(",", ":")))
'@
$offlineRaw = @(& $Python -c $offlineCode $evaluator $rulesetFile 2>&1)
if ($LASTEXITCODE -ne 0 -or $offlineRaw.Count -ne 1) { throw "Could not evaluate the versioned ruleset offline." }
try { $offline = ([string]$offlineRaw[0]) | ConvertFrom-Json -Depth 20 }
catch { throw "Offline ruleset evaluation output was unreadable." }
if (-not $offline.passed -or $offline.warnings.Count -gt 0 -or -not $offline.merge_queue) {
    throw ("The versioned ruleset would not PASS gate 10 in ruleset mode (errors: " + ($offline.errors -join "; ") + "; warnings: " + ($offline.warnings -join "; ") + "). Nothing was sent.")
}
if ($null -eq $offline.bypass_actors -or @($offline.bypass_actors).Count -ne 0) {
    throw "The versioned ruleset must declare an empty bypass_actors list. Nothing was sent."
}
$rulesetName = [string]$offline.name
if ([string]::IsNullOrWhiteSpace($rulesetName)) { throw "The versioned ruleset has no name." }

# Migration prerequisite (Codex P1 on #2429): a merge queue reports required
# checks only from workflows with a merge_group trigger. Every workflow that
# produces a queue-required context must carry it in THIS checkout, or queued
# PRs would wait forever. Checked here, before anything is sent.
$triggerCode = @'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
producers = {
    "ci.yml": ("test / test", "test / test-windows-appliance", "test / test-windows-tool-isolation",
               "browser-use-runtime-contract", "android-compile", "desktop-compile",
               "desktop-dpapi-windows", "agent3-memory-dpapi-windows"),
    "codeql.yml": ("analyze (go)", "analyze (python)"),
    "agent3-diagnostics.yml": ("agent3-python",),
    "agent3-full-diagnostics.yml": ("full-test-log",),
    "exact-head-qualification.yml": ("exact-head-core", "legacy-merge-tree-equivalence", "stage-b-verdict"),
    "freeze-guard.yml": ("freeze-guard",),
}
missing = []
for name in producers:
    text = (root / ".github" / "workflows" / name).read_text(encoding="utf-8").split("jobs:", 1)[0]
    if not re.search(r"(?m)^  merge_group:\n(?:    .*\n)*?    types: \[checks_requested\]", text):
        missing.append(name)
print(",".join(missing))
'@
$missingRaw = @(& $Python -c $triggerCode $repoRoot 2>&1)
if ($LASTEXITCODE -ne 0 -or $missingRaw.Count -ne 1) { throw "Could not check the workflows for merge_group triggers." }
$missingTriggers = [string]$missingRaw[0]
if (-not [string]::IsNullOrWhiteSpace($missingTriggers)) {
    throw "Merge-queue prerequisite missing: these required-check workflows have no merge_group trigger in this checkout: $missingTriggers. A queue would wait forever for their checks. Nothing was sent."
}

# Local HEAD must be GitHub main: the ruleset is applied from the commit that carries it.
$branch = Invoke-GhJson -ApiPath "repos/Ternedal/ModelRig/branches/main"
$githubHead = Need-Revision -Value ([string]$branch.commit.sha) -Label "GitHub main HEAD"
if ([string]$branch.name -ne "main") { throw "GitHub branch payload is not main." }
if ($githubHead -cne $head) {
    throw "GitHub main does not match the exact local checkout. Expected $head, got $githubHead."
}

$existingPayload = Invoke-GhJson -ApiPath "repos/Ternedal/ModelRig/rulesets?includes_parents=false" -AllowFailure
$existing = if ($null -eq $existingPayload) { @() } else { @($existingPayload) }
$sameName = @($existing | Where-Object { [string]$_.name -eq $rulesetName })
$otherActive = @($existing | Where-Object { [string]$_.name -ne $rulesetName -and [string]$_.enforcement -eq "active" -and [string]$_.target -eq "branch" })
if ($otherActive.Count -gt 0) {
    throw ("Other active branch rulesets exist (" + (($otherActive | ForEach-Object { "$($_.id):$($_.name)" }) -join ", ") + "). ADR-SYS-003 D1 requires exactly one; review them first. Nothing was sent.")
}
$classic = Invoke-GhJson -ApiPath "repos/Ternedal/ModelRig/branches/main/protection" -AllowFailure

# The versioned file carries a top-level "_comment" for readers; the REST API
# gets only the ruleset fields (name, target, enforcement, bypass_actors,
# conditions, rules). Anything else is a mistake in the file, not metadata.
$rulesetObject = Get-Content -LiteralPath $rulesetFile -Raw -Encoding utf8 | ConvertFrom-Json -Depth 60
$allowedTopLevel = @("name", "target", "enforcement", "bypass_actors", "conditions", "rules")
$payloadObject = [ordered]@{}
foreach ($property in $rulesetObject.PSObject.Properties) {
    if ($property.Name -eq "_comment") { continue }
    if ($allowedTopLevel -notcontains $property.Name) {
        throw "The versioned ruleset has an unexpected top-level field '$($property.Name)'. Only $($allowedTopLevel -join ', ') are sent. Nothing was sent."
    }
    $payloadObject[$property.Name] = $property.Value
}
foreach ($required in $allowedTopLevel) {
    if (-not $payloadObject.Contains($required)) { throw "The versioned ruleset lacks the required top-level field '$required'. Nothing was sent." }
}
$rulesetJson = $payloadObject | ConvertTo-Json -Depth 60
$method = if ($sameName.Count -eq 1) { "PUT" } else { "POST" }
$apiPath = if ($sameName.Count -eq 1) { "repos/Ternedal/ModelRig/rulesets/$($sameName[0].id)" } else { "repos/Ternedal/ModelRig/rulesets" }

if (-not $Apply) {
    Write-Host "ModelRig repository authority ruleset configuration: DRY RUN"
    Write-Host "Repository: Ternedal/ModelRig"
    Write-Host "Branch:     main"
    Write-Host "Head:       $head"
    Write-Host "Mode:       ruleset with merge queue (ADR-SYS-003)"
    Write-Host "Ruleset:    $rulesetName ($method $apiPath)"
    Write-Host ("Classic protection present: " + ($(if ($null -ne $classic) { "yes" } else { "no" })) + " (removed only with -RemoveClassicProtection, after the ruleset write)")
    Write-Host "Offline gate 10 evaluation of the versioned ruleset: PASS, no warnings"
    Write-Host "Payload:"
    Write-Host $rulesetJson
    Write-Host "No repository setting was changed. Re-run with -Apply using a GitHub identity with repository Administration: write."
    exit 0
}

# 2. Write the ruleset.
$tempPath = Join-Path ([IO.Path]::GetTempPath()) ("modelrig-repository-ruleset-" + [Guid]::NewGuid().ToString("N") + ".json")
try {
    $rulesetJson | Set-Content -LiteralPath $tempPath -Encoding utf8NoBOM
    $response = @(& gh api `
        --method $method `
        -H "Accept: application/vnd.github+json" `
        -H "X-GitHub-Api-Version: 2026-03-10" `
        $apiPath `
        --input $tempPath 2>&1)
    if ($LASTEXITCODE -ne 0) {
        # Show GitHub's own answer. 19/11: the generic permission text hid a
        # 422 "Invalid rule 'merge_queue'" (merge queue is organization-only;
        # this repository is user-owned) and cost a second diagnostic run.
        $body = ($response | ForEach-Object { "$_" }) -join [Environment]::NewLine
        throw ("GitHub ruleset write failed ($method $apiPath). Response:" + [Environment]::NewLine + $body + [Environment]::NewLine +
            "If the response is a 403, the authenticated gh identity needs repository Administration: write. " +
            "If it is 422 'Invalid rule ''merge_queue''', GitHub offers merge queues only in organization-owned repositories.")
    }
}
finally {
    if (Test-Path -LiteralPath $tempPath -PathType Leaf) { Remove-Item -LiteralPath $tempPath -Force }
}
Write-Host "Ruleset write completed ($method)."

# 3. Remove classic protection only when asked, and only now that the ruleset exists.
if ($null -ne $classic) {
    if ($RemoveClassicProtection) {
        @(& gh api --method DELETE -H "Accept: application/vnd.github+json" "repos/Ternedal/ModelRig/branches/main/protection" 2>&1) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "The ruleset was written, but classic branch protection could not be removed. main is protected by both; remove classic protection manually and re-run the verifier."
        }
        Write-Host "Classic branch protection removed; main is governed by the ruleset alone."
    }
    else {
        Write-Host "Classic branch protection is still present alongside the ruleset (strict + merge queue). Re-run with -RemoveClassicProtection to finish the migration."
    }
}

# 4. Live verification.
$verifier = Join-Path $repoRoot "verify-repository-authority.ps1"
if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
    throw "Repository-authority verifier is missing after ruleset write: $verifier"
}
Write-Host "Running live checkout-bound verifier."
& $verifier -Python $Python
if ($LASTEXITCODE -ne 0) {
    throw "The ruleset was written, but verify-repository-authority.ps1 did not PASS. Do not infer repository authority."
}
Write-Host "ModelRig repository authority ruleset configuration: PASS"
Write-Host "Authority: repository settings only; no Agent 3, physical validation, release or production activation."
exit 0
