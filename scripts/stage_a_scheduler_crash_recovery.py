#!/usr/bin/env python3
"""Exercise only the scheduler pilot's physical crash-recovery proof.

Requires the isolated scheduler stack plus completed read and revocation
checkpoints. The helper catches a real reserved read occurrence while JobStore
is backpressured, force-stops only the worker PID recorded by the phone stack,
waits for the real owner lease to expire, restarts against the same isolated
stores, and requires both the startup recovery log line and an abandoned ledger
row. It does not create a write schedule or generate the final pilot report.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMON_PATH = ROOT / "scripts" / "stage_a_scheduler_read.py"
WORKER_CMD = ROOT / "validation" / "stage-a-runtime" / "worker.cmd"


class CrashRecoveryError(RuntimeError):
    pass


def load_common():
    spec = importlib.util.spec_from_file_location(
        "stage_a_scheduler_crash_common", COMMON_PATH
    )
    if spec is None or spec.loader is None:
        raise CrashRecoveryError("Schedulerens fælles Stage A-helper kunne ikke indlæses.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise CrashRecoveryError(f"Stage A-helperen kunne ikke indlæses: {exc}") from exc
    return module


def save_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def planner_model() -> str:
    try:
        text = WORKER_CMD.read_text(encoding="ascii", errors="strict")
    except OSError as exc:
        raise CrashRecoveryError(f"Kunne ikke læse den registrerede worker-launcher: {exc}") from exc
    match = re.search(r'set "KALIV_AGENT3_PLANNER_MODEL=([^"\r\n]+)"', text)
    if match is None or not match.group(1).strip():
        raise CrashRecoveryError("Worker-launcheren indeholder ingen planner-model.")
    return match.group(1).strip()


def listener_pid(port: int) -> int | None:
    command = (
        f"$x=Get-NetTCPConnection -State Listen -LocalPort {port} "
        "-ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if($null -eq $x){exit 1}; Write-Output $x.OwningProcess"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def kill_recorded_worker(expected_pid: int) -> None:
    command = f"""
$listener=Get-NetTCPConnection -State Listen -LocalPort 8099 -ErrorAction SilentlyContinue | Select-Object -First 1
if($null -eq $listener){{exit 10}}
if([int]$listener.OwningProcess -ne {expected_pid}){{exit 11}}
$p=Get-CimInstance Win32_Process -Filter \"ProcessId={expected_pid}\" -ErrorAction SilentlyContinue
if($null -eq $p){{exit 12}}
if([string]$p.Name -ine \"python.exe\"){{exit 13}}
if([string]$p.CommandLine -notmatch \"uvicorn\\s+app\\.entrypoint:app\" -or [string]$p.CommandLine -notmatch \"--port\\s+8099\"){{exit 14}}
Stop-Process -Id {expected_pid} -Force -ErrorAction Stop
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise CrashRecoveryError(
            f"Den registrerede worker blev ikke stoppet sikkert (kontrolkode {result.returncode})."
        )


def wait_port_free(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if listener_pid(port) is None:
            return
        time.sleep(0.25)
    raise CrashRecoveryError(f"Port {port} blev ikke frigivet efter worker-crashet.")


def start_worker(wizard: Any, phone: dict[str, Any], data_dir: Path) -> tuple[int, Any]:
    scheduler = phone["scheduler"]
    secret_path = Path(str(scheduler.get("approval_secret_file") or ""))
    if not secret_path.is_file() or secret_path.parent.resolve() != data_dir.resolve():
        raise CrashRecoveryError("Schedulerens approval-secret tilhører ikke dette isolerede run.")
    secret = secret_path.read_text(encoding="ascii").strip()
    if len(secret) < 32:
        raise CrashRecoveryError("Schedulerens approval-secret er ugyldig.")

    log_path = Path(str(scheduler.get("worker_log") or ""))
    if log_path.parent.resolve() != data_dir.resolve():
        raise CrashRecoveryError("Worker-loggen tilhører ikke dette isolerede run.")

    env = wizard.controlled_worker_env()
    env.update(
        {
            "KALIV_AGENT3_ENABLED": "1",
            "KALIV_TOOLS_ENABLED": "1",
            "KALIV_AGENT3_PLANNER_MODEL": planner_model(),
            "KALIV_AGENT3_VALIDATION_REPORT": str(
                ROOT / "validation" / "agent3-rig-validation-latest.json"
            ),
            "KALIV_SCHEDULER_POLL_S": "5",
            "KALIV_SCHEDULER_APPROVAL_SECRET": secret,
            "KALIV_TOOLS_STATE": str(data_dir / "kaliv-tools-state.json"),
            "KALIV_TOOLS_DIR": str(data_dir / "tools"),
        }
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab", buffering=0)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "uvicorn",
            "app.entrypoint:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8099",
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    try:
        wizard.wait_endpoint(f"{wizard.WORKER_URL}/healthz", timeout=90.0)
        wizard.wait_for_first_tick(timeout=20.0)
        actual_pid = listener_pid(8099)
        if actual_pid != process.pid:
            raise CrashRecoveryError(
                f"Den genstartede worker ejer ikke port 8099 ({process.pid} != {actual_pid})."
            )
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        log.close()
        raise
    log.close()
    return process.pid, process


def main() -> int:
    if os.name != "nt":
        print("  STOP  Crash-recovery-testen må kun køres på Windows-riggen.")
        return 1

    common = None
    wizard = None
    try:
        common = load_common()
        phone = common.load_json(common.PHONE_STATE)
        if phone.get("schema") != "kaliv-stage-a-phone-test-state/v2":
            raise CrashRecoveryError("Telefon-status er ikke scheduler-kompatibel.")
        wizard, data_dir = common.bind_wizard(phone)
        state = wizard.load_state()

        if state.get("revocation_confirmed") is not True:
            raise CrashRecoveryError(
                "Revocation-checkpointet mangler. Kør RUN_STAGE_A_SCHEDULER_REVOCATION.cmd først."
            )
        if state.get("crash_recovery_confirmed") is True:
            print("  OK  Crash-recovery-beviset er allerede gemt for dette isolerede run.")
            return 0
        read_id = str(state.get("read_schedule_id") or "")
        if not read_id:
            raise CrashRecoveryError("Checkpointet indeholder ingen read-plan.")
        if state.get("write_pending") is not True:
            raise CrashRecoveryError("Write-status er uventet; crash-recovery skal køres før write.")

        detail = wizard.schedule_view(wizard.detail(read_id))
        if not wizard.matches_manifest(detail, wizard.READ_SPEC):
            raise CrashRecoveryError("Read-planen matcher ikke det kanoniske pilotmanifest.")

        expected_pid = int(phone.get("worker_pid") or 0)
        if expected_pid <= 0 or listener_pid(8099) != expected_pid:
            raise CrashRecoveryError("Den registrerede Stage A-worker matcher ikke port 8099.")

        print("\n===============================================================")
        print("  AUTOMATISK SCHEDULER CRASH-RECOVERY")
        print("===============================================================")
        print("  Fanger en durable claim, crasher den registrerede worker og venter på ægte recovery.")

        due, before, _ = wizard.prepare_aligned_schedule(read_id)
        wizard.wait_until(due + 2.5)
        claim = None
        with wizard.lock_job_store():
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                claim = wizard.reserved_after(read_id, before)
                if claim is not None:
                    kill_recorded_worker(expected_pid)
                    break
                time.sleep(0.02)
        if claim is None:
            raise CrashRecoveryError("Crash-claim blev ikke fanget; kør trinnet igen.")
        claim_id = str(claim.get("claim_id") or "")
        if not claim_id:
            raise CrashRecoveryError("Crash-occurrencen mangler claim_id.")

        wait_port_free(8099)
        wizard.wait_for_lease_expiry()
        offset = wizard.LOG_PATH.stat().st_size if wizard.LOG_PATH.is_file() else 0
        new_pid, _process = start_worker(wizard, phone, data_dir)
        recovery_line = wizard.wait_for_recovery_line(offset, timeout=120.0)
        wizard.wait_occurrence(claim_id, "abandoned", timeout=30.0)
        wizard.set_enabled(read_id, False)

        phone["worker_pid"] = new_pid
        save_json(common.PHONE_STATE, phone)
        state.update(
            {
                "crash_recovery_pending": False,
                "crash_recovery_confirmed": True,
                "crash_claim_id": claim_id,
                "recovery_line": recovery_line,
                "restarted_worker_pid": new_pid,
                "write_pending": True,
                "pilot_report_generated": False,
                "production_activation": False,
            }
        )
        wizard.save_state(state)

        print("\n===============================================================")
        print("  CRASH-RECOVERY-BEVISET ER GEMT")
        print("===============================================================")
        print(f"  Claim: {claim_id} -> abandoned")
        print(f"  Log:   {recovery_line}")
        print(f"  Ny worker-PID: {new_pid}")
        print(f"  Checkpoint: {data_dir / 'scheduler-pilot-state.json'}")
        print("  Write-godkendelse og samlet pilotrapport er fortsat pending.")
        print("  production_activation=false")
        return 0
    except Exception as exc:
        expected = isinstance(exc, CrashRecoveryError) or (
            common is not None and isinstance(exc, common.ReadPilotError)
        ) or (
            wizard is not None and isinstance(exc, wizard.PilotError)
        )
        if not expected:
            raise
        print(f"\n  STOP  {exc}")
        print("  Der er ikke skrevet noget crash-recovery- eller pilotresultat som bestået.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
