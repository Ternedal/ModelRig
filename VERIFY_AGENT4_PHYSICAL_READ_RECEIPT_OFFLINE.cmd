@echo off
setlocal EnableExtensions

if "%~1"=="" (
  echo Usage: %~nx0 EXPECTED_SHA [RECEIPT_JSON]
  exit /b 64
)

set "EXPECTED_SHA=%~1"
set "RECEIPT=%~2"
if "%RECEIPT%"=="" set "RECEIPT=validation\agent4-physical-read-latest.json"

pushd "%~dp0" >nul || exit /b 70
python scripts\agent4_physical_receipt_verify_offline.py --expected-sha "%EXPECTED_SHA%" --receipt "%RECEIPT%"
set "RC=%ERRORLEVEL%"
popd >nul
exit /b %RC%
