[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ReceiptPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
    throw "Receipt mangler: $ReceiptPath"
}

$receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sdk = [string]$receipt.pixel.sdk
if ($sdk -notmatch '^[0-9]+$') {
    throw "Pixel SDK skal være numerisk."
}

Write-Host "A4-18 PIXEL SDK AUDIT: PASS" -ForegroundColor Green
exit 0
