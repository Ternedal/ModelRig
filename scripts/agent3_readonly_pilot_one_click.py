#!/usr/bin/env python3
"""One-click Windows operator for the physical T-020 Agent 3 read-only pilot.

The wrapper reuses the existing Stage A checkout, token and exact-head stack
helpers. It never changes normal chat routing, confirms a write, merges, pushes,
tags, releases or activates production. The only unavoidable operator input is
the paired device token, entered hidden and kept only in this process.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_a_one_click as stage  # noqa: E402

BRANCH = "agent/unified-candidate-1.58.143"
VERSION = "1.58.143"
BASE_URL = "http://127.0.0.1:8080"
VALIDATION = ROOT / "validation"
REPORT_PATH = VALIDATION / "agent3-readonly-pilot-latest.json"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
SCHEMA = "kaliv-agent3-readonly-pilot/v1"


class PilotOperatorError(RuntimeError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def report_passes(report: dict[str, Any], sha: str) -> bool:
    candidate = report.get("candidate")
    summary = report.get("summary")
    stop = report.get("stop_fallback")
    target = report.get("target")
    return (
        report.get("schema") == SCHEMA
        and report.get("success") is True
        and isinstance(candidate, dict)
        and candidate.get("git_sha") == sha
        and candidate.get("version") == VERSION
        and isinstance(summary, dict)
        and summary.get("tasks") == 20
        and summary.get("successes") == 20
        and summary.get("failures") == 0
        and summary.get("error_types") == {}
        and isinstance(stop, dict)
        and stop.get("success") is True
        and stop.get("fallback_path") == "/api/v1/chat"
        and isinstance(target, dict)
        and target.get("production_activation") is False
    )


def archive_existing(label: str) -> None:
    if not REPORT_PATH.is_file():
        return
    archive = VALIDATION / "archive" / time.strftime(f"agent3-readonly-{label}-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.replace(archive / REPORT_PATH.name)
    stage.note(f"Tidligere pilotrapport er bevaret i {archive}")


def ensure_planner_model() -> str:
    """Select one local chat model; T-020 is fixed to rag=false."""
    stage.heading("Ollama og planner-model")
    ollama = shutil.which("ollama")
    if not ollama:
        raise PilotOperatorError("Ollama blev ikke fundet på PATH.")

    try:
        stage.request_json("http://127.0.0.1:11434/api/version")
    except Exception:
        stage.note("Starter Ollama...")
        subprocess.Popen(
            [ollama, "serve"],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        for _ in range(30):
            time.sleep(1)
            try:
                stage.request_json("http://127.0.0.1:11434/api/version")
                break
            except Exception:
                continue
        else:
            raise PilotOperatorError("Ollama svarer ikke på http://127.0.0.1:11434.")

    models = stage.ollama_models()
    configured = os.environ.get("KALIV_AGENT3_PLANNER_MODEL", "").strip()
    planner = configured if configured in models else ""
    if not planner:
        for pattern in ("qwen3:", "gemma3:"):
            planner = next((name for name in models if name.startswith(pattern)), "")
            if planner:
                break
    if not planner:
        planner = next((name for name in models if "embed" not in name.lower()), "")
    if not planner:
        planner = "qwen3:8b"
        stage.note("Ingen lokal chatmodel fundet; henter qwen3:8b automatisk...")
        stage.run([ollama, "pull", planner])

    os.environ["KALIV_AGENT3_PLANNER_MODEL"] = planner
    os.environ["KALIV_AGENT3_VALIDATION_REPORT"] = str(RIG_REPORT)
    stage.ok(f"Planner, answer og fallback: {planner}")
    stage.note("T-020 bruger rag=false; ingen embeddingmodel kræves eller hentes.")
    return planner


def run_rig_validation(planner: str) -> None:
    stage.heading("Frisk Agent 3-rig-validation")
    stage.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "run-agent3-rig-validation.ps1"),
            "-BaseUrl",
            BASE_URL,
            "-PlannerModel",
            planner,
        ]
    )
    # The PowerShell runner is the authoritative fail-closed gate: it verifies
    # worker visibility, exact report SHA, developer-preview eligibility and
    # production_activation=false through the authenticated status endpoint.
    if not read_object(RIG_REPORT):
        raise PilotOperatorError("Rig-validationen bestod, men rapportfilen mangler eller er ugyldig.")
    stage.ok("Rig-validation er frisk, exact-report-bound og eligible for developer preview.")


def run_pilot(planner: str) -> int:
    stage.heading("20 read-only tasks + stop/fallback")
    return stage.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "agent3_readonly_pilot.py"),
            "--base-url",
            BASE_URL,
            "--planner-model",
            planner,
            "--answer-model",
            planner,
            "--fallback-model",
            planner,
            "--report",
            str(REPORT_PATH),
        ],
        check=False,
    ).returncode


def main() -> int:
    os.chdir(ROOT)
    stage.heading("Kaliv T-020 — one-click Agent 3 read-only pilot")
    print("  Dobbeltklik START_AGENT3_READONLY_PILOT.cmd.")
    print("  De 20 tasks og stop/fallback kører automatisk uden task-for-task input.")
    print("  Wizard'en kan ikke merge, pushe, tagge, release eller aktivere produktion.")

    stage.BRANCH = BRANCH
    stage.VERSION = VERSION
    sha = stage.ensure_candidate()

    existing = read_object(REPORT_PATH)
    if report_passes(existing, sha):
        stage.ok(f"Piloten er allerede bestået 20/20 på exact SHA {sha}")
        print(f"  Rapport: {REPORT_PATH}")
        return 0
    if existing:
        candidate = existing.get("candidate")
        prior_sha = candidate.get("git_sha") if isinstance(candidate, dict) else None
        archive_existing("stale" if prior_sha != sha else "failed")

    planner = ensure_planner_model()
    stage.ensure_device_token()

    stage.heading("Start exact-head backend og worker")
    stage.note("Luk gamle backend/worker-vinduer, når stackstarteren beder om det.")
    stage.start_stack(planner)
    run_rig_validation(planner)

    exit_code = run_pilot(planner)
    report = read_object(REPORT_PATH)
    if exit_code != 0 or not report_passes(report, sha):
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        successes = summary.get("successes", "?")
        tasks = summary.get("tasks", "?")
        raise PilotOperatorError(
            f"Piloten bestod ikke: {successes}/{tasks}. Rapporten er bevaret i {REPORT_PATH}."
        )

    stage.heading("AGENT 3 READ-ONLY PILOT BESTÅET")
    stage.ok(f"20/20 tasks og stop/fallback er bundet til exact SHA {sha}")
    stage.ok("Normal chat-routing og production_activation forblev uændret.")
    print(f"  Rapport: {REPORT_PATH}")
    print("  Luk de synlige backend/worker-vinduer efter review.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:800]}", file=sys.stderr)
        print("  Ret problemet og dobbeltklik igen; rapporten er bevaret eller arkiveret.", file=sys.stderr)
        raise SystemExit(1)
