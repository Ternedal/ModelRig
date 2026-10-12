# Offline contract checks for the single-shot resource snapshot.
# Does not execute the snapshot, contact Ollama, or require GPU hardware.
$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot '..\scripts\resource_snapshot.ps1'
$source = Get-Content -LiteralPath $path -Raw
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "PowerShell parse errors: $($errors.Count)" }
if ($source -notmatch 'modelrig-resource-snapshot/v1') { throw 'Schema identifier missing' }
if ($source -notmatch '127\[\.\]0\[\.\]0\[\.\]1') { throw 'Loopback validation missing' }
if ($source -notmatch 'TimeoutSec 10') { throw 'Bounded Ollama timeout missing' }
if ($source -notmatch 'ConvertTo-Json') { throw 'JSON output missing' }
$commands = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst]
}, $true) | ForEach-Object { $_.GetCommandName() })
$forbidden = @('Invoke-Expression','Start-Process','Set-Content','Add-Content','Out-File','Remove-Item','Set-Item','New-Item','Invoke-WebRequest')
foreach ($name in $forbidden) {
    if ($commands -contains $name) { throw "Forbidden command in snapshot: $name" }
}
if (@($commands | Where-Object { $_ -eq 'Invoke-RestMethod' }).Count -ne 1) {
    throw 'Expected exactly one Ollama HTTP request'
}
Write-Output 'PASS: resource snapshot parses and matches offline read-only contract'
