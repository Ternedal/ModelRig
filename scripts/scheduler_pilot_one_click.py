#!/usr/bin/env python3
"""One-click, resumable Windows wizard for the physical T-019 scheduler pilot.

This wrapper reuses the Stage A checkout/model/stack helpers and the canonical
scheduler-pilot reporter. A pilot-only worker entrypoint provides a one-shot
hold after claim/job binding but before the live revoke guard and ToolGate. The
hold removes manual timing luck from revoke and crash observations while normal
worker and Stage A entrypoints remain unchanged.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path
from typing import Any

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_a_one_click as stage  # noqa: E402

BRANCH = "agent/t019-physical-pilot-candidate"
VERSION = "1.58.141"
VALIDATION = ROOT / "validation"
STATE_PATH = VALIDATION / "scheduler-pilot-easy-state.json"
REPORT_PATH = VALIDATION / "scheduler-pilot-latest.json"
MANUAL_PATH = VALIDATION / "scheduler-manual-observations.json"
CONTROL_DIR = VALIDATION / "scheduler-pilot-control"
WORKER_LOG = VALIDATION / "scheduler-pilot-worker.log"
CONTROL_SCHEMA = "kaliv-scheduler-pilot-control/v1"
WORKER_URL = "http://127.0.0.1:8099"
READ_BODY = {
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


class PilotError(RuntimeError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def save_state(state: dict[str, Any]) -> None:
    write_object(STATE_PATH, state)


def report_passes(report: dict[str, Any], sha: str) -> bool:
    candidate = report.get("candidate")
    pilot = report.get("pilot")
    return (
        isinstance(candidate, dict)
        and candidate.get("git_sha") == sha
        and isinstance(pilot, dict)
        and pilot.get("passed") is True
    )


def archive_local_files(label: str) -> None:
    sources = [path for path in (REPORT_PATH, MANUAL_PATH) if path.is_file()]
    if not sources:
        return
    archive = VALIDATION / "archive" / time.strftime(f"scheduler-{label}-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    for source in sources:
        source.replace(archive / source.name)
    stage.note(f"Tidligere scheduler-beviser er bevaret i {archive}")


def clear_control_files() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    for pattern in ("command.json", "command.json.tmp", "holding.json", "holding.json.tmp", "release-*.flag"):
        for path in CONTROL_DIR.glob(pattern):
            try:
                path.unlink()
            except OSError:
                pass


def prepare_state(sha: str) -> dict[str, Any]:
    state = read_object(STATE_PATH)
    previous_sha = str(state.get("candidate_sha") or "")
    if previous_sha and previous_sha != sha:
        stale = [
            str(state.get(name) or "")
            for name in ("read_schedule_id", "write_schedule_id")
            if state.get(name)
        ]
        archive_local_files("candidate-change")
        clear_control_files()
        state = {"candidate_sha": sha, "stale_schedule_ids": stale}
        save_state(state)
    elif not previous_sha:
        state["candidate_sha"] = sha
        save_state(state)
    return state


def start_pilot_stack(planner: str, *, worker_only: bool = False) -> None:
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "start-stage-a-validation-stack.ps1"),
        "-PlannerModel",
        planner,
        "-ValidationReport",
        str(stage.AGENT3_REPORT),
        "-SchedulerPilot",
    ]
    if worker_only:
        args.append("-WorkerOnly")
    if not worker_only and not shutil.which("go"):
        stage.install_with_winget("GoLang.Go", "Go")
        if not shutil.which("go"):
            raise PilotError(
                "Go blev installeret. Luk vinduet og dobbeltklik igen, så PATH opdateres."
            )
    stage.run(args)


def schedule_payload(value: dict[str, Any]) -> dict[str, Any]:
    schedule = value.get("schedule")
    if not isinstance(schedule, dict):
        raise PilotError("Workerens schedule-svar mangler det forventede schedule-objekt.")
    return schedule


def get_schedule(schedule_id: str) -> dict[str, Any]:
    return schedule_payload(stage.request_json(f"{WORKER_URL}/schedules/{schedule_id}"))


def set_schedule_enabled(schedule_id: str, enabled: bool) -> dict[str, Any]:
    return schedule_payload(
        stage.request_json(
            f"{WORKER_URL}/schedules/{schedule_id}/enabled",
            method="POST",
            body={"enabled": enabled},
        )
    )


def pause_schedule(schedule_id: str) -> None:
    try:
        set_schedule_enabled(schedule_id, False)
    except Exception as exc:
        stage.note(f"Kunne ikke pause tidligere pilotplan {schedule_id}: {str(exc)[:200]}")


def pause_stale_schedules(state: dict[str, Any]) -> None:
    stale = [str(value) for value in state.get("stale_schedule_ids", []) if value]
    if not stale:
        return
    for schedule_id in stale:
        pause_schedule(schedule_id)
    state.pop("stale_schedule_ids", None)
    save_state(state)


def reset_failed_pilot(sha: str, state: dict[str, Any]) -> dict[str, Any]:
    report = read_object(REPORT_PATH)
    if not report or report_passes(report, sha):
        return state
    for key in ("read_schedule_id", "write_schedule_id"):
        schedule_id = str(state.get(key) or "")
        if schedule_id:
            pause_schedule(schedule_id)
    archive_local_files("failed")
    clear_control_files()
    fresh = {"candidate_sha": sha}
    save_state(fresh)
    stage.note("Det fejlede pilotforsøg er arkiveret; et nyt afgrænset forsøg oprettes.")
    return fresh


def wait_runs(schedule_id: str, minimum: int, *, timeout: float = 100.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = get_schedule(schedule_id)
        if int(latest.get("runs_used") or 0) >= minimum:
            return latest
        time.sleep(1.0)
    raise PilotError(
        f"Plan {schedule_id} nåede ikke runs_used={minimum} inden for {timeout:.0f} sekunder."
    )


def arm_hold(schedule_id: str, purpose: str) -> str:
    clear_control_files()
    nonce = secrets.token_hex(16)
    write_object(
        CONTROL_DIR / "command.json",
        {
            "schema": CONTROL_SCHEMA,
            "action": "hold_before_guard",
            "schedule_id": schedule_id,
            "purpose": purpose,
            "nonce": nonce,
            "created_at": time.time(),
            "expires_at": time.time() + 180.0,
            "timeout_seconds": 180.0,
        },
    )
    return nonce


def wait_hold(schedule_id: str, nonce: str, *, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    marker_path = CONTROL_DIR / "holding.json"
    while time.monotonic() < deadline:
        marker = read_object(marker_path)
        if (
            marker.get("schema") == CONTROL_SCHEMA
            and marker.get("schedule_id") == schedule_id
            and marker.get("nonce") == nonce
            and marker.get("phase") == "before_live_guard"
        ):
            return marker
        time.sleep(0.25)
    raise PilotError(
        "Den deterministiske hold blev ikke ramt. Planen blev ikke pauset eller crashet."
    )


def release_hold(nonce: str) -> None:
    path = CONTROL_DIR / f"release-{nonce}.flag"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("release\n", encoding="ascii")


def wait_worker_down(*, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            stage.request_json(f"{WORKER_URL}/healthz")
        except Exception:
            return
        time.sleep(0.5)
    raise PilotError("Worker-vinduet blev ikke lukket inden for to minutter.")


def recovery_line_after(offset: int, *, timeout: float = 45.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            text = WORKER_LOG.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for line in text[offset:].splitlines():
            if "scheduler: recovered " in line:
                return line[line.index("scheduler: recovered ") :].strip()
        time.sleep(0.5)
    raise PilotError("Den nye worker skrev ingen scheduler: recovered-linje til pilotloggen.")


def require_yes(message: str) -> None:
    if stage.prompt(message).strip().upper() != "JA":
        raise PilotError(f"Ikke bekræftet: {message}")


def create_or_resume_read(state: dict[str, Any]) -> str:
    read_id = str(state.get("read_schedule_id") or "")
    if read_id:
        try:
            get_schedule(read_id)
            return read_id
        except Exception:
            read_id = ""
    stage.request_json(f"{WORKER_URL}/schedules/preview", method="POST", body=READ_BODY)
    created = schedule_payload(
        stage.request_json(f"{WORKER_URL}/schedules", method="POST", body=READ_BODY)
    )
    read_id = str(created.get("schedule_id") or "")
    if not read_id:
        raise PilotError("Read-planen returnerede intet schedule_id.")
    state["read_schedule_id"] = read_id
    save_state(state)
    return read_id


def get_write_id(state: dict[str, Any]) -> str:
    existing = str(state.get("write_schedule_id") or "")
    if existing:
        try:
            schedule = get_schedule(existing)
            if (
                schedule.get("tool") == WRITE_MANIFEST["tool"]
                and schedule.get("args") == WRITE_MANIFEST["args"]
                and schedule.get("cadence") == WRITE_MANIFEST["cadence"]
                and schedule.get("max_runs") == WRITE_MANIFEST["max_runs"]
            ):
                return existing
        except Exception:
            pass
    print("\n  Opret PRÆCIS denne plan i Android-appens schedule-flow og godkend den:")
    print('    tool=note_append, args={"text":"pilot"}, cadence=every:60, max_runs=2, ttl_days=1')
    write_id = stage.prompt("  Indsæt write schedule-id").strip()
    if not write_id:
        raise PilotError("Write schedule-id mangler.")
    schedule = get_schedule(write_id)
    if not (
        schedule.get("tool") == WRITE_MANIFEST["tool"]
        and schedule.get("args") == WRITE_MANIFEST["args"]
        and schedule.get("cadence") == WRITE_MANIFEST["cadence"]
        and schedule.get("max_runs") == WRITE_MANIFEST["max_runs"]
    ):
        raise PilotError("Write-planen matcher ikke det eksakte pilotmanifest.")
    state["write_schedule_id"] = write_id
    save_state(state)
    return write_id


def run_deterministic_pilot(planner: str, state: dict[str, Any]) -> None:
    stage.heading("FYSISK PILOT  Read + write")
    read_id = create_or_resume_read(state)
    write_id = get_write_id(state)
    stage.ok(f"Read schedule-id: {read_id}")
    stage.ok(f"Write schedule-id: {write_id}")

    stage.note("Venter på én ægte read-kørsel og én godkendt write-kørsel...")
    wait_runs(read_id, 1)
    wait_runs(write_id, 1)
    require_yes("Viser Android-listen begge planer? Skriv JA")
    require_yes("Så du mindst én plan som in-flight/running? Skriv JA")

    stage.heading("AUTOMATISK REVOCATION")
    set_schedule_enabled(read_id, True)
    revoke_nonce = arm_hold(read_id, "revocation")
    marker = wait_hold(read_id, revoke_nonce)
    stage.ok(f"Occurrence {marker.get('claim_id')} er holdt sikkert før ToolGate.")
    set_schedule_enabled(read_id, False)
    release_hold(revoke_nonce)
    require_yes("Viser Android jobbet som cancelled/terminal med pausegrund? Skriv JA")

    stage.heading("STYRET CRASH-RECOVERY")
    set_schedule_enabled(read_id, True)
    crash_nonce = arm_hold(read_id, "crash_recovery")
    marker = wait_hold(read_id, crash_nonce)
    stage.ok(f"Occurrence {marker.get('claim_id')} er holdt sikkert før ToolGate.")
    print("  Luk NU det synlige worker-vindue. Backend-vinduet skal blive åbent.")
    input("  Tryk Enter, når worker-vinduet er lukket: ")
    wait_worker_down()
    log_offset = WORKER_LOG.stat().st_size if WORKER_LOG.is_file() else 0
    start_pilot_stack(planner, worker_only=True)
    recovery = recovery_line_after(log_offset)
    stage.ok(recovery)

    manual = {
        "revocation_confirmed": True,
        "recovery_line": recovery,
        "operator": "Anders",
        "android_schedule_list_confirmed": True,
        "android_in_flight_confirmed": True,
        "android_terminal_confirmed": True,
    }
    write_object(MANUAL_PATH, manual)
    stage.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "scheduler_pilot_report.py"),
            "--worker-url",
            WORKER_URL,
            "--read-schedule-id",
            read_id,
            "--write-schedule-id",
            write_id,
            "--manual-observations",
            str(MANUAL_PATH),
            "--report",
            str(REPORT_PATH),
        ]
    )


def main() -> int:
    os.chdir(ROOT)
    stage.heading("Kaliv T-019 — lettest mulige scheduler-pilot")
    print("  Dobbeltklik START_SCHEDULER_PILOT.cmd.")
    print("  Wizard'en kan genoptages og kan ikke merge, release eller aktivere produktion.")

    stage.BRANCH = BRANCH
    stage.VERSION = VERSION
    sha = stage.ensure_candidate()
    state = prepare_state(sha)

    existing = read_object(REPORT_PATH)
    if report_passes(existing, sha):
        stage.ok(f"Scheduler-piloten er allerede bestået på {sha}")
        print(f"  Rapport: {REPORT_PATH}")
        return 0

    planner = stage.ensure_models()
    start_pilot_stack(planner)
    pause_stale_schedules(state)
    state = reset_failed_pilot(sha, state)
    run_deterministic_pilot(planner, state)

    report = read_object(REPORT_PATH)
    if not report_passes(report, sha):
        raise PilotError("Rapporten blev ikke bestået eller matcher ikke current exact head.")

    clear_control_files()
    stage.heading("SCHEDULER-PILOT BESTÅET")
    stage.ok(f"Read, write, Android, revoke og recovery er bundet til {sha}")
    print(f"  Rapport: {REPORT_PATH}")
    print("  Ingen merge, release eller produktionsaktivering er udført.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:800]}", file=sys.stderr)
        print("  Ret problemet og dobbeltklik igen; lokale beviser er bevaret.", file=sys.stderr)
        raise SystemExit(1)
