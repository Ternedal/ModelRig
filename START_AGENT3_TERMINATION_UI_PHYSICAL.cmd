@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv T-023 - fysisk termination UI-validering
echo ================================================================
echo.
python scripts\agent3_termination_ui_physical_one_click.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo T-023-wizard afsluttet uden softwarefejl.
) else (
  echo T-023-wizard stoppede sikkert med exitkode %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
