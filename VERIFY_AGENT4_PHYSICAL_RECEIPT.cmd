@echo off
setlocal
cd /d "%~dp0"

set "RECEIPT=%~1"
if not defined RECEIPT set "RECEIPT=validation\agent4-physical-read-latest.json"

set "EXPECTED_SHA=%~2"
if not defined EXPECTED_SHA (
  for /f "usebackq delims=" %%A in (`git rev-parse HEAD 2^>nul`) do set "EXPECTED_SHA=%%A"
)

if not defined EXPECTED_SHA (
  echo Kunne ikke bestemme exact SHA. Angiv receipt og 40-tegns SHA eksplicit.
  exit /b 2
)

python scripts\verify-agent4-physical-read-receipt.py "%RECEIPT%" --expected-sha "%EXPECTED_SHA%"
exit /b %ERRORLEVEL%
