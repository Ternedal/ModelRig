@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  set "RECEIPT=validation\agent4-physical-read-latest.json"
) else (
  set "RECEIPT=%~1"
)

for /f "delims=" %%S in ('git rev-parse HEAD 2^>nul') do set "EXACT_SHA=%%S"
if not defined EXACT_SHA (
  echo Kunne ikke laese repository HEAD. 1>&2
  exit /b 2
)

python scripts\validate-agent4-physical-read-receipt.py "%RECEIPT%" --expected-sha "%EXACT_SHA%" --repo-root "%CD%"
exit /b %ERRORLEVEL%
