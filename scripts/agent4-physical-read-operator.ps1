$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$core = Join-Path $PSScriptRoot "agent4-physical-read-operator-core.ps1"
if (-not (Test-Path -LiteralPath $core -PathType Leaf)) {
    throw "A4-18 operator-core mangler: $core"
}

# Bevar alle navngivne argumenter ordret. Denne fil er kun den stabile launcher-
# indgang; al parsing, fasekontrol og credential-håndtering ligger i core-filen.
& $core @args
exit $LASTEXITCODE
