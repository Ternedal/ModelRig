@echo off
setlocal
cd /d "%~dp0"
title Kaliv Scheduler Pilot
set "PYTHONDONTWRITEBYTECODE=1"
python "%~dp0scripts\scheduler_pilot_one_click.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Piloten stoppede sikkert. Dobbeltklik igen efter rettelsen; lokale beviser er bevaret.
if "%EXIT_CODE%"=="0" echo Scheduler-piloten er faerdig. Vinduet kan lukkes.
echo.
pause
exit /b %EXIT_CODE%
