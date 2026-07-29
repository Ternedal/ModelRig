"""Deterministic physical-pilot barrier for scheduler fault injection (T-019).

The barrier is completely dormant unless ``KALIV_SCHEDULER_PILOT_BARRIER_DIR``
points at a local directory containing ``arm.json``.  A matching one-shot arm
holds exactly one named schedule occurrence after its job has been created and
bound, but before the runner re-checks the live grant and before ToolGate can
perform a side effect.

This removes timing luck from the physical pause/crash pilot while preserving
the production path: no env variable means one branch check and no filesystem
access.  The barrier never approves, executes, merges, releases or activates
anything.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("app.schedule_runner")
ENV_BARRIER_DIR = "KALIV_SCHEDULER_PILOT_BARRIER_DIR"
ARM_SCHEMA = "kaliv-scheduler-pilot-barrier-arm/v1"
RELEASE_SCHEMA = "kaliv-scheduler-pilot-barrier-release/v1"
RECEIPT_SCHEMA = "kaliv-scheduler-pilot-barrier-receipt/v1"
ARM_NAME = "arm.json"
ACTIVE_NAME = "active.json"
RELEASE_NAME = "release.json"
COMPLETED_NAME = "completed.json"
VALID_MODES = frozenset({"pause_before_guard", "crash_before_guard"})


class PilotBarrierError(RuntimeError):
    """The explicitly armed validation barrier is malformed or inconsistent."""


@dataclass(frozen=True)
class PilotBarrierResult:
    armed: bool
    mode: str | None = None
    released: bool = False
    timed_out: bool = False
    receipt_path: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        raise PilotBarrierError(f"{label} kunne ikke læses: {exc}") from exc
    if not isinstance(value, dict):
        raise PilotBarrierError(f"{label} skal være et JSON-objekt")
    return value


def _challenge_digest(challenge: str) -> str:
    return hashlib.sha256(challenge.encode("utf-8")).hexdigest()


class PilotBarrierController:
    """One-shot local-file barrier with bounded waiting and explicit receipts."""

    def __init__(
        self,
        directory: Path,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        poll_seconds: float = 0.1,
    ) -> None:
        self.directory = Path(directory)
        self.clock = clock
        self.sleeper = sleeper
        self.poll_seconds = max(0.001, float(poll_seconds))

    def hold(self, *, schedule_id: str, claim_id: str, job_id: str) -> PilotBarrierResult:
        arm_path = self.directory / ARM_NAME
        if not arm_path.is_file():
            return PilotBarrierResult(armed=False)

        preview = _read_object(arm_path, "pilot-barrier arm")
        if preview.get("schedule_id") != schedule_id:
            return PilotBarrierResult(armed=False)

        claiming = self.directory / f"arm.claiming-{os.getpid()}.json"
        try:
            os.replace(arm_path, claiming)
        except FileNotFoundError:
            return PilotBarrierResult(armed=False)

        try:
            arm = _read_object(claiming, "pilot-barrier arm")
            self._validate_arm(arm, schedule_id)
            challenge = str(arm["challenge"])
            challenge_sha256 = _challenge_digest(challenge)
            mode = str(arm["mode"])
            timeout_seconds = float(arm.get("timeout_seconds", 120.0))
            active_path = self.directory / ACTIVE_NAME
            release_path = self.directory / RELEASE_NAME
            completed_path = self.directory / COMPLETED_NAME

            for stale in (active_path, release_path, completed_path):
                if stale.exists():
                    raise PilotBarrierError(
                        f"pilot-barrier har allerede {stale.name}; arkivér den før en ny arm"
                    )

            started_at = _utc_now()
            active = {
                "schema": RECEIPT_SCHEMA,
                "state": "active",
                "mode": mode,
                "schedule_id": schedule_id,
                "claim_id": claim_id,
                "job_id": job_id,
                "worker_pid": os.getpid(),
                "challenge_sha256": challenge_sha256,
                "started_at": started_at,
                "timeout_seconds": timeout_seconds,
                "production_activation": False,
            }
            _atomic_json(active_path, active)
            LOGGER.warning(
                "scheduler pilot barrier active "
                "(mode=%s schedule_id=%s claim_id=%s job_id=%s pid=%d)",
                mode,
                schedule_id,
                claim_id,
                job_id,
                os.getpid(),
            )

            deadline = self.clock() + timeout_seconds
            while self.clock() < deadline:
                if release_path.is_file():
                    release = _read_object(release_path, "pilot-barrier release")
                    self._validate_release(
                        release,
                        claim_id=claim_id,
                        challenge_sha256=challenge_sha256,
                    )
                    release_path.unlink()
                    completed = {
                        **active,
                        "state": "released",
                        "released_at": _utc_now(),
                    }
                    _atomic_json(completed_path, completed)
                    active_path.unlink(missing_ok=True)
                    LOGGER.warning(
                        "scheduler pilot barrier released "
                        "(mode=%s schedule_id=%s claim_id=%s)",
                        mode,
                        schedule_id,
                        claim_id,
                    )
                    return PilotBarrierResult(
                        armed=True,
                        mode=mode,
                        released=True,
                        receipt_path=str(completed_path),
                    )
                self.sleeper(self.poll_seconds)

            completed = {
                **active,
                "state": "timed_out",
                "timed_out_at": _utc_now(),
            }
            _atomic_json(completed_path, completed)
            active_path.unlink(missing_ok=True)
            LOGGER.error(
                "scheduler pilot barrier timed out; continuing fail-visible "
                "(mode=%s schedule_id=%s claim_id=%s)",
                mode,
                schedule_id,
                claim_id,
            )
            return PilotBarrierResult(
                armed=True,
                mode=mode,
                timed_out=True,
                receipt_path=str(completed_path),
            )
        finally:
            claiming.unlink(missing_ok=True)

    @staticmethod
    def _validate_arm(arm: dict[str, Any], expected_schedule_id: str) -> None:
        if arm.get("schema") != ARM_SCHEMA:
            raise PilotBarrierError("pilot-barrier arm har forkert schema")
        if arm.get("schedule_id") != expected_schedule_id:
            raise PilotBarrierError("pilot-barrier arm skiftede schedule_id under claim")
        if arm.get("mode") not in VALID_MODES:
            raise PilotBarrierError("pilot-barrier mode er ugyldig")
        challenge = arm.get("challenge")
        if not isinstance(challenge, str) or len(challenge) < 32:
            raise PilotBarrierError("pilot-barrier challenge skal være mindst 32 tegn")
        timeout = arm.get("timeout_seconds", 120.0)
        if not isinstance(timeout, (int, float)) or not 0.05 <= float(timeout) <= 300.0:
            raise PilotBarrierError("pilot-barrier timeout skal være 0.05..300 sekunder")
        if arm.get("production_activation") is not False:
            raise PilotBarrierError("pilot-barrier arm skal bevare production_activation=false")

    @staticmethod
    def _validate_release(
        release: dict[str, Any], *, claim_id: str, challenge_sha256: str
    ) -> None:
        if release.get("schema") != RELEASE_SCHEMA:
            raise PilotBarrierError("pilot-barrier release har forkert schema")
        if release.get("action") != "continue":
            raise PilotBarrierError("pilot-barrier release mangler action=continue")
        if release.get("claim_id") != claim_id:
            raise PilotBarrierError("pilot-barrier release matcher ikke claim_id")
        challenge = release.get("challenge")
        if not isinstance(challenge, str) or _challenge_digest(challenge) != challenge_sha256:
            raise PilotBarrierError("pilot-barrier release matcher ikke challenge")
        if release.get("production_activation") is not False:
            raise PilotBarrierError("pilot-barrier release skal bevare production_activation=false")


def controller_from_env() -> PilotBarrierController | None:
    raw = os.environ.get(ENV_BARRIER_DIR, "").strip()
    if not raw:
        return None
    directory = Path(raw)
    if not directory.is_dir():
        raise PilotBarrierError(
            f"{ENV_BARRIER_DIR} peger ikke på en eksisterende mappe: {directory}"
        )
    return PilotBarrierController(directory)


def install_pilot_barrier(runner_cls: type) -> None:
    """Wrap ``_run_claim`` once; no env means no filesystem access or delay."""

    if getattr(runner_cls, "_kaliv_pilot_barrier_installed", False):
        return
    original = runner_cls._run_claim

    def guarded_run_claim(self, claim, job_id, now):
        controller = controller_from_env()
        if controller is not None:
            result = controller.hold(
                schedule_id=claim.schedule.schedule_id,
                claim_id=claim.claim_id,
                job_id=job_id,
            )
            if result.timed_out:
                LOGGER.error(
                    "scheduler pilot barrier timeout receipt=%s",
                    result.receipt_path,
                )
        return original(self, claim, job_id, now)

    runner_cls._run_claim = guarded_run_claim
    runner_cls._kaliv_pilot_barrier_installed = True
