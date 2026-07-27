@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo FEJL: Python launcher ^(py^) blev ikke fundet.
  echo Installer Python 3 og proev igen.
  pause
  exit /b 1
)

py -3 scripts\agent3_write_pilot_physical_one_click.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo T-022 operatoren stoppede sikkert med exitkode %RC%.
  echo Manifest, journal og response-artifacts er bevaret til resume.
  pause
)
exit /b %RC%
