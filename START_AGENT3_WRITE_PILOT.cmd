@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\agent3_write_pilot_one_click.py
) else (
  python scripts\agent3_write_pilot_one_click.py
)

set EXITCODE=%errorlevel%
echo.
if not "%EXITCODE%"=="0" (
  echo T-022-wizard stoppede sikkert med exit %EXITCODE%.
  echo Delvis kandidatbundet state er bevaret under validation\.
) else (
  echo T-022-wizard afsluttede uden rapporterede blockers.
)
echo.
pause
exit /b %EXITCODE%
