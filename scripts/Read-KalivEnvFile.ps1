# Read-KalivEnvFile.ps1 -- parse a modelrig.env file the way the appliance
# means it, not the way a naive regex reads it.
#
# The rig lost three days in August to an env mirror that matched
# ^KEY=(.*)$ and swallowed the trailing "# comment" into the VALUE, so
# MODELRIG_OLLAMA_URL pointed at "http://127.0.0.1:11434 # (worker reads...)"
# and Ollama answered 405 to everything. This is the one place that parsing
# lives now: comments stripped, whitespace trimmed, optional quotes removed,
# blank and comment-only lines ignored.
#
# Dot-source it, then: $env = Read-KalivEnvFile -Path "C:\...\modelrig.env"

function Read-KalivEnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    $result = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $result }
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = [string]$rawLine
        if ($line -match '^\s*(#|$)') { continue }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $key = $line.Substring(0, $eq).Trim()
        if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
        $value = $line.Substring($eq + 1)
        # A comment starts at the first '#' that is preceded by whitespace.
        # A '#' glued to a value is part of the value -- "COLOUR=#ff00ff" is a
        # colour, and "KEY=#x" is "#x" -- exactly the dotenv convention.
        $hash = $value.IndexOf('#')
        while ($hash -ge 0) {
            if ($hash -gt 0 -and [char]::IsWhiteSpace($value[$hash - 1])) {
                $value = $value.Substring(0, $hash)
                break
            }
            $hash = $value.IndexOf('#', $hash + 1)
        }
        $value = $value.Trim()
        if ($value.Length -ge 2) {
            $first = $value[0]; $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $result[$key] = $value
    }
    return $result
}
