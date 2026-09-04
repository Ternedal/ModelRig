# Kaliv appliance bootstrap.
#
# This script is the only logon/startup entrypoint. It runs the updater's
# offline recovery pass before the supervisor task is allowed to start. A
# failed or ambiguous update transaction therefore leaves the appliance down
# and visible instead of starting a potentially mixed-version runtime.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$SupervisorTaskName = "KalivSupervisor"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$updater = Join-Path $RepoRoot "modelrig-updater-windows-x64.exe"
$supervisor = Join-Path $RepoRoot "modelrig-supervisor-windows-x64.exe"

if (-not (Test-Path -LiteralPath $updater -PathType Leaf)) {
    throw "Updater exe not found at $updater. Recovery cannot be proven, so the supervisor will not be started."
}
if (-not (Test-Path -LiteralPath $supervisor -PathType Leaf)) {
    throw "Supervisor exe not found at $supervisor."
}

Write-Host "Running updater recovery before appliance startup..."
& $updater -dir $RepoRoot -recover -supervisor-task $SupervisorTaskName
$recoveryExitCode = $LASTEXITCODE
if ($recoveryExitCode -ne 0) {
    throw "Updater recovery failed with exit code $recoveryExitCode. The supervisor was not started."
}

# An active journal recovery may already have started the supervisor task after
# proving the rollback. In the normal no-journal path it remains stopped, so the
# bootstrap starts it exactly once here.
$supervisorTask = Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction Stop
if ($supervisorTask.State -ne "Running") {
    Start-ScheduledTask -TaskName $SupervisorTaskName
    Write-Host "Started '$SupervisorTaskName' after successful recovery."
} else {
    Write-Host "'$SupervisorTaskName' is already running after recovery."
}
