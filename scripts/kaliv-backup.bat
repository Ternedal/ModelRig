@echo off
REM Kaliv backup helper for Windows. Wraps `python -m worker.app.backup` so a
REM backup is one double-click, not a remembered command line.
REM
REM Reads the same env vars the worker uses (MODELRIG_DB, KALIV_AUDIT_DB, ...),
REM so it backs up the LIVE locations. Set them in modelrig.env and load that
REM first if your rig overrides the defaults.
REM
REM Usage:
REM   kaliv-backup.bat                 -> create a backup in .\backups
REM   kaliv-backup.bat verify FILE     -> check an archive
REM   kaliv-backup.bat restore FILE    -> restore (refuses to overwrite)
REM   kaliv-backup.bat restore FILE /f -> restore, overwriting existing data

setlocal
cd /d "%~dp0\.."

if "%~1"=="" (
    python -m worker.app.backup create --out backups
    goto :end
)
if /i "%~1"=="verify" (
    python -m worker.app.backup verify "%~2"
    goto :end
)
if /i "%~1"=="restore" (
    if /i "%~3"=="/f" (
        python -m worker.app.backup restore "%~2" --force
    ) else (
        python -m worker.app.backup restore "%~2"
    )
    goto :end
)
echo Unknown command: %~1
echo Usage: kaliv-backup.bat [verify FILE ^| restore FILE [/f]]
:end
endlocal
