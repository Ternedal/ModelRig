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

rem A fresh rig may not have a notes file yet. The operator's default target is
rem this path; create only the missing directory/file and never truncate an
rem existing note. Custom paths are still selected and validated in the wizard.
set "DEFAULT_NOTES_DIR=%USERPROFILE%\Documents\Kaliv"
set "DEFAULT_NOTES=%DEFAULT_NOTES_DIR%\notes.md"
if not exist "%DEFAULT_NOTES_DIR%" mkdir "%DEFAULT_NOTES_DIR%"
if not exist "%DEFAULT_NOTES%" type nul > "%DEFAULT_NOTES%"

py -3 scripts\agent3_write_pilot_physical_one_click.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo T-022 operatoren stoppede sikkert med exitkode %RC%.
  echo Manifest, journal og response-artifacts er bevaret til resume.
  pause
)
exit /b %RC%
