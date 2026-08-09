@echo off
setlocal EnableExtensions
set "REPO=%~dp0"
set "RECEIPT=%REPO%validation\agent4-physical-read-latest.json"
set "OUT=%USERPROFILE%\ModelRig-Validation\A4-18-receipt-audit\receipt-audit-latest.json"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%REPO%scripts\agent4-physical-read-audit-sdk.ps1" -ReceiptPath "%RECEIPT%"
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%REPO%scripts\agent4-physical-read-audit-hardening.ps1" -ReceiptPath "%RECEIPT%" -RepoRoot "%REPO%" -OutputPath "%OUT%" -RequireRemoteRefs
  set "RC=%ERRORLEVEL%"
)
echo.
if "%RC%"=="0" (
  echo A4-18 RECEIPT AUDIT BESTAAET.
) else (
  echo A4-18 RECEIPT AUDIT FEJLEDE. Issue #421 maa ikke lukkes.
)
if exist "%OUT%" echo Rapport: %OUT%
pause
exit /b %RC%
