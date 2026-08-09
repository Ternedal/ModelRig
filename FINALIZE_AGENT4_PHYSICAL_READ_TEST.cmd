@echo off
setlocal
set "decision=%~1"
if "%decision%"=="" set "decision=NO-GO"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\agent4-physical-read-operator.ps1" -Action Finalize -Decision "%decision%"
exit /b %ERRORLEVEL%
