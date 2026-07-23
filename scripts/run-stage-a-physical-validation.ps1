[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Prepare", "Verify", "Complete")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedSha,

    [string]$Url,

    [ValidateRange(1, 720)]
    [double]$MaxAgeHours = 168,

    [ValidateRange(0, 1)]
    [double]$MinModelExact = 1.0
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$operatorScript = Join-Path $repoRoot "scripts\stage_a_physical_operator.py"

if (-not (Test-Path -LiteralPath $operatorScript -PathType Leaf)) {
    throw "Stage A operator script not found: $operatorScript"
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "Python was not found on PATH."
}

$normalizedAction = $Action.ToLowerInvariant()
if ($normalizedAction -eq "complete" -and [string]::IsNullOrWhiteSpace($Url)) {
    throw "Complete requires -Url with one exact pre-approved HTTPS/443 URL."
}
if ($normalizedAction -ne "complete" -and -not [string]::IsNullOrWhiteSpace($Url)) {
    throw "-Url is only valid with -Action Complete."
}

$arguments = @(
    $operatorScript,
    $normalizedAction,
    "--expected-sha", $ExpectedSha,
    "--max-age-hours", $MaxAgeHours.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--min-model-exact", $MinModelExact.ToString([Globalization.CultureInfo]::InvariantCulture)
)
if ($normalizedAction -eq "complete") {
    $arguments += @("--url", $Url)
}

Push-Location $repoRoot
try {
    & $python.Source @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    throw "Stage A physical validation was blocked or failed (exit $exitCode)."
}
