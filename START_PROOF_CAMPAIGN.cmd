@echo off
setlocal
cd /d "%~dp0"
title ModelRig - Physical Proof Campaign
set "PYTHONDONTWRITEBYTECODE=1"

echo ==============================================================================
echo   MODELRIG - FULD FYSISK BEVISKAMPAGNE
echo ==============================================================================
echo.
echo Denne ene launcher koerer saa meget automatisk som fysisk muligt:
echo   - exact-head / clean-checkout / Stage A-gates
echo   - Agent 3, planner-eval, RAG 1k/10k, voice, scheduler og browserbevis
echo   - 22 x 14 virkelige workflows = 308 workflow-executioner
echo   - T-023 fysisk UI-bevis paa Android + Windows
echo   - T-033 DPAPI backup/restore; kun anden Windows-SID kan ikke selvattesteres
echo.
echo Du bliver KUN afbrudt for hemmeligt token, UAC/login og fysiske observationer
echo eller godkendelser som software ikke maa opfinde. Ingen branch-skift, merge,
echo release eller produktionsaktivering foretages af kampagnen.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-proof-campaign.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" echo HELE BEVISKAMPAGNEN ER GROEN.
if "%EXIT_CODE%"=="3" echo KAMPAGNEN MANGLER KUN ET EKSPPLICIT FYSISK/TRUST-BOUND TRIN. Foelg instruktionen ovenfor og koer igen.
if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="3" echo KAMPAGNEN STOPPEDE SIKKERT. Logs og delbeviser er bevaret.
echo.
pause
exit /b %EXIT_CODE%
