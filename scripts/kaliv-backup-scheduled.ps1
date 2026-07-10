# Register a daily Kaliv backup as a Windows Scheduled Task.
# Run once, elevated:  powershell -ExecutionPolicy Bypass -File kaliv-backup-scheduled.ps1
#
# Creates a task "KalivBackup" that runs kaliv-backup.bat every day at 03:00.
# This is the "planlagt" half of ROADMAP V7.3; the manual half is the .bat.
# NOT YET RUN ON THE RIG -- verify the trigger fired before trusting it.

$repo = Split-Path -Parent $PSScriptRoot
$bat  = Join-Path $PSScriptRoot "kaliv-backup.bat"

$action  = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At 3am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName "KalivBackup" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Daily backup of Kaliv rig state (RAG, audit, tokens, notes)" -Force

Write-Host "Registered task 'KalivBackup' (daily 03:00)."
Write-Host "Verify: Get-ScheduledTask -TaskName KalivBackup"
Write-Host "Test now: Start-ScheduledTask -TaskName KalivBackup"
