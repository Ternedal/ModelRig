@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo FEJL: Python blev ikke fundet paa PATH.
  exit /b 2
)

python scripts\agent3_write_pilot_negative_operator.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo T-022 negativ operator stoppede sikkert med exit %EXIT_CODE%.
  echo Hashkaedet journal og fysiske observationer er bevaret til resume.
)

exit /b %EXIT_CODE%
