#!/usr/bin/env python3
"""Fail-closed completion guard for START_PROOF_CAMPAIGN.cmd.

The Windows shell may report exit code 0 after an interrupted native/PowerShell
prompt. The launcher must therefore never infer a green physical campaign from
process exit status alone. This helper records a launch marker before execution
and, on an apparent success, requires a fresh exact-SHA summary produced after
that marker with every source-bound proof gate actually green.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / "validation" / "stage-a-runtime" / "proof-campaign-launch-marker.json"
EVIDENCE_ROOT = ROOT / "validation" / "proof-campaign"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def current_identity() -> tuple[str, str, str]:
    sha = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    if not branch:
        raise RuntimeError("Detached HEAD afvises af completion-guarden.")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    return sha, branch, version


def write_marker() -> int:
    sha, branch, version = current_identity()
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    marker = {
        "schema": "modelrig-proof-launch-marker/v1",
        "created_at_unix_ns": time.time_ns(),
        "candidate": {"sha": sha, "branch": branch, "version": version},
    }
    MARKER.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    print(f"  Completion-guard: launch marker sat for {sha[:12]}.")
    return 0


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} er ikke et JSON-object.")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify_summary() -> int:
    require(MARKER.is_file(), "Launch-marker mangler; PASS kan ikke attesteres.")
    marker = load_json(MARKER)
    marker_candidate = marker.get("candidate")
    require(isinstance(marker_candidate, dict), "Launch-marker mangler kandidatidentitet.")
    started_ns = int(marker.get("created_at_unix_ns") or 0)
    require(started_ns > 0, "Launch-marker mangler gyldigt starttidspunkt.")

    sha, branch, version = current_identity()
    require(marker_candidate.get("sha") == sha, "HEAD ændrede sig siden kampagnen startede.")
    require(marker_candidate.get("branch") == branch, "Branch ændrede sig siden kampagnen startede.")
    require(marker_candidate.get("version") == version, "VERSION ændrede sig siden kampagnen startede.")

    summaries = sorted(
        EVIDENCE_ROOT.glob("*/summary.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    ) if EVIDENCE_ROOT.is_dir() else []
    fresh = [path for path in summaries if path.stat().st_mtime_ns >= started_ns]
    require(fresh, "Ingen ny summary.json blev produceret efter denne launch; afbrydelse kan ikke være PASS.")

    summary_path = fresh[0]
    summary = load_json(summary_path)
    candidate = summary.get("candidate")
    workflow = summary.get("workflow")
    t033 = summary.get("t033")
    stage_b = summary.get("stage_b_release_lifecycle")

    require(isinstance(candidate, dict), "summary.json mangler kandidatidentitet.")
    require(candidate.get("sha") == sha, "summary.json er ikke bundet til current exact SHA.")
    require(candidate.get("branch") == branch, "summary.json er ikke bundet til current branch.")
    require(candidate.get("version") == version, "summary.json er ikke bundet til current VERSION.")
    require(summary.get("passed") is True, "summary.passed er ikke true.")
    require(summary.get("stage_a") is True, "Stage A er ikke attesteret green i summary.")
    require(summary.get("forced_recovery") is True, "T-006 forced recovery er ikke green i summary.")

    require(isinstance(workflow, dict), "Workflow-summary mangler.")
    require(workflow.get("passed") is True, "Workflow-gaten er ikke green.")
    require(int(workflow.get("rounds") or 0) == 22, "Fuld kampagne kræver præcis 22 workflow-runder.")
    require(int(workflow.get("executions") or 0) == 308, "Fuld kampagne kræver præcis 308 workflow-executioner.")

    require(summary.get("t023") is True, "T-023 er ikke green.")
    require(summary.get("t023_skipped") is not True, "T-023 blev sprunget over.")
    require(isinstance(t033, dict), "T-033-summary mangler.")
    require(t033.get("passed") is True, "T-033 er ikke green.")
    require(t033.get("pending_second_sid") is not True, "T-033 mangler stadig anden Windows-SID.")
    require(t033.get("skipped") is not True, "T-033 blev sprunget over.")

    require(summary.get("production_activation") is False, "Proof-kampagnen må ikke aktivere produktion.")
    require(isinstance(stage_b, dict) and stage_b.get("included") is False, "Stage B skal forblive separat release-bound.")

    print(f"  Completion-guard PASS: frisk exact-SHA summary verificeret: {summary_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("mark", "check"))
    args = parser.parse_args()
    try:
        return write_marker() if args.action == "mark" else verify_summary()
    except Exception as exc:
        print(f"COMPLETION-GUARD BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
