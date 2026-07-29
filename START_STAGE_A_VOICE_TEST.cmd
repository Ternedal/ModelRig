@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"

echo ================================================================
echo   Kaliv Stage A - guidet voice-test
echo ================================================================
echo.
echo Denne ene launcher:
echo   - starter den isolerede telefonstack og laver en rigtig parringskode
echo   - guider fem Pixel-forsog uden manuel JSON-redigering
echo   - gemmer efter hvert forsog, saa testen kan genoptages
echo   - laver en fysisk cold-start og korer voice-baselinen
echo   - rydder backend, worker og firewallregel op bagefter
echo.
echo Hojreklik og vaelg "Kor som administrator".
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stage-a-voice-test.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo VOICE-TESTEN ER FAERDIG OG GROEN.
) else (
  echo VOICE-TESTEN STOPPEDE SIKKERT.
  echo Allerede besvarede forsog og rapporter er bevaret.
  echo Intet blev merget, releaset eller aktiveret.
)
echo.
pause
exit /b %EXIT_CODE%
