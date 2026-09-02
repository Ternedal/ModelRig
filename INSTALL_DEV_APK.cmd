@echo off
setlocal
cd /d "%~dp0"
title Kaliv DEV-APK
if "%GITHUB_TOKEN%"=="" set /p GITHUB_TOKEN=GitHub-PAT fra Notion Secrets: 
set "GH_TOKEN=%GITHUB_TOKEN%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-dev-apk.ps1" %*
echo.
pause
exit /b %ERRORLEVEL%
