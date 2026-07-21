@echo off
setlocal
cd /d "%~dp0"
title Kaliv Scheduler Pilot
set "PYTHONDONTWRITEBYTECODE=1"
python "%~dp0scripts\scheduler_pilot_easy_entry.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto done
python "%~dp0scripts\scheduler_pilot_android_gate.py" --report "%~dp0validation\scheduler-pilot-latest.json" --manual-observations "%~dp0validation\scheduler-manual-observations.json"
set "EXIT_CODE=%ERRORLEVEL%"
:done
echo.
if not "%EXIT_CODE%"=="0" echo Piloten stoppede sikkert. Dobbeltklik igen efter rettelsen; lokale beviser er bevaret.
if "%EXIT_CODE%"=="0" echo Scheduler-piloten er faerdig. Vinduet kan lukkes.
echo.
pause
exit /b %EXIT_CODE%
