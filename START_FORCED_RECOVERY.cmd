@echo off
setlocal
cd /d "%~dp0"
title Kaliv T-006 forced recovery
set "PYTHONDONTWRITEBYTECODE=1"
python "%~dp0scripts\forced_recovery_test.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" echo T-006 er bevist paa denne maskine. Vinduet kan lukkes.
if not "%EXIT_CODE%"=="0" echo Noget afveg. Kopier hele outputtet videre.
echo.
pause
exit /b %EXIT_CODE%
