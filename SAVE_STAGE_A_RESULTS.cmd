@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"

echo ================================================================
echo   Kaliv Stage A - gem de resultater der allerede findes
echo ================================================================
echo.
echo Denne launcher starter ingen backend, worker, telefonstest eller scheduler.
echo Den genberegner kun den autoritative lokale status og gemmer et checkpoint.
echo.

python scripts\physical_validation_candidate_campaign.py ^
  --mode prepare ^
  --report validation\physical-validation-candidate-campaign-latest.json
set "CAMPAIGN_EXIT=%ERRORLEVEL%"

python scripts\stage_a_checkpoint.py ^
  --campaign validation\physical-validation-candidate-campaign-latest.json ^
  --voice-fixtures validation\voice-baseline-fixture-check.json ^
  --report validation\stage-a-checkpoint-latest.json
set "CHECKPOINT_EXIT=%ERRORLEVEL%"

echo.
if "%CHECKPOINT_EXIT%"=="0" (
  echo CHECKPOINT GEMT.
  echo De bestaaede beviser er bevaret; manglende manuelle beviser er ikke opdigtet.
  echo Rapport: validation\stage-a-checkpoint-latest.json
) else (
  echo CHECKPOINT BLOKERET.
  echo Se validation\stage-a-checkpoint-latest.json for den konkrete aarsag.
)

echo.
echo Ingen merge, tag, release eller produktionsaktivering er udfoert.
pause
exit /b %CHECKPOINT_EXIT%
