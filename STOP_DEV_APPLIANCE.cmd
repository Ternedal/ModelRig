@echo off
setlocal
cd /d "%~dp0"
title Kaliv DEV-appliance -- stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev-appliance.ps1" -Stop
echo.
pause
exit /b %ERRORLEVEL%
