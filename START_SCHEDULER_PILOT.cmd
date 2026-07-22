@echo off
setlocal
cd /d "%~dp0"
title Kaliv T-019 scheduler-pilot
set "PYTHONDONTWRITEBYTECODE=1"
python "%~dp0scripts\scheduler_pilot_wizard.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Piloten stoppede sikkert. Dobbeltklik igen efter rettelsen.
if "%EXIT_CODE%"=="0" echo T-019-piloten er faerdig. Rapport: validation\scheduler-pilot-latest.json
if "%EXIT_CODE%"=="0" echo Vinduet kan lukkes.
echo.
pause
exit /b %EXIT_CODE%
