@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo FEJL: Python blev ikke fundet paa PATH.
  exit /b 2
)

rem Current-main binding delegates through agent3_write_pilot_final_gate_operator.py.
python scripts\agent3_write_pilot_current_main.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo T-022 current-main final gate stoppede sikkert med exit %EXIT_CODE%.
  echo Ingen gammel groen final-gate eller produktionsaktivering er blevet efterladt.
)

exit /b %EXIT_CODE%
