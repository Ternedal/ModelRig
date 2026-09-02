@echo off
setlocal
cd /d "%~dp0"
title Kaliv DEV-appliance -- stop
rem Stop-/Start-ScheduledTask paa appliancens tasks kraever administrator.
rem Uden elevation faldt foerste koersel paa praecis det -- saa bed om den.
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Beder om administrator-rettigheder...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev-appliance.ps1" -Stop
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo.
pause
exit /b %EXIT_CODE%
