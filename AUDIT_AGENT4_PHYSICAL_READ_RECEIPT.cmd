@echo off
setlocal EnableExtensions
if "%~1"=="" (
  echo.
  echo BRUG: AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd ^<40-tegns-exact-SHA^>
  echo.
  echo A4-18 receipt-audit starter ikke uden en eksplicit forventet validation-head.
  exit /b 2
)
set "REPO=%~dp0"
set "EXPECTED_SHA=%~1"
set "RECEIPT=%REPO%validation\agent4-physical-read-latest.json"
set "OUT=%USERPROFILE%\ModelRig-Validation\A4-18-receipt-audit\receipt-audit-latest.json"
python "%REPO%scripts\agent4_physical_read_exact_head_gate.py" --receipt "%RECEIPT%" --repo-root "%REPO%" --expected-sha "%EXPECTED_SHA%"
if errorlevel 1 (
  echo A4-18 EXACT-HEAD GATE FEJLEDE. Issue #421 maa ikke lukkes.
  exit /b 2
)
python "%REPO%scripts\agent4_physical_read_audit_hardening.py" --receipt "%RECEIPT%" --repo-root "%REPO%"
if errorlevel 1 (
  echo A4-18 RECEIPT HARDENING FEJLEDE. Issue #421 maa ikke lukkes.
  exit /b 2
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%REPO%scripts\agent4-physical-read-audit.ps1" -ReceiptPath "%RECEIPT%" -RepoRoot "%REPO%" -OutputPath "%OUT%" -RequireRemoteRefs
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo A4-18 RECEIPT AUDIT BESTAAET.
) else (
  echo A4-18 RECEIPT AUDIT FEJLEDE. Issue #421 maa ikke lukkes.
)
if exist "%OUT%" echo Rapport: %OUT%
pause
exit /b %RC%
