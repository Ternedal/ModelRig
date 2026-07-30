@echo off
setlocal
cd /d "%~dp0"

echo Kaliv Milestone 3 - byg offline current-main handoff
echo.
echo Kandidat: agent/milestone3-current-main-v2 ^(version 1.58.147^)
echo Builder:   agent/milestone3-current-main-handoff-v2
echo.
echo Builderen laver kun lokale bundle/build/hash/ZIP-artifacts.
echo Den merger, pusher, uploader, releaser eller aktiverer ikke produktion.
echo.

python -B scripts\milestone3_current_main_handoff.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo SIKKERT STOP: Offline-handoff blev ikke bygget.
) else (
  echo Offline-handoff er bygget og integritetskontrolleret lokalt.
)
pause
exit /b %EXIT_CODE%
