@echo off
setlocal
cd /d "%~dp0"
title Kaliv Stage B test
set "PYTHONDONTWRITEBYTECODE=1"

echo ================================================================
echo   KALIV STAGE B - STRICT UPDATER-EVIDENS
echo ================================================================
echo.
echo Wizard'en verificerer updater-bootstrapens checksum + provenance,
echo haandhaever source 1.58.150, gennemfoerer en kontrolleret mid-swap
echo interruption/recovery og samler derefter de normale lifecycle-beviser.
echo.
echo Den kan ikke merge, pushe, tagge, release eller aktivere produktion.
echo.

python "%~dp0scripts\stage_b_one_click_v2.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo Testen stoppede sikkert. Delresultater er bevaret; koer igen efter rettelsen.
if "%EXIT_CODE%"=="0" echo Strict + normale observationer er indsamlet. Koer VERIFY_STAGE_B_EVIDENCE.cmd.
echo.
pause
exit /b %EXIT_CODE%
