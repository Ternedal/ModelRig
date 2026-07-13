# Register the Kaliv supervisor to start automatically at logon (this is the
# "survives a reboot" half of the appliance goal). Run once, elevated:
#   powershell -ExecutionPolicy Bypass -File kaliv-autostart.ps1
#
# Creates a Scheduled Task "KalivSupervisor" that launches
# modelrig-supervisor-windows-x64.exe at logon. The supervisor then starts the
# worker + server and restarts either one if it exits or stops answering
# /healthz -- so you never open three terminals again. Mirrors the pattern in
# kaliv-backup-scheduled.ps1.
#
# NOT YET RUN ON THE RIG -- after registering, reboot (or Start-ScheduledTask)
# and confirm both processes come up before trusting it.

$repo = Split-Path -Parent $PSScriptRoot   # the ModelRig root; the exes live here
$exe  = Join-Path $repo "modelrig-supervisor-windows-x64.exe"

if (-not (Test-Path $exe)) {
    throw "Supervisor exe not found at $exe. Download modelrig-supervisor-windows-x64.exe from the release into the ModelRig root first."
}

$action  = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Keep the supervisor itself resilient: if IT exits, Task Scheduler brings it
# back, and an always-on task must never be killed for "running too long".
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask -TaskName "KalivSupervisor" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Starts and supervises the Kaliv worker + server; restarts them on crash." -Force

Write-Host "Registered 'KalivSupervisor' (runs at logon)."
Write-Host "Start it now without rebooting:  Start-ScheduledTask -TaskName KalivSupervisor"
Write-Host "Check it:                         Get-ScheduledTask -TaskName KalivSupervisor"
Write-Host "Stop the appliance:              Stop-ScheduledTask -TaskName KalivSupervisor  (then it won't restart until next logon)"
Write-Host "Child logs land in:              $repo\logs\worker.log and server.log"
Write-Host ""
Write-Host "NOTE: -AtLogOn starts it when you log in. For a headless box that reboots"
Write-Host "without a login, re-register with -AtStartup and a SYSTEM/service account."
