$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$processEntry = Join-Path $PSScriptRoot "agent4-physical-read-process.ps1"
if (-not (Test-Path -LiteralPath $processEntry -PathType Leaf)) {
    throw "A4-18 process-entrypoint mangler: $processEntry"
}

# Kompatibilitetssti for tidlige launchers. Record og Finalize routes aldrig her;
# den stabile operator-wrapper sender dem til deres isolerede entrypoints.
& $processEntry @args
if (-not $?) { exit 1 }
exit 0
