@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv T-022 - fysisk append-only write-pilot
echo ================================================================
echo.
echo Krav: Windows-rig, praecis en ADB-enhed og den parrede device-token.
echo Wizard'en kan ikke selv godkende eller opfinde fysisk evidens.
echo.
python scripts\agent3_write_pilot_physical_one_click.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo T-022-wizard afsluttet med en groen forensisk rapport.
) else (
  echo T-022-wizard stoppede sikkert med exitkode %EXIT_CODE%.
  echo Delvis manifest/journal er bevaret til kontrolleret resume.
)
echo.
pause
exit /b %EXIT_CODE%
