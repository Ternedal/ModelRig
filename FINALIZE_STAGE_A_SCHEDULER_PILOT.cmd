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
echo Ingen merge, release eller produktion aktiveres.
echo.

python "%~dp0scripts\stage_a_scheduler_finalize.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo SCHEDULER-PILOTEN BLEV IKKE GODKENDT.
  echo Delresultater er bevaret; intet er fremstillet som bestaaet.
  pause
)
exit /b %EXIT_CODE%
