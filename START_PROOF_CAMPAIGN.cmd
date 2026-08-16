@echo off
setlocal
cd /d "%~dp0"
title ModelRig - Physical Proof Campaign
set "PYTHONDONTWRITEBYTECODE=1"

rem Fysiske telefon/voice-trin kan kræve en midlertidig LocalSubnet-firewallregel.
rem Dobbeltklik skal derfor selv bede om UAC i stedet for at kræve højreklik.
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Starter igen som administrator - godkend kun Windows UAC-dialogen...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
  exit /b 0
)

echo ==============================================================================
echo   MODELRIG - FULD FYSISK BEVISKAMPAGNE
echo ==============================================================================
echo.
echo Denne ene launcher koerer saa meget automatisk som fysisk muligt:
echo   - UAC/elevation automatisk via normal Windows-dialog
echo   - exact-head / clean-checkout / Stage A-gates
echo   - lokal loopback-parring og midlertidigt proof-token - ingen tokenkopiering
echo   - Ollama/modelvalg og embeddingmodel
echo   - Agent 3, planner-eval, RAG 1k/10k, voice, scheduler og browserbevis
echo   - T-006 aegte hard-process recovery og lease recovery
echo   - 22 x 14 virkelige workflows = 308 workflow-executioner
echo   - T-023 fysisk UI-bevis paa Android + Windows
echo   - T-033 DPAPI backup/restore; kun anden Windows-SID kan ikke selvattesteres
echo.
echo Stage B updater/reboot er bevidst IKKE fake-groen: den kraever en publiceret
echo exact kandidat og at riggen starter paa forrige release. Kampagnen markerer
echo den derfor separat, hvis den release-bound forudsaetning ikke findes.
echo.
echo Du bliver KUN afbrudt for fysiske observationer/godkendelser, som software
echo ikke maa opfinde, samt Windows UAC. Proof-token oprettes automatisk via normal
echo pairing og vises eller kopieres ikke. Ingen branch-skift, merge, release eller
echo produktionsaktivering foretages af kampagnen.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-proof-campaign-easy.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" echo HELE DEN SOURCE-BOUND BEVISKAMPAGNE ER GROEN. Se summary.json for Stage B-boundary.
if "%EXIT_CODE%"=="3" echo KAMPAGNEN MANGLER KUN ET EKSPPLICIT FYSISK/TRUST-BOUND TRIN. Foelg instruktionen ovenfor og koer igen.
if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="3" echo KAMPAGNEN STOPPEDE SIKKERT. Logs og delbeviser er bevaret.
echo.
pause
exit /b %EXIT_CODE%
