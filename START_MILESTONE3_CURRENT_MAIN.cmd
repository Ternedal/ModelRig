@echo off
setlocal
cd /d "%~dp0"

echo Kaliv Milestone 3 - current-main fysisk kandidat
echo.
echo Denne launcher koerer Stage A, T-020, T-022 final-gate og T-023 paa samme kandidat.
echo Den kan ikke automatisere telefonobservationer eller approvals.
echo.

python -B scripts\milestone3_current_main.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo SIKKERT STOP: Milestone 3 er ikke komplet. Se blockeren ovenfor.
) else (
  echo Milestone 3-rapporterne er valideret paa samme kandidat.
)
pause
exit /b %EXIT_CODE%
