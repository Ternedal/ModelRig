#!/usr/bin/env python3
"""One-click, resumable Windows wizard for the physical T-019 scheduler pilot.

This wrapper deliberately reuses the existing Stage A candidate checks, stack
launcher and canonical scheduler-pilot reporter. It runs only the scheduler
pilot: no voice, RAG, browser, merge, push, tag, release or activation action.
"""
from __future__ import annotations

import json
import os
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


class PilotError(RuntimeError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    VALIDATION.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def pause_schedule(schedule_id: str) -> None:
    try:
        stage.request_json(
            f"http://127.0.0.1:8099/schedules/{schedule_id}/enabled",
            method="POST",
            body={"enabled": False},
        )
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
    fresh = {"candidate_sha": sha}
    save_state(fresh)
    stage.note("Det fejlede pilotforsøg er arkiveret; et nyt afgrænset forsøg oprettes.")
    return fresh


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
    stage.start_stack = start_pilot_stack
    start_pilot_stack(planner)
    pause_stale_schedules(state)
    state = reset_failed_pilot(sha, state)

    stage.run_scheduler(planner, state)
    report = read_object(REPORT_PATH)
    if not report_passes(report, sha):
        raise PilotError("Rapporten blev ikke bestået eller matcher ikke current exact head.")

    stage.heading("SCHEDULER-PILOT BESTÅET")
    stage.ok(f"Read, write, revoke og recovery er bundet til {sha}")
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
