@echo off
setlocal
cd /d "%~dp0"
title ModelRig - Physical Proof Campaign
set "PYTHONDONTWRITEBYTECODE=1"

rem Telefon/voice-bevis kan kraeve elevation senere i den eksisterende proof-engine.
rem Dobbeltklik beder derfor selv om UAC; pairing-bootstrapen bruger kun loopback.
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Starter igen som administrator - godkend Windows UAC-dialogen...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
  exit /b 0
)

echo ==============================================================================
echo   MODELRIG - FULD FYSISK BEVISKAMPAGNE
echo ==============================================================================
echo.
echo Dobbeltklik er nok til software-klargoeringen:
echo   - exact-head / clean-checkout / Stage A-gates
echo   - separat, ejet loopback-pairing via normal pair/start + pair/claim
echo   - proof-token bliver ikke vist, kopieret eller skrevet til disk
echo   - eksisterende listeners paa 8080/8099 roeres ikke af pairing-bootstrapen
echo   - Agent 3, planner-eval, RAG, voice, scheduler og browserbevis
echo   - T-006 hard-process recovery og lease recovery
echo   - workflow-bevis med den aktuelle spec-cardinalitet
echo   - T-023 fysisk UI-bevis paa Android + Windows
echo   - T-033 DPAPI backup/restore med en reelt anden Windows-SID
echo.
echo Fysiske observationer og godkendelser bliver stadig ALDRIG auto-attesteret.
echo Skip/reuse er fortsat fail-closed, og Stage B release/reboot er separat.
echo Ingen merge, release eller produktionsaktivering foretages af kampagnen.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-proof-campaign-owned-pairing.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" echo HELE DEN SOURCE-BOUND BEVISKAMPAGNE ER GROEN. Se summary.json for Stage B-boundary.
if "%EXIT_CODE%"=="3" echo KAMPAGNEN MANGLER KUN ET EKSPPLICIT FYSISK/TRUST-BOUND TRIN. Foelg instruktionen ovenfor og koer igen.
if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="3" echo KAMPAGNEN STOPPEDE SIKKERT. Logs og delbeviser er bevaret.
echo.
pause
exit /b %EXIT_CODE%
