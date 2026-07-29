#!/usr/bin/env python3
"""T-019 deterministic physical-pilot barrier contract.

Run: PYTHONPATH=worker python3 tests/worker_scheduler_pilot_barrier.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.scheduler_pilot_barrier import (  # noqa: E402
    ACTIVE_NAME,
    ARM_NAME,
    ARM_SCHEMA,
    COMPLETED_NAME,
    ENV_BARRIER_DIR,
    RELEASE_NAME,
    RELEASE_SCHEMA,
    PilotBarrierController,
    PilotBarrierError,
    install_pilot_barrier,
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


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def arm(directory: Path, schedule_id: str, challenge: str, *, mode="pause_before_guard", timeout=2.0):
    write_json(
        directory / ARM_NAME,
        {
            "schema": ARM_SCHEMA,
            "schedule_id": schedule_id,
            "mode": mode,
            "challenge": challenge,
            "timeout_seconds": timeout,
            "production_activation": False,
        },
    )


def release(directory: Path, claim_id: str, challenge: str):
    write_json(
        directory / RELEASE_NAME,
        {
            "schema": RELEASE_SCHEMA,
            "action": "continue",
            "claim_id": claim_id,
            "challenge": challenge,
            "production_activation": False,
        },
    )


# Dormant controller path: no arm means no files, no delay and no hidden state.
with tempfile.TemporaryDirectory(prefix="pilot-barrier-dormant-") as td:
    directory = Path(td)
    result = PilotBarrierController(directory).hold(
        schedule_id="read-1", claim_id="claim-1", job_id="job-1"
    )
    check(not result.armed, "no arm keeps the barrier dormant")
    check(list(directory.iterdir()) == [], "dormant path writes no files")

# An arm for another schedule remains untouched; a different occurrence cannot steal it.
with tempfile.TemporaryDirectory(prefix="pilot-barrier-mismatch-") as td:
    directory = Path(td)
    challenge = "m" * 40
    arm(directory, "read-target", challenge)
    result = PilotBarrierController(directory).hold(
        schedule_id="other", claim_id="claim-other", job_id="job-other"
    )
    check(not result.armed, "mismatched schedule does not enter the barrier")
    check((directory / ARM_NAME).is_file(), "mismatched schedule does not consume the arm")

# Matching pause arm: active receipt appears, contains no raw challenge, and a bound
# release lets the existing execution continue exactly once.
with tempfile.TemporaryDirectory(prefix="pilot-barrier-release-") as td:
    directory = Path(td)
    challenge = "pause-challenge-" + "x" * 32
    arm(directory, "read-1", challenge)
    result_box = []
    error_box = []

    def hold_pause():
        try:
            result_box.append(
                PilotBarrierController(directory, poll_seconds=0.01).hold(
                    schedule_id="read-1", claim_id="claim-1", job_id="job-1"
                )
            )
        except Exception as exc:
            error_box.append(exc)

    thread = threading.Thread(target=hold_pause)
    thread.start()
    deadline = time.time() + 2.0
    while not (directory / ACTIVE_NAME).is_file() and time.time() < deadline:
        time.sleep(0.01)
    check((directory / ACTIVE_NAME).is_file(), "matching occurrence produces active receipt")
    active = json.loads((directory / ACTIVE_NAME).read_text(encoding="utf-8"))
    check(active["schedule_id"] == "read-1" and active["claim_id"] == "claim-1", "active receipt binds schedule and claim")
    check(active["job_id"] == "job-1" and isinstance(active["worker_pid"], int), "active receipt binds job and worker pid")
    check(challenge not in json.dumps(active), "active receipt stores only challenge digest")
    check(active["production_activation"] is False, "active receipt preserves production_activation=false")
    release(directory, "claim-1", challenge)
    thread.join(2.0)
    check(not thread.is_alive() and not error_box, "valid release unblocks the occurrence")
    check(result_box and result_box[0].released and not result_box[0].timed_out, "release result is explicit")
    check(not (directory / ARM_NAME).exists(), "arm is one-use and consumed")
    check(not (directory / ACTIVE_NAME).exists(), "active receipt is retired after release")
    completed = json.loads((directory / COMPLETED_NAME).read_text(encoding="utf-8"))
    check(completed["state"] == "released", "completed receipt records released state")
    second = PilotBarrierController(directory).hold(
        schedule_id="read-1", claim_id="claim-2", job_id="job-2"
    )
    check(not second.armed, "same arm cannot block a second occurrence")

# Wrong release data fails closed instead of silently continuing.
with tempfile.TemporaryDirectory(prefix="pilot-barrier-wrong-release-") as td:
    directory = Path(td)
    challenge = "correct-" + "c" * 32
    arm(directory, "read-2", challenge)
    error_box = []

    def hold_wrong_release():
        try:
            PilotBarrierController(directory, poll_seconds=0.01).hold(
                schedule_id="read-2", claim_id="claim-2", job_id="job-2"
            )
        except Exception as exc:
            error_box.append(exc)

    thread = threading.Thread(target=hold_wrong_release)
    thread.start()
    deadline = time.time() + 2.0
    while not (directory / ACTIVE_NAME).is_file() and time.time() < deadline:
        time.sleep(0.01)
    release(directory, "wrong-claim", challenge)
    thread.join(2.0)
    check(error_box and isinstance(error_box[0], PilotBarrierError), "wrong release fails closed with typed error")
    check((directory / ACTIVE_NAME).is_file(), "failed release leaves active evidence for diagnosis")

# Crash mode has a deterministic bounded timeout. A fake monotonic clock makes the
# test instant while exercising the same loop and receipt path.
with tempfile.TemporaryDirectory(prefix="pilot-barrier-timeout-") as td:
    directory = Path(td)
    challenge = "crash-" + "z" * 32
    arm(directory, "read-3", challenge, mode="crash_before_guard", timeout=0.05)
    fake_now = [0.0]

    def fake_sleep(seconds):
        fake_now[0] += seconds

    result = PilotBarrierController(
        directory,
        clock=lambda: fake_now[0],
        sleeper=fake_sleep,
        poll_seconds=0.01,
    ).hold(schedule_id="read-3", claim_id="claim-3", job_id="job-3")
    check(result.armed and result.timed_out and not result.released, "crash barrier timeout is bounded and explicit")
    completed = json.loads((directory / COMPLETED_NAME).read_text(encoding="utf-8"))
    check(completed["state"] == "timed_out", "timeout receipt remains inspectable")

# Integration wrapper: env unset calls the original method directly. Env + matching
# arm holds before the original _run_claim and then returns the original outcome.
class FakeRunner:
    def __init__(self):
        self.calls = []

    def _run_claim(self, claim, job_id, now):
        self.calls.append((claim.claim_id, job_id, now))
        return "completed"


install_pilot_barrier(FakeRunner)
install_pilot_barrier(FakeRunner)
runner = FakeRunner()
old_env = os.environ.pop(ENV_BARRIER_DIR, None)
try:
    plain_claim = SimpleNamespace(
        claim_id="plain-claim",
        schedule=SimpleNamespace(schedule_id="plain-schedule"),
    )
    check(runner._run_claim(plain_claim, "plain-job", 1.0) == "completed", "unset env preserves original result")
    check(runner.calls == [("plain-claim", "plain-job", 1.0)], "unset env calls original exactly once")

    with tempfile.TemporaryDirectory(prefix="pilot-barrier-wrapper-") as td:
        directory = Path(td)
        challenge = "wrapper-" + "w" * 32
        arm(directory, "wrapped-schedule", challenge)
        os.environ[ENV_BARRIER_DIR] = str(directory)
        wrapped_claim = SimpleNamespace(
            claim_id="wrapped-claim",
            schedule=SimpleNamespace(schedule_id="wrapped-schedule"),
        )
        wrapped_result = []
        thread = threading.Thread(
            target=lambda: wrapped_result.append(
                runner._run_claim(wrapped_claim, "wrapped-job", 2.0)
            )
        )
        thread.start()
        deadline = time.time() + 2.0
        while not (directory / ACTIVE_NAME).is_file() and time.time() < deadline:
            time.sleep(0.01)
        check(thread.is_alive(), "wrapper holds before original _run_claim")
        check(len(runner.calls) == 1, "original method has not run while barrier is active")
        release(directory, "wrapped-claim", challenge)
        thread.join(2.0)
        check(wrapped_result == ["completed"], "wrapper preserves original outcome after release")
        check(runner.calls[-1] == ("wrapped-claim", "wrapped-job", 2.0), "wrapper enters original once after release")
finally:
    if old_env is None:
        os.environ.pop(ENV_BARRIER_DIR, None)
    else:
        os.environ[ENV_BARRIER_DIR] = old_env

# An explicitly configured missing directory is an operator error, not a silent no-op.
os.environ[ENV_BARRIER_DIR] = str(Path(tempfile.gettempdir()) / "kaliv-missing-pilot-barrier-dir")
try:
    missing_claim = SimpleNamespace(
        claim_id="missing-claim",
        schedule=SimpleNamespace(schedule_id="missing-schedule"),
    )
    missing_error = None
    try:
        runner._run_claim(missing_claim, "missing-job", 3.0)
    except Exception as exc:
        missing_error = exc
    check(isinstance(missing_error, PilotBarrierError), "configured missing directory fails closed")
finally:
    os.environ.pop(ENV_BARRIER_DIR, None)

print(f"\n===== SCHEDULER PILOT BARRIER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
