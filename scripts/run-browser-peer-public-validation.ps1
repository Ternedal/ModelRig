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

Push-Location $repoRoot
try {
    & $python.Source $operatorScript --url $Url
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    throw "Physical browser peer validation was blocked or failed (exit $exitCode)."
}
