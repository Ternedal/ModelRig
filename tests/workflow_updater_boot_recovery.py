"""The appliance must recover an interrupted update before booting services.

Run: python3 tests/workflow_updater_boot_recovery.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTOSTART = ROOT / "scripts" / "kaliv-autostart.ps1"
BOOTSTRAP = ROOT / "scripts" / "kaliv-bootstrap.ps1"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(AUTOSTART.exists(), "the task-registration script exists")
check(BOOTSTRAP.exists(), "the recovery-first bootstrap exists")

if AUTOSTART.exists() and BOOTSTRAP.exists():
    autostart = AUTOSTART.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")

    recovery_call = re.search(
        r"&\s+\$updater\s+-dir\s+\$RepoRoot\s+-recover\s+-supervisor-task\s+\$SupervisorTaskName",
        bootstrap,
        flags=re.IGNORECASE,
    )
    start_call = re.search(
        r"Start-ScheduledTask\s+-TaskName\s+\$SupervisorTaskName",
        bootstrap,
        flags=re.IGNORECASE,
    )
    check(recovery_call is not None, "bootstrap invokes the updater's offline recovery mode")
    check(start_call is not None, "bootstrap starts the supervisor task after recovery")
    check(
        recovery_call is not None
        and start_call is not None
        and recovery_call.start() < start_call.start(),
        "recovery is ordered before supervisor startup",
    )
    check(
        "$recoveryExitCode = $LASTEXITCODE" in bootstrap
        and "if ($recoveryExitCode -ne 0)" in bootstrap,
        "the native updater exit code is checked explicitly",
    )
    check(
        "The supervisor was not started" in bootstrap,
        "failed recovery is documented as fail-closed",
    )
    check(
        "Test-Path -LiteralPath $updater -PathType Leaf" in bootstrap,
        "a missing updater blocks appliance startup",
    )

    check(
        '-TaskName "KalivBootstrap"' in autostart
        and '-TaskName "KalivSupervisor"' in autostart,
        "registration creates distinct bootstrap and supervisor tasks",
    )
    check(
        "$bootstrapTrigger = New-ScheduledTaskTrigger -AtLogOn" in autostart,
        "the logon trigger belongs to the bootstrap",
    )
    supervisor_registration = re.search(
        r"Register-ScheduledTask\s+`\s*\n\s*-TaskName\s+\"KalivSupervisor\"(?P<body>.*?)\n\s*Register-ScheduledTask",
        autostart,
        flags=re.DOTALL | re.IGNORECASE,
    )
    check(
        supervisor_registration is not None,
        "the supervisor task registration is structurally present",
    )
    check(
        supervisor_registration is not None
        and "-Trigger" not in supervisor_registration.group("body"),
        "the supervisor has no direct logon trigger and cannot race recovery",
    )
    check(
        '-File `"$bootstrap`"' in autostart,
        "the bootstrap task executes the checked-in bootstrap script",
    )
    check(
        "modelrig-updater-windows-x64.exe" in autostart
        and "kaliv-bootstrap.ps1" in autostart,
        "registration refuses to proceed when recovery components are absent",
    )

print(f"\nupdater boot recovery: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
