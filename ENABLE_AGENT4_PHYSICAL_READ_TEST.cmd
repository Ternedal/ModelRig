@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\agent4-physical-read-operator.ps1" -Action Enable
exit /b %ERRORLEVEL%
