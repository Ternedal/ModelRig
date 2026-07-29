@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo FEJL: Python blev ikke fundet paa PATH.
  exit /b 2
)

python scripts\agent3_write_pilot_final_gate_operator.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo T-022 final gate stoppede sikkert med exit %EXIT_CODE%.
  echo Ingen gammel groen final-gate eller produktionsaktivering er blevet efterladt.
)

exit /b %EXIT_CODE%
