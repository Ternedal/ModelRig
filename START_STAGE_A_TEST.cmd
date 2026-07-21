@echo off
setlocal
cd /d "%~dp0"
title Kaliv Stage A test
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stage-a-easy-test.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo Testen stoppede sikkert. Ret beskeden ovenfor og dobbeltklik igen.
if "%EXIT_CODE%"=="0" echo Faerdig. Vinduet kan lukkes.
echo.
pause
exit /b %EXIT_CODE%
