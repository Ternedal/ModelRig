#Requires -Version 5.1
<#
.SYNOPSIS
  Parse every operator script with the Windows PowerShell 5.1 parser.

.DESCRIPTION
  The rig runs Windows PowerShell 5.1, not PowerShell 7. A script written or
  reviewed in pwsh can use syntax 5.1 rejects (the ternary operator, '??',
  '&&' pipeline chains, 'using namespace' placements) and nothing notices until
  the rig day. This check runs the 5.1 parser over every root *.ps1,
  scripts\*.ps1, scripts\rig_simulator\*.ps1 and deploy\*.ps1 and fails when
  any file has a parse error. tests/workflow_ps1_encoding.py parses the same
  files with pwsh 7 on Linux; this is the 5.1 parser the rig actually uses.

  It parses only. Nothing is executed, dot-sourced or imported.

.PARAMETER RepositoryRoot
  The checkout to scan. Defaults to the repository that holds this script.

.PARAMETER Report
  Optional path for a JSON report (one entry per file, errors with line and column).

.OUTPUTS
  Exit 0 when every file parses; 1 when any file has parse errors; 2 when the
  host is not Windows PowerShell 5.1, because a pass from another parser would
  prove nothing about the rig.
#>
[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$Report
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if ($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -ne 5) {
    Write-Host ("ps51_parse_check: host is {0} {1}, not Windows PowerShell 5.1; refusing to vouch for the rig's parser." -f $PSVersionTable.PSEdition, $PSVersionTable.PSVersion)
    exit 2
}

$files = @()
foreach ($pattern in @('*.ps1', 'scripts\*.ps1', 'scripts\rig_simulator\*.ps1', 'deploy\*.ps1')) {
    $files += Get-ChildItem -Path (Join-Path $RepositoryRoot $pattern) -File -ErrorAction SilentlyContinue
}
$files = $files | Sort-Object FullName

$entries = @()
$failed = 0
foreach ($file in $files) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    $relative = $file.FullName.Substring($RepositoryRoot.Length).TrimStart('\', '/') -replace '\\', '/'
    $problems = @()
    foreach ($err in @($errors)) {
        $problems += [ordered]@{
            line    = $err.Extent.StartLineNumber
            column  = $err.Extent.StartColumnNumber
            id      = $err.ErrorId
            message = $err.Message
        }
    }
    if ($problems.Count -gt 0) {
        $failed += 1
        Write-Host ("PARSE FAIL {0}" -f $relative)
        foreach ($p in $problems) { Write-Host ("    {0}:{1} {2}" -f $p.line, $p.column, $p.message) }
    }
    $entries += [ordered]@{ file = $relative; errors = $problems }
}

$result = [ordered]@{
    schema        = 'kaliv-rig-simulator-ps51-parse/v1'
    host          = ('{0} {1}' -f $PSVersionTable.PSEdition, $PSVersionTable.PSVersion)
    files_checked = $files.Count
    files_failed  = $failed
    ok            = ($failed -eq 0 -and $files.Count -gt 0)
    entries       = $entries
}
$json = $result | ConvertTo-Json -Depth 6
if ($Report) {
    $dir = Split-Path -Parent $Report
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Report, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
}
Write-Host ("ps51_parse_check: {0} files, {1} with parse errors" -f $files.Count, $failed)
if ($result.ok) { exit 0 } else { exit 1 }
