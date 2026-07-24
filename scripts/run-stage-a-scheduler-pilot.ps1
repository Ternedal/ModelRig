[CmdletBinding()]
param(
    [switch]$Elevated
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$branch = "agent/stage-a-checkpoint-ux"
$pythonScript = Join-Path $repoRoot "scripts\stage_a_scheduler_pilot_easy.py"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($env:OS -ne "Windows_NT") {
    throw "Scheduler-piloten må kun køres på Windows-riggen."
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        throw "Windows gav ikke administratoradgang til scheduler-piloten."
    }
    $quotedScript = '"' + $PSCommandPath.Replace('"', '""') + '"'
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File $quotedScript -Elevated"
    try {
        $process = Start-Process `
            -FilePath "powershell.exe" `
            -Verb RunAs `
            -ArgumentList $arguments `
            -Wait `
            -PassThru
    }
    catch {
        throw "Administratorprompten blev afvist eller kunne ikke åbnes: $($_.Exception.Message)"
    }
    exit $process.ExitCode
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git blev ikke fundet på PATH."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python blev ikke fundet på PATH."
}

Push-Location $repoRoot
try {
    $dirty = (& git status --porcelain --untracked-files=no) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Git-status kunne ikke læses." }
    if (-not [string]::IsNullOrWhiteSpace($dirty)) {
        throw "Tracked working tree er ikke ren:`n$dirty"
    }

    & git fetch --quiet origin $branch
    if ($LASTEXITCODE -ne 0) { throw "Kunne ikke hente $branch fra origin." }

    $current = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Aktuel Git-branch kunne ikke læses." }
    if ($current -ne $branch) {
        & git switch $branch
        if ($LASTEXITCODE -ne 0) { throw "Kunne ikke skifte til $branch." }
    }

    & git pull --ff-only origin $branch
    if ($LASTEXITCODE -ne 0) { throw "Kunne ikke fast-forwarde $branch til origin." }

    $expected = (& git rev-parse "origin/$branch").Trim()
    $actual = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $expected) {
        throw "Lokal HEAD matcher ikke origin/$branch efter opdateringen."
    }

    Write-Host "" 
    Write-Host "Exact scheduler-head: $actual" -ForegroundColor Cyan
    & python $pythonScript
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
