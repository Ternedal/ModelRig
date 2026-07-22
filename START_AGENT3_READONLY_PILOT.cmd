@echo off
setlocal
cd /d "%~dp0"
title Kaliv Agent 3 Read-Only Pilot
set "PYTHONDONTWRITEBYTECODE=1"
python "%~dp0scripts\agent3_readonly_pilot_one_click.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Piloten stoppede sikkert. Dobbeltklik igen efter rettelsen; rapporten er bevaret eller arkiveret.
if "%EXIT_CODE%"=="0" echo Agent 3 read-only-piloten er faerdig og bestaaet.
echo.
pause
exit /b %EXIT_CODE%
