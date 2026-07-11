@echo off
setlocal
:: ===========================================================================
::  Kaliv rig launcher -- starts the whole stack in one double-click.
::
::  Rewritten to avoid parenthesized if/else blocks with nested quotes, which
::  cmd mis-parses ("was unexpected at this time"). Uses goto labels and starts
::  each service via a tiny generated .cmd so there are NO nested quotes or bare
::  & on the start line. Sets MODELRIG_HOST cleanly (no trailing space) and
::  KALIV_TOOLS_ENABLED=1, then reports /health/full.
:: ===========================================================================

set "REPO=%~dp0.."
pushd "%REPO%" >nul
set "REPO=%CD%"
popd >nul

echo.
echo   Kaliv rig launcher
echo   repo: %REPO%
echo.

:: --- 1. Ollama -------------------------------------------------------------
curl -s -o nul http://127.0.0.1:11434/api/tags
if not errorlevel 1 goto ollama_up
echo   [1/3] starter Ollama...
start "Ollama" cmd /k ollama serve
timeout /t 3 >nul
goto worker
:ollama_up
echo   [1/3] Ollama koerer allerede.

:worker
:: --- 2. Worker (Python) ----------------------------------------------------
if exist "%REPO%\worker\app\main.py" goto worker_ok
echo   [FEJL] finder ikke worker\app\main.py under %REPO%
echo          Ligger start-kaliv.bat i den rigtige repo-kopi?
pause
exit /b 1
:worker_ok
curl -s -o nul http://127.0.0.1:8099/health
if errorlevel 1 goto worker_start
echo   [2/3] [ADVARSEL] noget lytter allerede paa 8099 -- en gammel worker koerer maaske.
echo         Luk det gamle worker-vindue foerst, ellers bruger appen den GAMLE worker.
echo         Tryk en tast for at springe denne worker over.
pause >nul
goto server
:worker_start
echo   [2/3] starter worker med tools slaaet til (port 8099)...
:: Generate a tiny launch script -- no nested quotes on the start line.
> "%TEMP%\kaliv_worker.cmd" echo @echo off
>>"%TEMP%\kaliv_worker.cmd" echo cd /d "%REPO%"
>>"%TEMP%\kaliv_worker.cmd" echo set "KALIV_TOOLS_ENABLED=1"
>>"%TEMP%\kaliv_worker.cmd" echo set "PYTHONPATH=%REPO%\worker"
>>"%TEMP%\kaliv_worker.cmd" echo python -m uvicorn app.main:app --host 127.0.0.1 --port 8099
start "Kaliv worker" cmd /k "%TEMP%\kaliv_worker.cmd"

:server
:: --- 3. Server (Go exe) ----------------------------------------------------
set "SRV="
if exist "%REPO%\scripts\modelrig-server-windows-x64.exe" set "SRV=%REPO%\scripts\modelrig-server-windows-x64.exe"
if exist "%REPO%\modelrig-server-windows-x64.exe" set "SRV=%REPO%\modelrig-server-windows-x64.exe"
if exist "%USERPROFILE%\Desktop\modelrig-server-windows-x64.exe" set "SRV=%USERPROFILE%\Desktop\modelrig-server-windows-x64.exe"
if "%SRV%"=="" goto no_server
echo   [3/3] starter server: %SRV%
:: Generate a launch script that sets the bind host CLEANLY (no trailing space).
> "%TEMP%\kaliv_server.cmd" echo @echo off
>>"%TEMP%\kaliv_server.cmd" echo set "MODELRIG_HOST=0.0.0.0"
>>"%TEMP%\kaliv_server.cmd" echo "%SRV%"
start "Kaliv server" cmd /k "%TEMP%\kaliv_server.cmd"
goto health
:no_server
echo   [3/3] [ADVARSEL] finder ikke modelrig-server-windows-x64.exe
echo         Lagt den paa skrivebordet? Start serveren manuelt med to linjer:
echo             set MODELRIG_HOST=0.0.0.0
echo             modelrig-server-windows-x64.exe

:health
:: --- 4. Health check -------------------------------------------------------
echo.
echo   venter paa at riggen kommer op...
timeout /t 8 >nul
echo.
echo   === /health/full ===
curl -s "http://127.0.0.1:8099/health/full" > "%TEMP%\kaliv_health.json" 2>nul
if errorlevel 1 goto health_fail
python -c "import json; d=json.load(open(r'%TEMP%\kaliv_health.json')); print('   overall:', 'OK' if d['ok'] else 'FEJL -> '+', '.join(d['faults'])); [print('   -', k.ljust(8), 'ok' if v['ok'] else 'FEJL', '  ', v.get('detail') or v.get('device') or '') for k,v in d['checks'].items()]" 2>nul
if errorlevel 1 type "%TEMP%\kaliv_health.json"
goto done
:health_fail
echo   Kunne ikke naa workeren endnu. Giv den et par sekunder mere og koer:
echo       curl http://127.0.0.1:8099/health/full

:done
echo.
echo   Klar. Tre vinduer koerer nu (Ollama, worker, server).
echo   Luk dem for at stoppe riggen.
echo.
pause
