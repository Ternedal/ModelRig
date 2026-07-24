@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo   Kaliv Stage A - afslut scheduler-piloten
echo ================================================================
echo.
echo Kraever en koerende scheduler-teststack og groenne read/revocation/recovery-checkpoints.
echo Den eneste manuelle handling er at oprette og godkende den viste write-plan i Android.
echo ID, receipt, koersel, observationer og autoritativ rapport haandteres automatisk.
echo Den verificerede rapport publiceres derefter til Stage A-kampagnens faste evidenssti.
echo Ingen merge, release eller produktion aktiveres.
echo.

python "%~dp0scripts\stage_a_scheduler_finalize.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto :failed

python "%~dp0scripts\stage_a_scheduler_publish.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto :failed

echo.
echo SCHEDULER-PILOTEN ER VERIFICERET OG PUBLICERET TIL STAGE A-KAMPAGNEN.
exit /b 0

:failed
echo.
echo SCHEDULER-PILOTEN BLEV IKKE GODKENDT ELLER PUBLICERET.
echo Delresultater er bevaret; intet er fremstillet som bestaaet.
pause
exit /b %EXIT_CODE%
