@echo off
setlocal
cd /d "%~dp0"

title Kaliv Stage A - Scheduler Pilot

echo ================================================================
echo   KALIV STAGE A - EN GUIDET SCHEDULER-PILOT
echo ================================================================
echo.
echo Denne launcher opdaterer den eksakte valideringsgren og beder selv om
 echo administratoradgang. Read, revocation, crash-recovery, rapport og cleanup
 echo koeres automatisk.
echo.
echo Din eneste handling bliver at forbinde Pixel 6a og godkende EN vist
 echo note_append-plan i Kaliv. Ingen token, ID eller JSON skal kopieres.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-stage-a-scheduler-pilot.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo ================================================================
    echo   SCHEDULER-PILOTEN ER AFSLUTTET OG GEMT
    echo ================================================================
    echo Rapporten ligger i validation\scheduler-pilot-latest.json
    echo Ingen merge, release eller produktion blev aktiveret.
) else (
    echo ================================================================
    echo   SCHEDULER-PILOTEN STOPPEDE SIKKERT
    echo ================================================================
    echo Delresultater er bevaret. Koer samme launcher igen for at fortsaette.
    echo Brug STOP_STAGE_A_PHONE_TEST.cmd, hvis teststacken skal lukkes.
)
echo.
pause
exit /b %EXIT_CODE%
