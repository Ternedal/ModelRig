@echo off
setlocal enabledelayedexpansion
:: ===========================================================================
::  Kaliv rig launcher -- starts the whole stack in one double-click.
::
::  Why this exists: the rig needs three processes (Ollama, the Python worker,
::  the Go server) with specific env vars. The #1 footgun is forgetting
::  MODELRIG_HOST=0.0.0.0 on the server, after which the phone silently cannot
::  reach the rig. This script sets everything correctly, in order, and then
::  asks /health/full whether the rig actually came up -- so you know it is
::  green BEFORE you pick up the phone.
::
::  It runs the worker from THIS script's own folder (%~dp0..\worker), which
::  also sidesteps the stale-copy trap: whichever repo copy you launch from is
::  the one that runs. No more debugging modelrig-new while modelrig-mono runs.
:: ===========================================================================

set "REPO=%~dp0.."
pushd "%REPO%" >nul
set "REPO=%CD%"
popd >nul

echo(
echo   Kaliv rig launcher
echo   repo: %REPO%
echo(

:: --- 1. Ollama -------------------------------------------------------------
:: Only start it if it is not already serving on 11434.
curl -s -o nul http://127.0.0.1:11434/api/tags
if errorlevel 1 (
    echo   [1/3] starter Ollama...
    start "Ollama" cmd /k "ollama serve"
    timeout /t 3 >nul
) else (
    echo   [1/3] Ollama koerer allerede.
)

:: --- 2. Worker (Python) ----------------------------------------------------
:: Runs from THIS repo's worker/ folder. Requires Python on PATH.
if not exist "%REPO%\worker\app\main.py" (
    echo   [FEJL] finder ikke worker\app\main.py under %REPO%
    echo          Ligger start-kaliv.bat i den rigtige repo-kopi?
    pause & exit /b 1
)
curl -s -o nul http://127.0.0.1:8099/health
if not errorlevel 1 (
    echo   [2/3] [ADVARSEL] noget lytter allerede paa 8099 -- en gammel worker koerer maaske.
    echo         Luk det gamle worker-vindue foerst, ellers bruger appen den GAMLE worker.
    echo         Trykker du en tast, springer jeg denne worker over.
    pause >nul
) else (
    echo   [2/3] starter worker med tools slaaet til (port 8099)...
    start "Kaliv worker" cmd /k "cd /d "%REPO%" && set "KALIV_TOOLS_ENABLED=1"& set "PYTHONPATH=%REPO%\worker"& python -m uvicorn app.main:app --host 127.0.0.1 --port 8099"
)

:: --- 3. Server (Go exe) ----------------------------------------------------
:: The exe is a CI artifact. Look next to this script, then in the repo root,
:: then on the Desktop -- the usual spots. MODELRIG_HOST=0.0.0.0 is the whole
:: point: without it the server binds to loopback and the phone cannot connect.
set "SRV="
for %%D in ("%REPO%\scripts" "%REPO%" "%USERPROFILE%\Desktop") do (
    if exist "%%~D\modelrig-server-windows-x64.exe" set "SRV=%%~D\modelrig-server-windows-x64.exe"
)
if "%SRV%"=="" (
    echo   [3/3] [ADVARSEL] finder ikke modelrig-server-windows-x64.exe
    echo         Lagt den paa skrivebordet? Start serveren manuelt med:
    echo             set MODELRIG_HOST=0.0.0.0 ^&^& modelrig-server-windows-x64.exe
) else (
    echo   [3/3] starter server: %SRV%
    start "Kaliv server" cmd /k "set "MODELRIG_HOST=0.0.0.0"& "%SRV%""
)

:: --- 4. Health check -------------------------------------------------------
:: Give the worker a moment to boot, then ask it how the whole chain is doing.
echo(
echo   venter paa at riggen kommer op...
timeout /t 8 >nul
echo(
echo   === /health/full ===
curl -s "http://127.0.0.1:8099/health/full" > "%TEMP%\kaliv_health.json" 2>nul
if errorlevel 1 (
    echo   Kunne ikke naa workeren endnu. Giv den et par sekunder mere og koer:
    echo       curl http://127.0.0.1:8099/health/full
) else (
    python -c "import json,sys; d=json.load(open(r'%TEMP%\kaliv_health.json')); print('   overall:', 'OK' if d['ok'] else 'FEJL -> '+', '.join(d['faults'])); [print(f'   - {k:8} {\"ok\" if v[\"ok\"] else \"FEJL\"}   {v.get(\"detail\") or v.get(\"device\") or \"\"}') for k,v in d['checks'].items()]" 2>nul || type "%TEMP%\kaliv_health.json"
)
echo(
echo   Klar. Tre vinduer koerer nu (Ollama, worker, server).
echo   Luk dem for at stoppe riggen.
echo(
pause
