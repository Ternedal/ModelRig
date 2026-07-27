@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" blev ikke fundet.
  echo Installer Python 3 og prov igen.
  pause
  exit /b 2
)

py -3 scripts\agent3_write_pilot_one_click.py %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo T-022-wizard stoppede sikkert med exit %EXIT_CODE%.
  echo Delvis manifest, journal og operator-state er bevaret.
  pause
)
exit /b %EXIT_CODE%
