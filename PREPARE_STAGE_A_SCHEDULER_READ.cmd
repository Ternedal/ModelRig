@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv Stage A - scheduler read-halvdel
echo ================================================================
echo.
echo Kraever at START_STAGE_A_SCHEDULER_TEST.cmd allerede koerer.
echo Opretter den praecise read-plan, venter paa en rigtig koersel og pauser den.
echo Write, revocation, crash-recovery og samlet pilotrapport forbliver pending.
echo.

python "%~dp0scripts\stage_a_scheduler_read.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo READ-HALVDELEN BLEV IKKE GODKENDT.
  echo Der er ikke skrevet et bestaaet pilotresultat.
  pause
)
exit /b %EXIT_CODE%
