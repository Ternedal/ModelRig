#!/usr/bin/env python3
"""Final machine-only seal for the automatic #846 live renderer proof.

This gate composes the existing independent machine-evidence validator with the
physical product exercise receipt. It rehashes the machine run and Unity quality
receipts, verifies the create-only exercise seal, then writes one final receipt
for downstream activation. No human visual attestation is consumed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from scripts.bodyrig_unity_live_automatic_gate import validate_automatic_evidence
from scripts.bodyrig_unity_live_physical_gate import (
    ROOT,
    LivePhysicalGateError,
    _load_json,
    _parse_time,
    _require_body_id,
    _require_git_sha,
    _require_sha256,
)

EXERCISE_SCHEMA = "bodyrig.live_automatic_exercise/v0.1"
FINAL_SCHEMA = "bodyrig.unity_live_automatic_final/v0.1"
EXPECTED_STATES = ["idle", "listening", "speaking", "interrupted", "idle"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise LivePhysicalGateError(f"final receipt destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(value), sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temporary_raw = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise LivePhysicalGateError("final receipt destination appeared before commit")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def validate_final_evidence(
    *, evidence_dir: Path, expected_sha: str, repo_root: Path = ROOT,
    require_git_state: bool = True,
) -> dict[str, Any]:
    base = validate_automatic_evidence(
        evidence_dir=evidence_dir,
        expected_sha=expected_sha,
        repo_root=repo_root,
        require_git_state=require_git_state,
    )
    expected_sha = _require_git_sha(expected_sha, label="expected_sha")
    evidence_dir = evidence_dir.expanduser().resolve()
    run_path = evidence_dir / "live-run-receipt.json"
    quality_path = evidence_dir / "live-quality-receipt.json"
    exercise_path = evidence_dir / "live-automatic-exercise-receipt.json"
    run, _ = _load_json(run_path)
    quality, _ = _load_json(quality_path)
    exercise, _ = _load_json(exercise_path)

    if exercise.get("schema") != EXERCISE_SCHEMA:
        raise LivePhysicalGateError("automatic exercise receipt schema mismatch")
    if exercise.get("production_activation") is not False:
        raise LivePhysicalGateError("automatic exercise receipt activated production")
    if _require_git_sha(exercise.get("candidate_git_sha"), label="exercise.candidate_git_sha") != expected_sha:
        raise LivePhysicalGateError("automatic exercise candidate SHA mismatch")
    body_id = _require_body_id(exercise.get("body_id"), label="exercise.body_id")
    package_sha = _require_sha256(exercise.get("package_sha256"), label="exercise.package_sha256")
    if body_id != base["body_id"] or package_sha != base["package_sha256"]:
        raise LivePhysicalGateError("automatic exercise profile identity mismatch")
    if exercise.get("rig_url") != base["rig_url"]:
        raise LivePhysicalGateError("automatic exercise rig URL mismatch")
    if exercise.get("token_source") != "environment":
        raise LivePhysicalGateError("automatic exercise token source must be environment")
    if exercise.get("states_driven") != EXPECTED_STATES:
        raise LivePhysicalGateError("automatic exercise state sequence mismatch")
    for field in ("voice_chunk_observed", "playback_reanchored", "interrupt_sent", "idle_restored"):
        if exercise.get(field) is not True:
            raise LivePhysicalGateError(f"automatic exercise did not prove {field}")

    bindings = exercise.get("bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != {"live_run_sha256", "live_quality_sha256"}:
        raise LivePhysicalGateError("automatic exercise receipt bindings are incomplete or unexpected")
    run_sha = _sha(run_path)
    quality_sha = _sha(quality_path)
    if bindings.get("live_run_sha256") != run_sha:
        raise LivePhysicalGateError("automatic exercise no longer binds live-run receipt")
    if bindings.get("live_quality_sha256") != quality_sha:
        raise LivePhysicalGateError("automatic exercise no longer binds Unity quality receipt")

    if run.get("candidate_git_sha") != expected_sha or quality.get("candidate_git_sha") != expected_sha:
        raise LivePhysicalGateError("sealed machine evidence candidate mismatch")
    exercise_time = _parse_time(exercise.get("created_at"), label="automatic exercise")
    quality_time = _parse_time(quality.get("created_at"), label="live quality")
    if exercise_time < quality_time:
        raise LivePhysicalGateError("automatic exercise seal predates Unity quality receipt")

    return {
        "schema": FINAL_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "production_activation": False,
        "pr_number": 846,
        "candidate_git_sha": expected_sha,
        "body_id": body_id,
        "package_sha256": package_sha,
        "rig_url": base["rig_url"],
        "machine_live_proof": True,
        "machine_quality": True,
        "product_exercise": True,
        "bindings": {
            "live_run_sha256": run_sha,
            "live_quality_sha256": quality_sha,
            "automatic_exercise_sha256": _sha(exercise_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (args.evidence_dir / "live-automatic-final-receipt.json")
    try:
        result = validate_final_evidence(
            evidence_dir=args.evidence_dir,
            expected_sha=args.expected_sha,
            repo_root=ROOT,
            require_git_state=True,
        )
        _write_create_only(output.expanduser().resolve(), result)
    except LivePhysicalGateError as exc:
        print(f"BODYRIG UNITY LIVE AUTOMATIC FINAL GATE: FAIL — {exc}")
        return 1
    print(
        "BODYRIG UNITY LIVE AUTOMATIC FINAL GATE: PASS — "
        f"#846 @ {result['candidate_git_sha']} · {result['body_id']}"
    )
    print(f"  receipt: {output}")
    print("production_activation=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
