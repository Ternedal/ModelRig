@echo off
setlocal
if "%~1"=="" (
  echo.
  echo BRUG: START_AGENT4_PHYSICAL_READ_TEST.cmd ^<40-tegns-exact-SHA^>
  echo.
  echo A4-18 starter ikke uden en eksplicit fysisk validation-head.
  exit /b 2
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\agent4-physical-read-operator.ps1" -Action PrepareOff -ExpectedSha "%~1"
exit /b %ERRORLEVEL%
