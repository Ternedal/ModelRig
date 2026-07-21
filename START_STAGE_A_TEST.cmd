@echo off
setlocal
cd /d "%~dp0"
title Kaliv Stage A test
set "PYTHONDONTWRITEBYTECODE=1"
python "%~dp0scripts\stage_a_resume_cleanup.py"
if errorlevel 1 goto failed
python "%~dp0scripts\stage_a_one_click.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto done
:failed
set "EXIT_CODE=%ERRORLEVEL%"
:done
echo.
if not "%EXIT_CODE%"=="0" echo Testen stoppede sikkert. Ret beskeden ovenfor og dobbeltklik igen.
if "%EXIT_CODE%"=="0" echo Stage A er faerdig. Vinduet kan lukkes.
echo.
pause
exit /b %EXIT_CODE%
