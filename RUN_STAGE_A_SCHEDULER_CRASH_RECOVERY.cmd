@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv Stage A - scheduler crash-recovery
echo ================================================================
echo.
echo Kraever en koerende scheduler-teststack samt read- og revocation-checkpoints.
echo Fanger en rigtig claim, crasher kun den registrerede worker og genstarter sikkert.
echo Write-godkendelse og samlet pilotrapport forbliver pending.
echo.

python "%~dp0scripts\stage_a_scheduler_crash_recovery.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo CRASH-RECOVERY-BEVISET BLEV IKKE GODKENDT.
  echo Der er ikke skrevet et bestaaet pilotresultat.
  pause
)
exit /b %EXIT_CODE%
