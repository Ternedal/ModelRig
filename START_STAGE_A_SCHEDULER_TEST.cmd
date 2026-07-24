@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv Stage A - scheduler-teststack
echo ================================================================
echo.
echo Starter en isoleret exact-head backend, worker og scheduler.
echo Telefonen parres med en frisk kode; scheduler-data og log gemmes separat.
echo Dette gennemfoerer endnu ikke selve scheduler-pilotbeviset.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stage-a-phone-test.ps1" -EnableSchedulerPilot
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo SCHEDULER-TESTSTACKEN KUNNE IKKE STARTES.
  echo Intet blev merget, releaset eller aktiveret.
  pause
)
exit /b %EXIT_CODE%
