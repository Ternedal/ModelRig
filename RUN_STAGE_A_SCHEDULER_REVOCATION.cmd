@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv Stage A - scheduler revocation
 echo ================================================================
echo.
echo Kraever en koerende scheduler-teststack og en groent read-checkpoint.
echo Fanger en rigtig claim, pauser planen og verificerer cancelled-job + refundering.
echo Crash-recovery, write og samlet pilotrapport forbliver pending.
echo.

python "%~dp0scripts\stage_a_scheduler_revocation.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo REVOCATION-BEVISET BLEV IKKE GODKENDT.
  echo Der er ikke skrevet et bestaaet pilotresultat.
  pause
)
exit /b %EXIT_CODE%
