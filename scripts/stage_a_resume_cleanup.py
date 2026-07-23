#!/usr/bin/env python3
"""Archive failed Stage A rolling evidence before a one-click resume.

This helper is intentionally narrow. It acts only when the local wizard state is
bound to the current candidate SHA and the existing candidate-campaign report
names concrete failed proof slots. It preserves every failed file under a dated
validation/archive directory and never touches passing or missing evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
STATE = VALIDATION / "stage-a-easy-state.json"
CAMPAIGN = VALIDATION / "physical-validation-candidate-campaign-latest.json"
PATHS = {
    "preflight": VALIDATION / "rig-preflight-latest.json",
    "agent3": VALIDATION / "agent3-rig-validation-latest.json",
    "model_eval": VALIDATION / "agent3-model-eval-latest.json",
    "voice": VALIDATION / "voice-baseline-latest.json",
    "rag": VALIDATION / "rag-benchmark-latest.json",
    "scheduler_pilot": VALIDATION / "scheduler-pilot-latest.json",
}


def current_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    if not STATE.is_file() or not CAMPAIGN.is_file():
        return 0
    state = read_object(STATE)
    if not state or state.get("candidate_sha") != current_sha():
        return 0
    campaign = read_object(CAMPAIGN)
    summary = campaign.get("summary") if isinstance(campaign.get("summary"), dict) else {}
    failed = [name for name in summary.get("failed", []) if name in PATHS]
    if not failed:
        return 0

    archive = VALIDATION / "archive" / time.strftime("stage-a-failed-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for name in failed:
        source = PATHS[name]
        if source.is_file():
            source.replace(archive / source.name)
            moved.append(name)
    CAMPAIGN.replace(archive / CAMPAIGN.name)
    print("  Resume: fejlede rolling reports blev bevaret i", archive)
    if moved:
        print("  Resume: kører disse trin igen:", ", ".join(moved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
