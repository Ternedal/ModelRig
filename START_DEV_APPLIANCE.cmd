@echo off
setlocal
cd /d "%~dp0"
title Kaliv DEV-appliance
rem Stop-/Start-ScheduledTask paa appliancens tasks kraever administrator.
rem Uden elevation faldt foerste koersel paa praecis det -- saa bed om den.
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Beder om administrator-rettigheder...
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  )
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev-appliance.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Dev-appliancen kom ikke op. Se fejlen ovenfor og de to konsolvinduer.
if "%EXIT_CODE%"=="0" echo Dev-appliancen koerer. Luk IKKE de to konsolvinduer; brug STOP_DEV_APPLIANCE for at gaa tilbage til release.
echo.
pause
exit /b %EXIT_CODE%
