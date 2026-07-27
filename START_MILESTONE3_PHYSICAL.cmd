@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"

echo ================================================================
echo   Kaliv Milestone 3 - samlet fysisk Agent 3-kandidat
echo ================================================================
echo.
echo Raekkefoelge: T-020 read-only, T-022 append-only, T-023 termination UI.
echo Alle tre operatorer bindes til samme rene exact-head kandidat.
echo Ingen fysisk observation eller approval kan auto-udfyldes.
echo.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 -B scripts\milestone3_physical_one_click.py
) else (
  python -B scripts\milestone3_physical_one_click.py
)
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Milestone 3-rapporterne er groenne paa samme kandidat.
) else (
  echo Milestone 3 stoppede sikkert med exitkode %EXIT_CODE%.
  echo Ret den viste blocker og start denne launcher igen.
)
echo.
pause
exit /b %EXIT_CODE%
