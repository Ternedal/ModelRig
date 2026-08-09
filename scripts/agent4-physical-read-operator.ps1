$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$action = $null
for ($index = 0; $index -lt $args.Count; $index++) {
    if ([string]$args[$index] -ieq "-Action" -and $index + 1 -lt $args.Count) {
        $action = [string]$args[$index + 1]
        break
    }
}

$target = switch ($action) {
    "Record" { Join-Path $PSScriptRoot "agent4-physical-read-record.ps1" }
    "Finalize" { Join-Path $PSScriptRoot "agent4-physical-read-finalize.ps1" }
    default { Join-Path $PSScriptRoot "agent4-physical-read-operator-core.ps1" }
}
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw "A4-18 operator-entrypoint mangler: $target"
}

# Bevar alle navngivne argumenter ordret. Processtyring, observation og receipt
# har separate entrypoints, men launcherne har én stabil fil at kalde.
& $target @args
if (-not $?) { exit 1 }
exit 0
