@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo FEJL: Python blev ikke fundet paa PATH.
  exit /b 1
)

if "%~1"=="" (
  python scripts\agent3_memory_protected_backup_physical.py prepare
) else (
  python scripts\agent3_memory_protected_backup_physical.py %*
)

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo T-033 fysisk backup/restore er BLOKERET. Ingen produktion er aktiveret.
)
exit /b %EXIT_CODE%
