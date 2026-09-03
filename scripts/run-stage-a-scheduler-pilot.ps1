[CmdletBinding()]
param(
    [switch]$Elevated
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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

    # Bind to the checked-out, frozen rig candidate. Never fetch/switch/pull a
    # branch: the scheduler proof must share the candidate's exact SHA with the
    # other Stage A proofs. The Python orchestrator enforces that HEAD is a
    # candidate branch; here we only require a clean tree and a valid exact head.
    $actual = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -notmatch '^[0-9a-f]{40}$') {
        throw "Kunne ikke læse en gyldig exact HEAD for den udcheckede kandidat."
    }

    Write-Host ""
    Write-Host "Exact candidate-head: $actual" -ForegroundColor Cyan
    & python $pythonScript
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
