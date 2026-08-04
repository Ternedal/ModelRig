@echo off
setlocal
cd /d "%~dp0"
title Kaliv Stage B test
set "PYTHONDONTWRITEBYTECODE=1"

echo ================================================================
echo   KALIV STAGE B - UPDATER-EVIDENS
echo ================================================================
echo.
echo Wizard'en maaler selv reboot-tid, supervisor-genstarter, versioner,
echo fingerprints og log-hashes. Den stopper kun for genstarten og for din
echo godkendelse af den ugyldige opdatering.
echo.
echo Den kan ikke merge, pushe, tagge, release eller aktivere produktion.
echo.

python "%~dp0scripts\stage_b_one_click.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo Testen stoppede sikkert. Delresultater er bevaret; koer igen efter rettelsen.
if "%EXIT_CODE%"=="0" echo Alle fem observationer er indsamlet. Koer VERIFY_STAGE_B_EVIDENCE.cmd.
echo.
pause
exit /b %EXIT_CODE%
