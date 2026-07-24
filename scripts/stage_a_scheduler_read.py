#!/usr/bin/env python3
"""Prepare only the physical scheduler pilot's read half.

The helper consumes the state written by START_STAGE_A_SCHEDULER_TEST.cmd. It
creates the exact canonical read schedule, waits for one real execution through
the running worker, pauses it, and saves a resumable checkpoint beside the
isolated scheduler databases. It does not create a write schedule, fabricate
manual observations, generate a pilot report, merge, release, or activate.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "validation" / "stage-a-runtime"
PHONE_STATE = RUNTIME / "phone-test-state.json"


class ReadPilotError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadPilotError(f"Kunne ikke læse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReadPilotError(f"{path} indeholder ikke et JSON-objekt.")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def under_runtime(path: Path) -> bool:
    try:
        return os.path.commonpath((str(RUNTIME.resolve()), str(path.resolve()))) == str(
            RUNTIME.resolve()
        )
    except (OSError, ValueError):
        return False


def bind_wizard(phone: dict[str, Any]):
    scheduler = phone.get("scheduler")
    if not isinstance(scheduler, dict):
        raise ReadPilotError("Telefon-status mangler scheduler-sektionen.")
    if not (
        scheduler.get("enabled") is True
        and scheduler.get("configured") is True
        and scheduler.get("running") is True
        and scheduler.get("resources_open") is True
    ):
        raise ReadPilotError(
            "Scheduler-teststacken er ikke klar. Start START_STAGE_A_SCHEDULER_TEST.cmd først."
        )
    if phone.get("production_activation") is not False:
        raise ReadPilotError("Telefon-status kan ikke bevise production_activation=false.")

    raw_dir = scheduler.get("data_dir")
    raw_log = scheduler.get("worker_log")
    if not isinstance(raw_dir, str) or not raw_dir.strip():
        raise ReadPilotError("Scheduler-status mangler den isolerede datamappe.")
    if not isinstance(raw_log, str) or not raw_log.strip():
        raise ReadPilotError("Scheduler-status mangler worker-loggen.")

    data_dir = Path(raw_dir)
    worker_log = Path(raw_log)
    if not under_runtime(data_dir) or not under_runtime(worker_log):
        raise ReadPilotError("Scheduler-stierne ligger ikke under Stage A-runtimeområdet.")
    if worker_log.parent.resolve() != data_dir.resolve():
        raise ReadPilotError("Worker-log og scheduler-databaser tilhører ikke samme isolerede run.")

    from scripts import scheduler_pilot_wizard as wizard

    wizard.VALIDATION = data_dir
    wizard.STATE_PATH = data_dir / "scheduler-pilot-state.json"
    wizard.LOG_PATH = worker_log
    wizard.REPORT_PATH = data_dir / "scheduler-pilot-latest.json"
    wizard.MANUAL_PATH = data_dir / "scheduler-manual-observations.json"
    wizard.SCHEDULES_DB = data_dir / "kaliv-schedules.db"
    wizard.JOBS_DB = data_dir / "modelrig-jobs.db"
    wizard.AUDIT_DB = data_dir / "kaliv-audit.db"
    return wizard, data_dir


def main() -> int:
    if os.name != "nt":
        print("  STOP  Read-piloten må kun køres på Windows-riggen.")
        return 1
    try:
        phone = load_json(PHONE_STATE)
        if phone.get("schema") != "kaliv-stage-a-phone-test-state/v2":
            raise ReadPilotError(
                "Telefon-status er ikke fra den nye scheduler-kompatible launcher."
            )
        wizard, data_dir = bind_wizard(phone)

        status = wizard.schedule_status()
        if not (
            status.get("configured") is True
            and status.get("running") is True
            and status.get("resources_open") is True
            and not status.get("last_error")
        ):
            raise ReadPilotError(f"Scheduler-endpointet er ikke klart: {status!r}")

        state = wizard.load_state()
        known_id = str(state.get("read_schedule_id") or "")
        rows = wizard.schedules()
        unexpected = [
            wizard.schedule_id(row)
            for row in rows
            if wizard.schedule_id(row) and wizard.schedule_id(row) != known_id
        ]
        if unexpected:
            raise ReadPilotError(
                "Den isolerede scheduler-store indeholder uventede planer: "
                + ", ".join(sorted(unexpected))
            )

        read_id = wizard.create_read(state)
        payload = wizard.wait_runs(read_id, 1, timeout=150.0)
        wizard.set_enabled(read_id, False)
        view = wizard.schedule_view(payload)
        state.update(
            {
                "schema": "kaliv-stage-a-scheduler-read-checkpoint/v1",
                "read_schedule_id": read_id,
                "read_executed": True,
                "read_runs_used": int(view.get("runs_used") or 0),
                "write_pending": True,
                "revocation_pending": True,
                "crash_recovery_pending": True,
                "pilot_report_generated": False,
                "production_activation": False,
            }
        )
        wizard.save_state(state)

        print("\n===============================================================")
        print("  SCHEDULERENS READ-HALVDEL ER KLAR")
        print("===============================================================")
        print(f"  Read-plan: {read_id}")
        print(f"  Runs used: {state['read_runs_used']}")
        print("  Planen er pauset igen.")
        print(f"  Checkpoint: {data_dir / 'scheduler-pilot-state.json'}")
        print("  Write, revocation og crash-recovery er fortsat pending.")
        print("  production_activation=false")
        return 0
    except (ReadPilotError, wizard.PilotError if "wizard" in locals() else ReadPilotError) as exc:
        print(f"\n  STOP  {exc}")
        print("  Der er ikke skrevet noget pilotresultat som bestået.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
