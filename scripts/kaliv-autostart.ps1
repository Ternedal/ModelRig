# Register Kaliv's recovery-first appliance startup. Run once, elevated:
#   powershell -ExecutionPolicy Bypass -File kaliv-autostart.ps1
#
# Two tasks are deliberately registered:
#
# - KalivBootstrap runs at logon and executes kaliv-bootstrap.ps1.
# - KalivSupervisor is an on-demand task that launches the supervisor.
#
# The bootstrap runs `modelrig-updater-windows-x64.exe -recover` before it starts
# KalivSupervisor. A crashed or ambiguous update therefore fails closed instead
# of starting a potentially mixed-version appliance.
#
# NOT YET RUN ON THE RIG -- after registering, reboot (or start KalivBootstrap)
# and confirm recovery completes before the supervisor and children start.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo       = Split-Path -Parent $PSScriptRoot
$supervisor = Join-Path $repo "modelrig-supervisor-windows-x64.exe"
$updater    = Join-Path $repo "modelrig-updater-windows-x64.exe"
$bootstrap  = Join-Path $PSScriptRoot "kaliv-bootstrap.ps1"

foreach ($required in @($supervisor, $updater, $bootstrap)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required startup file not found at $required."
    }
}

# KalivSupervisor intentionally has no logon trigger. It is started only by the
# bootstrap after updater recovery succeeds, or by the updater itself after a
# proven recovery/update transition.
$supervisorAction = New-ScheduledTaskAction `
    -Execute $supervisor `
    -WorkingDirectory $repo
$supervisorSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask `
    -TaskName "KalivSupervisor" `
    -Action $supervisorAction `
    -Settings $supervisorSettings `
    -Description "Runs and supervises the Kaliv worker + server. Started only after recovery succeeds." `
    -Force

$bootstrapArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$bootstrap`" -RepoRoot `"$repo`" -SupervisorTaskName `"KalivSupervisor`""
$bootstrapAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $bootstrapArguments `
    -WorkingDirectory $repo
$bootstrapTrigger = New-ScheduledTaskTrigger -AtLogOn
$bootstrapSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName "KalivBootstrap" `
    -Action $bootstrapAction `
    -Trigger $bootstrapTrigger `
    -Settings $bootstrapSettings `
    -Description "Recovers an interrupted ModelRig update before starting KalivSupervisor." `
    -Force

Write-Host "Registered 'KalivBootstrap' (runs at logon and recovers first)."
Write-Host "Registered 'KalivSupervisor' (on-demand; no direct logon trigger)."
Write-Host "Start safely now:                  Start-ScheduledTask -TaskName KalivBootstrap"
Write-Host "Check bootstrap:                   Get-ScheduledTask -TaskName KalivBootstrap"
Write-Host "Check supervisor:                  Get-ScheduledTask -TaskName KalivSupervisor"
Write-Host "Stop the appliance:                Stop-ScheduledTask -TaskName KalivSupervisor"
Write-Host "Child logs land in:                $repo\logs\worker.log and server.log"
Write-Host ""
Write-Host "NOTE: -AtLogOn requires a login. For a headless box, replace the bootstrap"
Write-Host "trigger with -AtStartup and register it under a suitable service account."
