@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 -B scripts\stage_b_physical_gate.py
) else (
  python -B scripts\stage_b_physical_gate.py
)

set "EXITCODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXITCODE%
