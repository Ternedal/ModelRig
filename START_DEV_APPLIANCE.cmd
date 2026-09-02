@echo off
setlocal
cd /d "%~dp0"
title Kaliv DEV-appliance
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev-appliance.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Dev-appliancen kom ikke op. Se fejlen ovenfor og de to konsolvinduer.
if "%EXIT_CODE%"=="0" echo Dev-appliancen koerer. Luk IKKE de to konsolvinduer; brug -Stop for at gaa tilbage til release.
echo.
pause
exit /b %EXIT_CODE%
