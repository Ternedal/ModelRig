#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_a_checkpoint.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage_a_checkpoint_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = load_module()
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
CANDIDATE = {
    "version": "1.58.145",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "branch": "agent/unified-candidate-1.58.145",
    "working_tree_clean": True,
    "dirty_entries": 0,
    "identity_source": "git",
    "version_stamps_consistent": True,
    "version_check_detail": None,
}


def campaign(*, passed_names: list[str], failed_names: list[str], missing_names: list[str], candidate_errors: list[str] | None = None) -> dict:
    candidate_errors = candidate_errors or []
    evidence = {}
    for name in module.PROOFS:
        status = "pass" if name in passed_names else "fail" if name in failed_names else "missing"
        evidence[name] = {"status": status, "errors": [] if status != "fail" else ["fixture failure"]}
    complete = len(passed_names) == len(module.PROOFS) and not candidate_errors
    return {
        "schema": module.CAMPAIGN_SCHEMA,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "mode": "prepare",
        "candidate": dict(CANDIDATE),
        "evidence": evidence,
        "summary": {
            "total": len(module.PROOFS),
            "passed": passed_names,
            "failed": failed_names,
            "missing": missing_names,
            "candidate_errors": candidate_errors,
        },
        "gate": {
            "passed": not failed_names and not candidate_errors,
            "candidate_campaign_complete": complete,
            "release_validation_pending": True,
            "release_complete": False,
            "production_activation": False,
        },
    }


def write(path: Path, value: dict) -> bytes:
    raw = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


validation = ROOT / "validation"
validation.mkdir(exist_ok=True)
temp = Path(tempfile.mkdtemp(prefix="stage-a-checkpoint-test-", dir=validation))
try:
    campaign_path = temp / "campaign.json"
    voice_path = temp / "voice-fixtures.json"
    voice = {
        "schema": module.VOICE_SCHEMA,
        "build": {"version": CANDIDATE["version"], "git_sha": CANDIDATE["git_sha"]},
        "summary": {"audio_present": 20, "audio_missing": 0},
        "gate": {"mode": "validate_only", "passed": True},
    }
    write(voice_path, voice)

    partial = campaign(
        passed_names=["preflight", "agent3", "model_eval", "rag"],
        failed_names=[],
        missing_names=["voice", "scheduler_pilot"],
    )
    raw = write(campaign_path, partial)
    report, code = module.build_checkpoint(
        partial,
        source_path=campaign_path,
        source_raw=raw,
        voice_fixture_path=voice_path,
        now=NOW,
    )
    check(code == 0 and report["checkpoint"]["valid"] is True,
          "missing manual evidence still produces an honest resumable checkpoint")
    check(report["checkpoint"]["automatic_evidence_complete"] is True,
          "the four accepted automatic proofs remain visible")
    check(report["checkpoint"]["manual_evidence_pending"] == ["voice", "scheduler_pilot"],
          "voice and scheduler stay explicitly pending")
    check(report["checkpoint"]["ready_for_stage_a_verify"] is False,
          "a partial checkpoint cannot advance to Stage A verify")
    check(report["supplemental"]["voice_fixtures"]["status"] == "pass",
          "the candidate-bound 20-file voice fixture check is preserved as supplemental evidence")
    check(report["gate"]["promotion_ready"] is False and report["gate"]["production_activation"] is False,
          "a checkpoint can never claim promotion or activate production")

    broken = campaign(
        passed_names=["preflight", "agent3", "model_eval", "rag"],
        failed_names=["voice"],
        missing_names=["scheduler_pilot"],
    )
    raw = write(campaign_path, broken)
    report, code = module.build_checkpoint(
        broken,
        source_path=campaign_path,
        source_raw=raw,
        voice_fixture_path=voice_path,
        now=NOW,
    )
    check(code == 1 and report["checkpoint"]["valid"] is False,
          "a real failed proof blocks a green checkpoint")

    complete = campaign(
        passed_names=list(module.PROOFS),
        failed_names=[],
        missing_names=[],
    )
    raw = write(campaign_path, complete)
    report, code = module.build_checkpoint(
        complete,
        source_path=campaign_path,
        source_raw=raw,
        voice_fixture_path=voice_path,
        now=NOW,
    )
    check(code == 0 and report["checkpoint"]["ready_for_stage_a_verify"] is True,
          "all six candidate proofs make the separate verify step available")
    check(report["gate"]["promotion_ready"] is False,
          "even a complete candidate checkpoint is not the final promotion verdict")

    contradictory = campaign(
        passed_names=["preflight", "agent3", "model_eval", "rag"],
        failed_names=[],
        missing_names=["voice", "scheduler_pilot"],
    )
    contradictory["gate"]["production_activation"] = True
    try:
        module.build_checkpoint(
            contradictory,
            source_path=campaign_path,
            source_raw=b"{}",
            voice_fixture_path=voice_path,
            now=NOW,
        )
    except module.CheckpointError:
        rejected = True
    else:
        rejected = False
    check(rejected, "production activation in the source campaign is rejected fail-closed")

    duplicate = campaign(
        passed_names=["preflight", "agent3", "model_eval", "rag", "rag"],
        failed_names=[],
        missing_names=["voice", "scheduler_pilot"],
    )
    try:
        module.build_checkpoint(
            duplicate,
            source_path=campaign_path,
            source_raw=b"{}",
            voice_fixture_path=voice_path,
            now=NOW,
        )
    except module.CheckpointError:
        rejected = True
    else:
        rejected = False
    check(rejected, "duplicate or contradictory proof lists are rejected")
finally:
    shutil.rmtree(temp, ignore_errors=True)

source = SCRIPT.read_text(encoding="utf-8").lower()
for forbidden in (
    "git push",
    "git tag",
    "gh release",
    "merge_pull_request",
    "production_activation=true",
):
    check(forbidden not in source, f"checkpoint writer has no forbidden action: {forbidden}")

launcher = (ROOT / "SAVE_STAGE_A_RESULTS.cmd").read_text(encoding="utf-8").lower()
for forbidden in ("start_stage_a_test", "start-process", "pair/start", "schedules"):
    check(forbidden not in launcher, f"checkpoint launcher does not restart interactive systems: {forbidden}")

print(f"Stage A checkpoint contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
