@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo FEJL: Python blev ikke fundet paa PATH.
  exit /b 2
)

python scripts\agent3_write_pilot_positive_one_click.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo T-022 positiv operator stoppede sikkert med exit %EXIT_CODE%.
  echo Delvis manifest og observationsjournal er bevaret til resume.
)

exit /b %EXIT_CODE%
