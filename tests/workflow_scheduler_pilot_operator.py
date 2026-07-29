#!/usr/bin/env python3
"""T-019 resumable scheduler-pilot operator contract.

Run: PYTHONPATH=worker python3 tests/workflow_scheduler_pilot_operator.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "worker"))

from scheduler_pilot_operator import (  # noqa: E402
    ACTIVE_NAME,
    ARM_NAME,
    COMPLETED_NAME,
    OperatorError,
    PilotOperator,
    READ_MANIFEST,
    RELEASE_NAME,
    STATE_SCHEMA,
    WRITE_MANIFEST,
    schedule_matches,
)

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def clone(value):
    return json.loads(json.dumps(value))


class FakeApi:
    def __init__(self, now: float):
        self.now = now
        self.schedules: dict[str, dict] = {}
        self.receipts: dict[str, list[dict]] = {}
        self.requests: list[tuple[str, str, dict | None]] = []
        self._next = 1

    def add(self, schedule: dict, receipts=None):
        sid = schedule["schedule_id"]
        self.schedules[sid] = clone(schedule)
        self.receipts[sid] = clone(receipts or [])

    def get(self, path: str):
        self.requests.append(("GET", path, None))
        if path == "/schedules":
            return {"schedules": [clone(x) for x in self.schedules.values()]}
        if path.startswith("/schedules/"):
            sid = path.rsplit("/", 1)[-1]
            if sid not in self.schedules:
                raise OperatorError(f"missing fake schedule {sid}")
            return {
                "schedule": clone(self.schedules[sid]),
                "approval_receipts": clone(self.receipts.get(sid, [])),
            }
        raise OperatorError(f"unexpected GET {path}")

    def post(self, path: str, body: dict):
        self.requests.append(("POST", path, clone(body)))
        if path == "/schedules/preview":
            return {"preview": clone(body), "executed": False, "schedule_persisted": False}
        if path == "/schedules":
            sid = f"read-{self._next}"
            self._next += 1
            schedule = {
                "schedule_id": sid,
                **clone(body),
                "enabled": True,
                "runs_used": 0,
                "approval_valid": True,
            }
            self.add(schedule)
            # Real API wraps the id under schedule. This catches the old wizard bug.
            return {"schedule": clone(schedule), "executed": False}
        if path.endswith("/enabled"):
            sid = path.split("/")[2]
            self.schedules[sid]["enabled"] = bool(body["enabled"])
            return {"schedule": clone(self.schedules[sid]), "executed": False}
        raise OperatorError(f"unexpected POST {path}")


def write_schedule(sid: str, *, now: float, enabled=True):
    return {
        "schedule_id": sid,
        **clone(WRITE_MANIFEST),
        "enabled": enabled,
        "runs_used": 0,
        "approval_valid": True,
    }, [
        {
            "device_id": "pixel-6a",
            "issued_at": now + 1,
            "consumed_at": now + 2,
            "fingerprint": "f" * 64,
        }
    ]


def barrier_worker(directory: Path, api: FakeApi, read_id: str, *, stop_after_active=False):
    deadline = time.time() + 4.0
    while not (directory / ARM_NAME).is_file() and time.time() < deadline:
        time.sleep(0.01)
    if not (directory / ARM_NAME).is_file():
        return
    arm = json.loads((directory / ARM_NAME).read_text(encoding="utf-8"))
    (directory / ARM_NAME).unlink()
    baseline = int(api.schedules[read_id].get("runs_used") or 0)
    api.schedules[read_id]["runs_used"] = baseline + 1
    active = {
        "schema": "kaliv-scheduler-pilot-barrier-receipt/v1",
        "state": "active",
        "mode": arm["mode"],
        "schedule_id": read_id,
        "claim_id": f"claim-{arm['mode']}",
        "job_id": f"job-{arm['mode']}",
        "worker_pid": 4242,
        "challenge_sha256": hashlib.sha256(arm["challenge"].encode()).hexdigest(),
        "production_activation": False,
    }
    (directory / ACTIVE_NAME).write_text(json.dumps(active), encoding="utf-8")
    if stop_after_active:
        return
    while not (directory / RELEASE_NAME).is_file() and time.time() < deadline:
        time.sleep(0.01)
    release = json.loads((directory / RELEASE_NAME).read_text(encoding="utf-8"))
    assert release["claim_id"] == active["claim_id"]
    assert release["challenge"] == arm["challenge"]
    api.schedules[read_id]["runs_used"] = baseline
    (directory / RELEASE_NAME).unlink()
    (directory / ACTIVE_NAME).unlink()
    completed = {**active, "state": "released"}
    (directory / COMPLETED_NAME).write_text(json.dumps(completed), encoding="utf-8")


check(
    schedule_matches(
        {"schedule_id": "x", **clone(READ_MANIFEST), "enabled": True},
        READ_MANIFEST,
    ),
    "manifest matcher ignores response-only fields but keeps exact action/cadence/budget",
)
check(
    not schedule_matches(
        {"schedule_id": "x", **clone(READ_MANIFEST), "max_runs": 4},
        READ_MANIFEST,
    ),
    "manifest matcher rejects a changed run budget",
)

with tempfile.TemporaryDirectory(prefix="pilot-operator-") as td:
    root = Path(td)
    state_path = root / "state.json"
    barrier = root / "barrier"
    now = 2_000_000_000.0
    api = FakeApi(now)
    operator = PilotOperator(
        api=api,
        state_path=state_path,
        barrier_dir=barrier,
        clock=lambda: now,
        challenge_factory=lambda: "operator-challenge-" + "x" * 32,
    )

    prepared = operator.prepare(candidate_sha="a" * 40)
    check(prepared["schema"] == STATE_SCHEMA, "prepare writes versioned state")
    check(prepared["read_schedule_id"] == "read-1", "prepare extracts nested schedule.schedule_id")
    check(prepared["phase"] == "awaiting_write_approval", "prepare stops honestly for physical approval")
    check(prepared["production_activation"] is False, "operator state preserves production_activation=false")
    read = api.schedules["read-1"]
    check(schedule_matches(read, READ_MANIFEST), "prepare creates the exact canonical read grant")
    create_calls = [r for r in api.requests if r[0] == "POST" and r[1] == "/schedules"]
    check(len(create_calls) == 1, "resume does not create duplicate read grants")
    operator.prepare(candidate_sha="a" * 40)
    create_calls = [r for r in api.requests if r[0] == "POST" and r[1] == "/schedules"]
    check(len(create_calls) == 1, "second prepare reuses only its state-bound read id")

    stale, stale_receipts = write_schedule("write-stale", now=now - 1000)
    stale_receipts[0]["issued_at"] = now - 500
    stale_receipts[0]["consumed_at"] = now - 499
    stale["enabled"] = False
    api.add(stale, stale_receipts)
    fresh, fresh_receipts = write_schedule("write-fresh", now=now)
    api.add(fresh, fresh_receipts)
    detected = operator.detect_write()
    check(detected["write_schedule_id"] == "write-fresh", "detect-write selects the unique fresh approved grant")
    check(detected["phase"] == "ready_pause", "fresh approval advances to deterministic pause")

    pause_thread = threading.Thread(
        target=barrier_worker,
        args=(barrier, api, "read-1"),
    )
    pause_thread.start()
    paused = operator.pause(wait_seconds=2.0)
    pause_thread.join(2.0)
    check(not pause_thread.is_alive(), "pause barrier completes without timing luck")
    check(paused["phase"] == "pause_done", "pause advances resumable state")
    check(paused["pause"]["api_verified"] is True, "pause verifies disabled state and refunded budget")
    check(paused["pause"]["runs_used_before"] == paused["pause"]["runs_used_after"], "pause proves reserved run was refunded")
    pause_receipt = Path(paused["pause"]["receipt"])
    check(pause_receipt.is_file(), "pause receipt is archived for later report binding")
    check(not (barrier / COMPLETED_NAME).exists(), "archive clears the one-shot barrier for crash")
    check(api.schedules["read-1"]["enabled"] is False, "read grant remains paused after deterministic revocation")

    crash_thread = threading.Thread(
        target=barrier_worker,
        args=(barrier, api, "read-1"),
        kwargs={"stop_after_active": True},
    )
    crash_thread.start()
    crash = operator.arm_crash(wait_seconds=2.0)
    crash_thread.join(2.0)
    check(crash["phase"] == "crash_active", "crash step stops before any automatic termination")
    check(crash["crash"]["worker_pid"] == 4242, "crash state identifies the exact worker PID")
    check(crash["crash"]["operator_must_close_exact_pid"] is True, "state requires a real operator process action")
    check((barrier / ACTIVE_NAME).is_file(), "crash leaves active receipt for restart evidence")
    check(not (barrier / RELEASE_NAME).exists(), "crash arm never releases or executes automatically")

with tempfile.TemporaryDirectory(prefix="pilot-operator-ambiguous-") as td:
    root = Path(td)
    now = 2_100_000_000.0
    api = FakeApi(now)
    operator = PilotOperator(
        api=api,
        state_path=root / "state.json",
        barrier_dir=root / "barrier",
        clock=lambda: now,
        challenge_factory=lambda: "ambiguous-challenge-" + "y" * 32,
    )
    state = operator.prepare(candidate_sha="b" * 40)
    for sid in ("write-a", "write-b"):
        schedule, receipts = write_schedule(sid, now=now)
        api.add(schedule, receipts)
    ambiguous = None
    try:
        operator.detect_write()
    except Exception as exc:
        ambiguous = exc
    check(isinstance(ambiguous, OperatorError), "multiple fresh write grants fail closed")
    check("tvetydig" in str(ambiguous), "ambiguity error explains why operator stopped")

with tempfile.TemporaryDirectory(prefix="pilot-operator-inventory-") as td:
    root = Path(td)
    now = 2_200_000_000.0
    api = FakeApi(now)
    api.add(
        {
            "schedule_id": "other-active",
            "tool": "rig_status",
            "args": {},
            "cadence": "every:300",
            "max_runs": 0,
            "enabled": True,
            "runs_used": 0,
        }
    )
    operator = PilotOperator(
        api=api,
        state_path=root / "state.json",
        barrier_dir=root / "barrier",
        clock=lambda: now,
    )
    inventory_error = None
    try:
        operator.prepare(candidate_sha="c" * 40)
    except Exception as exc:
        inventory_error = exc
    check(isinstance(inventory_error, OperatorError), "other active schedules block a contaminated pilot window")
    check("pausér dem først" in str(inventory_error), "inventory stop names the safe operator action")

print(f"\n===== SCHEDULER PILOT OPERATOR: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
