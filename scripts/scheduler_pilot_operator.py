#!/usr/bin/env python3
"""Resumable operator for the physical scheduler pilot (T-019).

This tool removes avoidable rig-day work without fabricating physical evidence:
it creates the exact read grant, discovers the unique freshly approved canonical
write grant, and drives the deterministic pause barrier.  Crash remains a real
operator action: the tool arms and identifies the exact worker PID but never
terminates a process itself.

It cannot approve a write, merge, push, tag, release or activate production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.scheduler_pilot_barrier import (  # noqa: E402
    ACTIVE_NAME,
    ARM_NAME,
    ARM_SCHEMA,
    COMPLETED_NAME,
    RELEASE_NAME,
    RELEASE_SCHEMA,
)

STATE_SCHEMA = "kaliv-scheduler-pilot-operator-state/v1"
DEFAULT_STATE = ROOT / "validation" / "scheduler-pilot-operator-state.json"
DEFAULT_BARRIER = ROOT / "validation" / "scheduler-pilot-barrier"
READ_MANIFEST = {
    "tool": "rig_status",
    "args": {},
    "cadence": "every:60",
    "ttl_days": 1,
    "max_runs": 3,
}
WRITE_MANIFEST = {
    "tool": "note_append",
    "args": {"text": "pilot"},
    "cadence": "every:60",
    "ttl_days": 1,
    "max_runs": 2,
}


class OperatorError(RuntimeError):
    pass


class ScheduleApi(Protocol):
    def get(self, path: str) -> dict[str, Any]: ...
    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]: ...


class HttpScheduleApi:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def _request(
        self, path: str, *, method: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                value = json.load(response)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
            raise OperatorError(f"schedule API {method} {path} fejlede: {exc}") from exc
        if not isinstance(value, dict):
            raise OperatorError(f"schedule API {method} {path} returnerede ikke et objekt")
        return value

    def get(self, path: str) -> dict[str, Any]:
        return self._request(path, method="GET")

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(path, method="POST", body=body)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"{label} kunne ikke læses: {exc}") from exc
    if not isinstance(value, dict):
        raise OperatorError(f"{label} skal være et JSON-objekt")
    return value


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperatorError(f"git SHA kunne ikke læses: {exc}") from exc
    value = result.stdout.strip()
    if result.returncode != 0 or len(value) != 40:
        raise OperatorError("git rev-parse HEAD returnerede ikke en gyldig SHA")
    return value


def _schedule_from_envelope(value: dict[str, Any], label: str) -> dict[str, Any]:
    schedule = value.get("schedule")
    if not isinstance(schedule, dict):
        raise OperatorError(f"{label} mangler schedule-objektet")
    schedule_id = schedule.get("schedule_id")
    if not isinstance(schedule_id, str) or not schedule_id:
        raise OperatorError(f"{label} mangler schedule.schedule_id")
    return schedule


def schedule_matches(schedule: dict[str, Any], manifest: dict[str, Any]) -> bool:
    return (
        schedule.get("tool") == manifest["tool"]
        and schedule.get("args") == manifest["args"]
        and schedule.get("cadence") == manifest["cadence"]
        and schedule.get("max_runs") == manifest["max_runs"]
    )


def _fresh_receipt(detail: dict[str, Any], started_at: float) -> bool:
    receipts = detail.get("approval_receipts")
    if not isinstance(receipts, list):
        return False
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        issued = receipt.get("issued_at")
        consumed = receipt.get("consumed_at")
        if (
            isinstance(issued, (int, float))
            and isinstance(consumed, (int, float))
            and float(issued) >= started_at
            and float(consumed) >= float(issued)
        ):
            return True
    return False


@dataclass
class PilotOperator:
    api: ScheduleApi
    state_path: Path
    barrier_dir: Path
    clock: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    challenge_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32)

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {}
        state = _read_object(self.state_path, "pilot-operator state")
        if state.get("schema") != STATE_SCHEMA:
            raise OperatorError("pilot-operator state har forkert schema")
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        state["schema"] = STATE_SCHEMA
        state["production_activation"] = False
        state["updated_at"] = self.clock()
        _atomic_json(self.state_path, state)

    def prepare(self, *, candidate_sha: str) -> dict[str, Any]:
        state = self.load_state()
        if state and state.get("candidate_sha") != candidate_sha:
            raise OperatorError(
                "pilot-state tilhører en anden kandidat; arkivér den før en ny pilot"
            )
        if not state:
            state = {
                "candidate_sha": candidate_sha,
                "started_at": self.clock(),
                "phase": "prepare",
            }

        self.barrier_dir.mkdir(parents=True, exist_ok=True)
        read_id = str(state.get("read_schedule_id") or "")
        if read_id:
            detail = self.api.get(f"/schedules/{read_id}")
            schedule = _schedule_from_envelope(detail, "gemt read-plan")
            if not schedule_matches(schedule, READ_MANIFEST):
                raise OperatorError("gemt read schedule-id matcher ikke pilotmanifestet")
        else:
            self._require_quiet_inventory(exclude=set())
            self.api.post("/schedules/preview", dict(READ_MANIFEST))
            created = self.api.post("/schedules", dict(READ_MANIFEST))
            schedule = _schedule_from_envelope(created, "oprettet read-plan")
            if not schedule_matches(schedule, READ_MANIFEST):
                raise OperatorError("workeren oprettede ikke den eksakte read-plan")
            read_id = str(schedule["schedule_id"])
            state["read_schedule_id"] = read_id

        write_id = self._discover_write(state, required=False)
        if write_id:
            state["write_schedule_id"] = write_id
            state["phase"] = "ready_pause"
        else:
            state["phase"] = "awaiting_write_approval"
        self.save_state(state)
        return state

    def detect_write(self) -> dict[str, Any]:
        state = self._require_state()
        write_id = self._discover_write(state, required=True)
        state["write_schedule_id"] = write_id
        state["phase"] = "ready_pause"
        self._require_quiet_inventory(
            exclude={str(state["read_schedule_id"]), write_id}
        )
        self.save_state(state)
        return state

    def pause(self, *, wait_seconds: float = 180.0) -> dict[str, Any]:
        state = self._require_state()
        if not state.get("write_schedule_id"):
            self.detect_write()
            state = self._require_state()
        read_id = str(state["read_schedule_id"])
        self._require_quiet_inventory(
            exclude={read_id, str(state["write_schedule_id"])}
        )
        before = _schedule_from_envelope(
            self.api.get(f"/schedules/{read_id}"), "read-plan før pause"
        )
        if not before.get("enabled"):
            before = _schedule_from_envelope(
                self.api.post(f"/schedules/{read_id}/enabled", {"enabled": True}),
                "genaktiveret read-plan",
            )
        baseline_runs = int(before.get("runs_used") or 0)

        active, challenge = self._arm_or_resume(
            state,
            mode="pause_before_guard",
            schedule_id=read_id,
            wait_seconds=wait_seconds,
        )
        self.api.post(f"/schedules/{read_id}/enabled", {"enabled": False})
        self._release(active, challenge)
        completed = self._wait_json(
            self.barrier_dir / COMPLETED_NAME,
            wait_seconds,
            "released pilot-barrier receipt",
        )
        if completed.get("state") != "released" or completed.get("claim_id") != active.get("claim_id"):
            raise OperatorError("pause-barrieren afsluttede ikke released på samme claim")

        deadline = self.monotonic() + wait_seconds
        final: dict[str, Any] | None = None
        while self.monotonic() < deadline:
            final = _schedule_from_envelope(
                self.api.get(f"/schedules/{read_id}"), "read-plan efter pause"
            )
            if final.get("enabled") is False and int(final.get("runs_used") or 0) == baseline_runs:
                break
            self.sleeper(0.2)
        else:
            raise OperatorError("pause blev ikke synlig med refunderet run-budget")

        state["phase"] = "pause_done"
        state["pause"] = {
            "claim_id": active.get("claim_id"),
            "job_id": active.get("job_id"),
            "worker_pid": active.get("worker_pid"),
            "runs_used_before": baseline_runs,
            "runs_used_after": int(final.get("runs_used") or 0) if final else None,
            "api_verified": True,
            "receipt": str(self.barrier_dir / COMPLETED_NAME),
        }
        state.pop("barrier_challenge", None)
        self.save_state(state)
        return state

    def arm_crash(self, *, wait_seconds: float = 180.0) -> dict[str, Any]:
        state = self._require_state()
        if state.get("phase") not in {"pause_done", "crash_active"}:
            raise OperatorError("crash-trinnet kræver en bestået deterministisk pause")
        read_id = str(state["read_schedule_id"])
        detail = _schedule_from_envelope(
            self.api.get(f"/schedules/{read_id}"), "read-plan før crash"
        )
        if not detail.get("enabled"):
            self.api.post(f"/schedules/{read_id}/enabled", {"enabled": True})
        active, _challenge = self._arm_or_resume(
            state,
            mode="crash_before_guard",
            schedule_id=read_id,
            wait_seconds=wait_seconds,
        )
        state["phase"] = "crash_active"
        state["crash"] = {
            "claim_id": active.get("claim_id"),
            "job_id": active.get("job_id"),
            "worker_pid": active.get("worker_pid"),
            "active_receipt": str(self.barrier_dir / ACTIVE_NAME),
            "operator_must_close_exact_pid": True,
        }
        self.save_state(state)
        return state

    def status(self) -> dict[str, Any]:
        state = self.load_state()
        state["barrier_files"] = sorted(
            path.name for path in self.barrier_dir.glob("*.json")
        ) if self.barrier_dir.is_dir() else []
        return state

    def _require_state(self) -> dict[str, Any]:
        state = self.load_state()
        if not state:
            raise OperatorError("pilot-state mangler; kør prepare først")
        return state

    def _list_schedules(self) -> list[dict[str, Any]]:
        value = self.api.get("/schedules")
        schedules = value.get("schedules")
        if not isinstance(schedules, list) or not all(isinstance(x, dict) for x in schedules):
            raise OperatorError("schedule-listen har forkert format")
        return schedules

    def _discover_write(self, state: dict[str, Any], *, required: bool) -> str:
        existing = str(state.get("write_schedule_id") or "")
        if existing:
            detail = self.api.get(f"/schedules/{existing}")
            schedule = _schedule_from_envelope(detail, "gemt write-plan")
            if not schedule_matches(schedule, WRITE_MANIFEST) or not _fresh_receipt(
                detail, float(state["started_at"])
            ):
                raise OperatorError("gemt write schedule-id er ikke en frisk kanonisk grant")
            return existing

        candidates: list[str] = []
        for schedule in self._list_schedules():
            if not schedule_matches(schedule, WRITE_MANIFEST):
                continue
            schedule_id = str(schedule.get("schedule_id") or "")
            if not schedule_id:
                continue
            detail = self.api.get(f"/schedules/{schedule_id}")
            if _fresh_receipt(detail, float(state["started_at"])):
                candidates.append(schedule_id)
        if len(candidates) > 1:
            raise OperatorError(
                "flere friske kanoniske write-planer fundet; piloten er tvetydig: "
                + ", ".join(candidates)
            )
        if not candidates:
            if required:
                raise OperatorError(
                    "ingen frisk kanonisk note_append-pilot fundet; godkend præcis "
                    "tool=note_append args={\"text\":\"pilot\"} cadence=every:60 "
                    "ttl_days=1 max_runs=2 i appen"
                )
            return ""
        return candidates[0]

    def _require_quiet_inventory(self, *, exclude: set[str]) -> None:
        active = [
            str(item.get("schedule_id"))
            for item in self._list_schedules()
            if item.get("enabled") is True
            and str(item.get("schedule_id") or "") not in exclude
        ]
        if active:
            raise OperatorError(
                "andre aktive schedules kan fyre under pilotvinduet; pausér dem først: "
                + ", ".join(active)
            )

    def _clean_barrier_for_new_arm(self) -> None:
        present = [
            name
            for name in (ARM_NAME, ACTIVE_NAME, RELEASE_NAME, COMPLETED_NAME)
            if (self.barrier_dir / name).exists()
        ]
        if present:
            raise OperatorError(
                "pilot-barrier indeholder tidligere state; arkivér før nyt trin: "
                + ", ".join(present)
            )

    def _arm_or_resume(
        self,
        state: dict[str, Any],
        *,
        mode: str,
        schedule_id: str,
        wait_seconds: float,
    ) -> tuple[dict[str, Any], str]:
        active_path = self.barrier_dir / ACTIVE_NAME
        challenge = str(state.get("barrier_challenge") or "")
        if state.get("barrier_mode") == mode and challenge and active_path.is_file():
            active = _read_object(active_path, "aktiv pilot-barrier")
            if active.get("schedule_id") != schedule_id or active.get("mode") != mode:
                raise OperatorError("gemt barrier-state matcher ikke den aktive occurrence")
            return active, challenge

        self._clean_barrier_for_new_arm()
        challenge = self.challenge_factory()
        if len(challenge) < 32:
            raise OperatorError("challenge-generatoren returnerede for få tegn")
        arm = {
            "schema": ARM_SCHEMA,
            "schedule_id": schedule_id,
            "mode": mode,
            "challenge": challenge,
            "timeout_seconds": min(max(wait_seconds + 30.0, 60.0), 300.0),
            "production_activation": False,
        }
        _atomic_json(self.barrier_dir / ARM_NAME, arm)
        state["barrier_mode"] = mode
        state["barrier_challenge"] = challenge
        state["phase"] = "pause_armed" if mode == "pause_before_guard" else "crash_armed"
        self.save_state(state)
        active = self._wait_json(active_path, wait_seconds, "aktiv pilot-barrier")
        if active.get("schedule_id") != schedule_id or active.get("mode") != mode:
            raise OperatorError("aktiv barrier matcher ikke armens schedule/mode")
        expected = hashlib.sha256(challenge.encode("utf-8")).hexdigest()
        if active.get("challenge_sha256") != expected:
            raise OperatorError("aktiv barrier matcher ikke armens challenge")
        return active, challenge

    def _release(self, active: dict[str, Any], challenge: str) -> None:
        _atomic_json(
            self.barrier_dir / RELEASE_NAME,
            {
                "schema": RELEASE_SCHEMA,
                "action": "continue",
                "claim_id": active.get("claim_id"),
                "challenge": challenge,
                "production_activation": False,
            },
        )

    def _wait_json(self, path: Path, seconds: float, label: str) -> dict[str, Any]:
        deadline = self.monotonic() + seconds
        while self.monotonic() < deadline:
            if path.is_file():
                return _read_object(path, label)
            self.sleeper(0.1)
        raise OperatorError(f"timeout mens der blev ventet på {label}")


def _print_state(state: dict[str, Any]) -> None:
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    phase = state.get("phase")
    if phase == "awaiting_write_approval":
        print("\nNÆSTE: Opret/godkend den viste kanoniske note_append-plan i Android-appen.")
        print("Kør derefter samme script med --action detect-write.")
    elif phase == "ready_pause":
        print("\nNÆSTE: --action pause")
    elif phase == "pause_done":
        print("\nNÆSTE: --action arm-crash")
    elif phase == "crash_active":
        pid = (state.get("crash") or {}).get("worker_pid")
        print(f"\nFYSISK HANDLING: Luk kun worker-processen med PID {pid}.")
        print("Ingen proces afsluttes automatisk af operatøren.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=("prepare", "detect-write", "pause", "arm-crash", "status"),
        required=True,
    )
    parser.add_argument("--worker-url", default="http://127.0.0.1:8099")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--barrier-dir", type=Path, default=DEFAULT_BARRIER)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--wait-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)

    operator = PilotOperator(
        api=HttpScheduleApi(args.worker_url),
        state_path=args.state,
        barrier_dir=args.barrier_dir,
    )
    if args.action == "prepare":
        state = operator.prepare(candidate_sha=args.candidate_sha or _git_sha())
    elif args.action == "detect-write":
        state = operator.detect_write()
    elif args.action == "pause":
        state = operator.pause(wait_seconds=args.wait_seconds)
    elif args.action == "arm-crash":
        state = operator.arm_crash(wait_seconds=args.wait_seconds)
    else:
        state = operator.status()
    _print_state(state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nSIKKERT STOP: afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"\nSIKKERT STOP: {type(exc).__name__}: {str(exc)[:1000]}", file=sys.stderr)
        print("Ingen proces blev afsluttet, og intet blev merget, releaset eller aktiveret.", file=sys.stderr)
        raise SystemExit(1)
