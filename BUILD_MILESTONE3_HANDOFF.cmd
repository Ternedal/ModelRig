@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"

echo ================================================================
echo   Kaliv Milestone 3 - byg offline kandidat-handoff
echo ================================================================
echo.
echo Pakken indeholder exact Git-bundle, Android APK, Windows desktop-jar,
echo SHA-256-manifest og en bootstrap, der kontrollerer kandidatens SHA.
echo Ingen upload, release, merge eller production activation udfoeres.
echo.

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 -B scripts\milestone3_candidate_handoff.py
) else (
  python -B scripts\milestone3_candidate_handoff.py
)
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Handoff-pakken ligger i handoff\
) else (
  echo Handoff-build stoppede sikkert med exitkode %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
