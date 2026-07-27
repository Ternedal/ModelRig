@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="--legacy" goto legacy

echo ================================================================
echo   LEGACY LAUNCHER - IKKE MILESTONE 3
echo ================================================================
echo.
echo Denne launcher koerer kun den aeldre kombination:
echo   Stage A - T-020 read-only - Scheduler M2
echo.
echo For den autoritative Agent 3 Milestone 3-kandidat med
echo T-020, T-022 og T-023 skal du i stedet koere:
echo.
echo   START_MILESTONE3_PHYSICAL.cmd
echo.
echo Den gamle kombination kan stadig koeres bevidst med:
echo   START_REMAINING_PHYSICAL_TESTS.cmd --legacy
echo.
pause
exit /b 2

:legacy
set "PYTHONDONTWRITEBYTECODE=1"
echo.
echo ADVARSEL: koerer legacy Stage A + T-020 + Scheduler M2.
echo Dette fuldfoerer ikke T-022 eller T-023.
echo.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 -B scripts\remaining_physical_pilots.py
) else (
  python -B scripts\remaining_physical_pilots.py
)

set "EXITCODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXITCODE%
