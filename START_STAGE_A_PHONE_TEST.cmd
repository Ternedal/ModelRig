@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv Stage A - let telefonforbindelse
echo ================================================================
echo.
echo Starter en isoleret exact-head backend og worker paa LAN.
echo Der oprettes automatisk en rigtig parringskode til appen.
echo Ingen tokenkopiering, JSON-redigering eller manuel firewallopsætning.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stage-a-phone-test.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo TELEFON-TESTEN KUNNE IKKE STARTES.
  echo Intet blev merget, releaset eller aktiveret.
  pause
)
exit /b %EXIT_CODE%
