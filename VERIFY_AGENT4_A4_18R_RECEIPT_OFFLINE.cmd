@echo off
setlocal EnableExtensions

if "%~1"=="" (
  echo Usage: %~nx0 EXPECTED_SHA [RECEIPT_JSON]
  exit /b 64
)

set "EXPECTED_SHA=%~1"
set "RECEIPT=%~2"
if "%RECEIPT%"=="" (
  echo RECEIPT_JSON is required unless you run this command from the A4-18R evidence location with an explicit path.
  exit /b 64
)

pushd "%~dp0" >nul || exit /b 70
python scripts\agent4_a4_18r_receipt_verify_offline.py --expected-sha "%EXPECTED_SHA%" --receipt "%RECEIPT%"
set "RC=%ERRORLEVEL%"
popd >nul
exit /b %RC%
