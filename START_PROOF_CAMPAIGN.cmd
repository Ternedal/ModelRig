@echo off
setlocal
cd /d "%~dp0"
title ModelRig - Physical Proof Campaign
set "PYTHONDONTWRITEBYTECODE=1"

rem Telefon/voice-testen skal kunne aabne en midlertidig LocalSubnet-firewallregel.
rem Dobbeltklik skal derfor selv bede om UAC i stedet for at kraeve hoejreklik.
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Starter igen som administrator - godkend kun Windows UAC-dialogen...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
  exit /b 0
)

echo ==============================================================================
echo   MODELRIG - LETTEST MULIGE FYSISKE BEVISKAMPAGNE
echo ==============================================================================
echo.
echo Dobbeltklik er nok. Launcheren klarer automatisk:
echo   - UAC/elevation
echo   - exact-head / clean-checkout / Stage A-gates
echo   - lokal loopback-parring og midlertidigt test-token - ingen tokenkopiering
echo   - Ollama/modelvalg og embeddingmodel
echo   - Agent 3, planner-eval, RAG 1k/10k, voice, scheduler og browserbevis
echo   - QR-parring til telefonen, hvor det fysiske telefontrin kraever parring
echo   - T-006 aegte hard-process recovery og lease recovery
echo   - 22 x 14 virkelige workflows = 308 workflow-executioner
echo   - T-023 fysisk UI-bevis paa Android + Windows
echo   - T-033 klargoering + one-click-fil til den anden Windows-SID
echo.
echo Du bliver kun afbrudt for handlinger, software ikke maa selvattestere:
echo   - se/hoere de konkrete fysiske resultater
echo   - trykke de noedvendige godkendelser i Kaliv
echo   - koere det ene T-033-trin under en anden Windows-konto
echo.
echo Ingen merge, release eller produktionsaktivering foretages af kampagnen.
echo Stage B updater/reboot er fortsat separat, fordi den kraever en publiceret release.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-proof-campaign-easy.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" echo HELE DEN SOURCE-BOUND BEVISKAMPAGNE ER GROEN. Se summary.json for Stage B-boundary.
if "%EXIT_CODE%"=="3" echo KAMPAGNEN MANGLER KUN ANDEN WINDOWS-SID. One-click-filen er lagt paa Public Desktop.
if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="3" echo KAMPAGNEN STOPPEDE SIKKERT. Logs og delbeviser er bevaret.
echo.
pause
exit /b %EXIT_CODE%
