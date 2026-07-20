[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Url
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$operatorScript = Join-Path $repoRoot "scripts\browser_peer_public_validation_operator.py"

if (-not (Test-Path -LiteralPath $operatorScript -PathType Leaf)) {
    throw "Operator script not found: $operatorScript"
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "Python was not found on PATH."
}

$git = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $git) {
    throw "Git was not found on PATH."
}

Push-Location $repoRoot
try {
    $dirty = @(& $git.Source status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the candidate working tree."
    }
    if ($dirty.Count -ne 0) {
        throw "Candidate working tree is not clean. Commit, stash or remove local changes before physical validation."
    }

    & $git.Source fetch --quiet origin main
    if ($LASTEXITCODE -ne 0) {
        throw "Could not fetch the current origin/main reference. No physical evidence was created."
    }

    $candidateSha = (& $git.Source rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $candidateSha -notmatch '^[0-9a-f]{40}$') {
        throw "Candidate HEAD is unavailable or malformed."
    }

    $mainSha = (& $git.Source rev-parse origin/main).Trim()
    if ($LASTEXITCODE -ne 0 -or $mainSha -notmatch '^[0-9a-f]{40}$') {
        throw "Fetched origin/main is unavailable or malformed."
    }

    & $git.Source merge-base --is-ancestor $mainSha $candidateSha
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate HEAD $candidateSha does not contain fetched origin/main $mainSha. Reconcile the integration candidate before physical validation."
    }

    Write-Host "Candidate:   $candidateSha"
    Write-Host "Main anchor: $mainSha"

    & $python.Source $operatorScript --url $Url
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    throw "Physical browser peer validation was blocked or failed (exit $exitCode)."
}
