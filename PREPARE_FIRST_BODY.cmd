@echo off
setlocal
cd /d "%~dp0"
title Kaliv -- foerste krop
if "%~1"=="" (
  echo Brug: PREPARE_FIRST_BODY.cmd ^<sti til .vrm^> [navn]
  echo   fx: PREPARE_FIRST_BODY.cmd C:\Users\admin\Desktop\Kaliv.vrm Kaliv
  pause
  exit /b 1
)
set "BODYNAME=%~2"
if "%BODYNAME%"=="" set "BODYNAME=Kaliv"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\prepare-first-body.ps1" -Vrm "%~1" -Name "%BODYNAME%"
pause
