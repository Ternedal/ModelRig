"""Dormant file-controlled hold for the physical T-019 scheduler pilot.

The production entrypoint never imports this module. The pilot-only entrypoint
installs it before scheduler startup and only when a local control directory is
configured. One exact rig_status schedule can then be held after claim/job bind
but before the live revoke guard and ToolGate attempt marker. This makes pause
and crash observations deterministic without changing the tool or its manifest.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

SCHEMA = "kaliv-scheduler-pilot-control/v1"
_LOG = logging.getLogger("app.schedule_runner")


def _read_command(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def install_pilot_hold(runner_cls: type) -> None:
    """Install the exact pilot hold once; inert without the pilot env variable."""
    if getattr(runner_cls, "_kaliv_pilot_hold_installed", False):
        return
    original = runner_cls._run_claim

    def held_run_claim(self, claim, job_id: str, now: float):
        raw_dir = os.environ.get("KALIV_SCHEDULER_PILOT_CONTROL_DIR", "").strip()
        if not raw_dir:
            return original(self, claim, job_id, now)

        control_dir = Path(raw_dir)
        command_path = control_dir / "command.json"
        command = _read_command(command_path)
        schedule = getattr(claim, "schedule", None)
        schedule_id = str(getattr(schedule, "schedule_id", ""))
        tool = str(getattr(schedule, "tool", ""))
        current_time = time.time()
        if not (
            command
            and command.get("schema") == SCHEMA
            and command.get("action") == "hold_before_guard"
            and command.get("schedule_id") == schedule_id
            and tool == "rig_status"
            and isinstance(command.get("nonce"), str)
            and command.get("nonce")
            and isinstance(command.get("expires_at"), (int, float))
            and float(command["expires_at"]) > current_time
        ):
            return original(self, claim, job_id, now)

        nonce = str(command["nonce"])
        consumed = control_dir / f"command.consumed-{nonce}.json"
        try:
            command_path.replace(consumed)
        except OSError:
            return original(self, claim, job_id, now)

        marker = control_dir / "holding.json"
        release = control_dir / f"release-{nonce}.flag"
        timeout_s = min(max(float(command.get("timeout_seconds", 180.0)), 5.0), 300.0)
        _write_atomic(
            marker,
            {
                "schema": SCHEMA,
                "phase": "before_live_guard",
                "schedule_id": schedule_id,
                "claim_id": str(getattr(claim, "claim_id", "")),
                "job_id": job_id,
                "nonce": nonce,
                "pid": os.getpid(),
                "created_at": current_time,
                "expires_at": current_time + timeout_s,
            },
        )
        _LOG.warning(
            "scheduler pilot: occurrence held before live guard "
            "(schedule_id=%s claim_id=%s nonce=%s)",
            schedule_id,
            getattr(claim, "claim_id", ""),
            nonce,
        )

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and not release.is_file():
            time.sleep(0.1)

        timed_out = not release.is_file()
        try:
            marker.unlink(missing_ok=True)
            release.unlink(missing_ok=True)
        except OSError:
            pass
        if timed_out:
            _LOG.error(
                "scheduler pilot: hold timed out; schedule is paused before execution "
                "(schedule_id=%s nonce=%s)",
                schedule_id,
                nonce,
            )
            try:
                self.schedules.set_enabled(schedule_id, False, now=now)
            except Exception:
                pass
        return original(self, claim, job_id, now)

    runner_cls._run_claim = held_run_claim
    runner_cls._kaliv_pilot_hold_installed = True
