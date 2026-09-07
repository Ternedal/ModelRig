#!/usr/bin/env python3
"""Machine-only fail-closed final gate for BodyRig Unity live evidence (#846)."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping
import sys

from scripts.bodyrig_unity_live_physical_gate import (
    ROOT,
    CANDIDATE_BRANCH,
    LivePhysicalGateError,
    _check_bound_file,
    _check_build_artifact,
    _git,
    _load_json,
    _parse_time,
    _require_body_id,
    _require_git_sha,
    _require_sha256,
)

RUN_SCHEMA = "bodyrig.unity_live_run/v0.1"
PREFLIGHT_SCHEMA = "bodyrig.live_stream_probe/v0.1"
UNITY_LIVE_SCHEMA = "bodyrig.unity_live_stream/v0.1"
BUILD_SCHEMA = "bodyrig.unity_physical_build/v0.2"
RUNTIME_SCHEMA = "bodyrig.unity_runtime_load/v0.1"
QUALITY_SCHEMA = "bodyrig.unity_live_quality/v0.1"

REQUIRED_STATES = {"idle", "listening", "speaking", "interrupted"}
EXPECTED_THRESHOLDS = {
    "min_applied_frames": 80,
    "min_duration_ms": 5000,
    "min_speaking_frames": 2,
    "min_interrupted_frames": 2,
    "min_speaking_mouth_activity": 0.10,
    "max_interrupted_mouth_activity": 0.01,
    "min_blink_peak": 0.50,
    "min_breath_range": 0.05,
}
EXPECTED_CHECKS = {
    "required_states_seen",
    "enough_applied_frames",
    "enough_duration",
    "live_speech_mouth_active",
    "interruption_mouth_neutral",
    "interruption_gesture_neutral",
    "blink_active",
    "breath_active",
}


def _number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LivePhysicalGateError(f"{label} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise LivePhysicalGateError(f"{label} must be finite")
    return result


def _integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LivePhysicalGateError(f"{label} must be an integer")
    return value


def _quality_semantics(quality: Mapping[str, Any]) -> dict[str, bool]:
    thresholds = quality.get("thresholds")
    if not isinstance(thresholds, Mapping) or set(thresholds) != set(EXPECTED_THRESHOLDS):
        raise LivePhysicalGateError("live quality threshold contract is incomplete or unexpected")
    for key, expected in EXPECTED_THRESHOLDS.items():
        actual = thresholds.get(key)
        if isinstance(expected, int):
            if _integer(actual, label=f"quality.thresholds.{key}") != expected:
                raise LivePhysicalGateError(f"live quality threshold drifted: {key}")
        elif abs(_number(actual, label=f"quality.thresholds.{key}") - float(expected)) > 1e-6:
            raise LivePhysicalGateError(f"live quality threshold drifted: {key}")

    required = quality.get("required_states")
    seen = quality.get("states_seen")
    if not isinstance(required, list) or set(required) != REQUIRED_STATES:
        raise LivePhysicalGateError("live quality required state set drifted")
    if not isinstance(seen, list) or any(not isinstance(item, str) for item in seen):
        raise LivePhysicalGateError("live quality states_seen is invalid")

    applied = _integer(quality.get("applied_frames"), label="quality.applied_frames")
    duration = _integer(quality.get("duration_ms"), label="quality.duration_ms")
    first_ts = _integer(quality.get("first_timestamp_ms"), label="quality.first_timestamp_ms")
    last_ts = _integer(quality.get("last_timestamp_ms"), label="quality.last_timestamp_ms")
    speaking = _integer(quality.get("speaking_frames"), label="quality.speaking_frames")
    interrupted = _integer(quality.get("interrupted_frames"), label="quality.interrupted_frames")
    interrupted_gestures = _integer(
        quality.get("interrupted_nonempty_gesture_frames"),
        label="quality.interrupted_nonempty_gesture_frames",
    )
    if first_ts < 0 or last_ts < first_ts or duration != last_ts - first_ts:
        raise LivePhysicalGateError("live quality timestamp/duration binding is invalid")

    speaking_activity = max(
        _number(quality.get("max_speaking_mouth_open"), label="quality.max_speaking_mouth_open"),
        _number(quality.get("max_speaking_viseme_weight"), label="quality.max_speaking_viseme_weight"),
    )
    interrupted_activity = max(
        _number(quality.get("max_interrupted_mouth_open"), label="quality.max_interrupted_mouth_open"),
        _number(quality.get("max_interrupted_viseme_weight"), label="quality.max_interrupted_viseme_weight"),
    )
    blink_min = _number(quality.get("blink_min"), label="quality.blink_min")
    blink_max = _number(quality.get("blink_max"), label="quality.blink_max")
    breath_min = _number(quality.get("breath_min"), label="quality.breath_min")
    breath_max = _number(quality.get("breath_max"), label="quality.breath_max")
    for label, value in (
        ("blink_min", blink_min), ("blink_max", blink_max),
        ("breath_min", breath_min), ("breath_max", breath_max),
    ):
        if value < 0.0 or value > 1.0:
            raise LivePhysicalGateError(f"quality.{label} is outside canonical unit range")
    if blink_max < blink_min or breath_max < breath_min:
        raise LivePhysicalGateError("live quality min/max ordering is invalid")

    recomputed = {
        "required_states_seen": REQUIRED_STATES.issubset(set(seen)),
        "enough_applied_frames": applied >= EXPECTED_THRESHOLDS["min_applied_frames"],
        "enough_duration": duration >= EXPECTED_THRESHOLDS["min_duration_ms"],
        "live_speech_mouth_active": (
            speaking >= EXPECTED_THRESHOLDS["min_speaking_frames"]
            and speaking_activity >= EXPECTED_THRESHOLDS["min_speaking_mouth_activity"]
        ),
        "interruption_mouth_neutral": (
            interrupted >= EXPECTED_THRESHOLDS["min_interrupted_frames"]
            and interrupted_activity <= EXPECTED_THRESHOLDS["max_interrupted_mouth_activity"]
        ),
        "interruption_gesture_neutral": (
            interrupted >= EXPECTED_THRESHOLDS["min_interrupted_frames"]
            and interrupted_gestures == 0
        ),
        "blink_active": blink_max >= EXPECTED_THRESHOLDS["min_blink_peak"],
        "breath_active": (breath_max - breath_min) >= EXPECTED_THRESHOLDS["min_breath_range"],
    }
    reported = quality.get("checks")
    if not isinstance(reported, Mapping) or set(reported) != EXPECTED_CHECKS:
        raise LivePhysicalGateError("live quality check set is incomplete or unexpected")
    for key, expected in recomputed.items():
        if reported.get(key) is not expected:
            raise LivePhysicalGateError(f"live quality reported check disagrees with raw metrics: {key}")
    if quality.get("machine_quality_pass") is not all(recomputed.values()):
        raise LivePhysicalGateError("live quality PASS flag disagrees with independently recomputed metrics")
    if not all(recomputed.values()):
        failed = ", ".join(sorted(key for key, value in recomputed.items() if not value))
        raise LivePhysicalGateError(f"live machine quality failed: {failed}")
    return recomputed


def validate_automatic_evidence(
    *,
    evidence_dir: Path,
    expected_sha: str,
    repo_root: Path = ROOT,
    require_git_state: bool = True,
) -> dict[str, Any]:
    expected_sha = _require_git_sha(expected_sha, label="expected_sha")
    evidence_dir = evidence_dir.expanduser().resolve()
    if not evidence_dir.is_dir() or evidence_dir.is_symlink():
        raise LivePhysicalGateError("evidence directory is missing or irregular")

    if require_git_state:
        if _git("rev-parse", "HEAD", root=repo_root) != expected_sha:
            raise LivePhysicalGateError("current HEAD differs from expected live candidate")
        if _git("status", "--porcelain=v1", "--untracked-files=all", root=repo_root):
            raise LivePhysicalGateError("repository is not fully clean")

    paths = {
        "run": evidence_dir / "live-run-receipt.json",
        "preflight": evidence_dir / "live-preflight-receipt.json",
        "unity_live": evidence_dir / "unity-live-receipt.json",
        "quality": evidence_dir / "live-quality-receipt.json",
        "build": evidence_dir / "renderer" / "build-receipt.json",
        "runtime": evidence_dir / "renderer" / "runtime-receipt.json",
    }
    loaded = {name: _load_json(path) for name, path in paths.items()}
    values = {name: item[0] for name, item in loaded.items()}
    digests = {name: item[1] for name, item in loaded.items()}
    run = values["run"]
    preflight = values["preflight"]
    unity_live = values["unity_live"]
    quality = values["quality"]
    build = values["build"]
    runtime = values["runtime"]

    schemas = {
        "run": RUN_SCHEMA,
        "preflight": PREFLIGHT_SCHEMA,
        "unity_live": UNITY_LIVE_SCHEMA,
        "quality": QUALITY_SCHEMA,
        "build": BUILD_SCHEMA,
        "runtime": RUNTIME_SCHEMA,
    }
    for name, schema in schemas.items():
        if values[name].get("schema") != schema:
            raise LivePhysicalGateError(f"{name} receipt schema mismatch")
        if values[name].get("production_activation") is not False:
            raise LivePhysicalGateError(f"{name} receipt activated production")

    if run.get("pr_number") != 846 or run.get("visual_acceptance") is not False:
        raise LivePhysicalGateError("machine run must be non-visual evidence bound to PR #846")

    sha_values = {
        "run": run.get("candidate_git_sha"),
        "preflight": preflight.get("candidate_git_sha"),
        "unity_live": unity_live.get("candidate_git_sha"),
        "quality": quality.get("candidate_git_sha"),
        "build": (build.get("candidate") or {}).get("git_sha") if isinstance(build.get("candidate"), Mapping) else None,
        "runtime": runtime.get("candidate_git_sha"),
    }
    for name, value in sha_values.items():
        if _require_git_sha(value, label=f"{name}.candidate_git_sha") != expected_sha:
            raise LivePhysicalGateError(f"{name} candidate SHA mismatch")

    authority = run.get("authority")
    if not isinstance(authority, Mapping):
        raise LivePhysicalGateError("machine live run authority is missing")
    if authority.get("remote_branch") != CANDIDATE_BRANCH:
        raise LivePhysicalGateError("machine live run remote branch mismatch")
    recorded_remote = _require_git_sha(authority.get("remote_pr_head_sha"), label="run.authority.remote_pr_head_sha")
    recorded_main = _require_git_sha(authority.get("origin_main_sha"), label="run.authority.origin_main_sha")
    if recorded_remote != expected_sha or authority.get("remote_pr_head_verified") is not True:
        raise LivePhysicalGateError("machine live run did not bind current remote #846 head")
    if authority.get("origin_main_stable_during_run") is not True or authority.get("clean_checkout") is not True:
        raise LivePhysicalGateError("machine live run did not prove stable main + clean checkout")
    if require_git_state:
        _git("fetch", "--quiet", "origin", "main", CANDIDATE_BRANCH, root=repo_root)
        if _git("rev-parse", f"origin/{CANDIDATE_BRANCH}", root=repo_root) != expected_sha:
            raise LivePhysicalGateError("remote #846 head moved after machine evidence was collected")
        if _git("rev-parse", "origin/main", root=repo_root) != recorded_main:
            raise LivePhysicalGateError("origin/main moved after machine evidence was collected")
        if _git("rev-list", "--count", f"{expected_sha}..origin/main", root=repo_root) != "0":
            raise LivePhysicalGateError("#846 candidate is behind current origin/main")

    profile = run.get("profile")
    if not isinstance(profile, Mapping):
        raise LivePhysicalGateError("run profile metadata is missing")
    body_id = _require_body_id(profile.get("body_id"), label="run.profile.body_id")
    package_sha = _require_sha256(profile.get("package_sha256"), label="run.profile.package_sha256")
    body_values = {
        "preflight": preflight.get("active_body_id"),
        "unity_live": unity_live.get("body_id"),
        "quality": quality.get("body_id"),
        "build": (build.get("profile") or {}).get("body_id") if isinstance(build.get("profile"), Mapping) else None,
        "runtime": runtime.get("body_id"),
    }
    package_values = {
        "preflight": preflight.get("active_package_sha256"),
        "unity_live": unity_live.get("package_sha256"),
        "quality": quality.get("package_sha256"),
        "build": (build.get("profile") or {}).get("package_sha256") if isinstance(build.get("profile"), Mapping) else None,
        "runtime": runtime.get("package_sha256"),
    }
    for name, value in body_values.items():
        if value != body_id:
            raise LivePhysicalGateError(f"{name} body identity mismatch")
    for name, value in package_values.items():
        if value != package_sha:
            raise LivePhysicalGateError(f"{name} package identity mismatch")

    rig_url = run.get("rig_url")
    if not isinstance(rig_url, str) or not rig_url or "@" in rig_url:
        raise LivePhysicalGateError("run rig URL is missing or contains credentials")
    if any(value != rig_url for value in (preflight.get("base_url"), unity_live.get("source_url"), quality.get("source_url"))):
        raise LivePhysicalGateError("rig/source URL differs across machine evidence")
    if preflight.get("token_source") != "environment" or preflight.get("canonical_frame_validation") is not True:
        raise LivePhysicalGateError("preflight did not use env token + canonical frame validation")
    frame_identity = preflight.get("frame_identity")
    if not isinstance(frame_identity, Mapping) or frame_identity.get("body_id") != body_id:
        raise LivePhysicalGateError("preflight frame identity is missing or mismatched")
    frame_count = _integer(preflight.get("frame_count"), label="preflight.frame_count")
    if frame_count < 2:
        raise LivePhysicalGateError("preflight frame count is insufficient")

    if unity_live.get("bearer_auth_used") is not True or unity_live.get("renderer_bound") is not True or unity_live.get("frame_applied") is not True:
        raise LivePhysicalGateError("Unity live receipt does not prove authenticated frame application")

    build_state = build.get("build")
    if not isinstance(build_state, Mapping) or build_state.get("success") is not True or build_state.get("exit_code") != 0:
        raise LivePhysicalGateError("renderer build did not succeed")
    if build_state.get("launched") is not True or build_state.get("runtime_load_verified") is not True:
        raise LivePhysicalGateError("renderer build does not prove launch + runtime load")
    if runtime.get("vrm_loaded") is not True or runtime.get("renderer_bound") is not True:
        raise LivePhysicalGateError("renderer runtime does not prove VRM load + bind")

    artifacts = build.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise LivePhysicalGateError("renderer build artifact metadata is missing")
    _check_build_artifact(artifacts.get("executable"), evidence_dir=evidence_dir, label="renderer executable")
    _check_build_artifact(artifacts.get("unity_log"), evidence_dir=evidence_dir, label="Unity build log")
    runtime_path, runtime_sha, _ = _check_build_artifact(
        artifacts.get("runtime_receipt"), evidence_dir=evidence_dir, label="renderer runtime receipt"
    )
    if runtime_path != paths["runtime"].resolve() or runtime_sha != digests["runtime"]:
        raise LivePhysicalGateError("build receipt does not bind consumed runtime receipt")

    receipts = run.get("receipts")
    if not isinstance(receipts, Mapping):
        raise LivePhysicalGateError("run receipt bindings are missing")
    for key, path_key in (
        ("preflight", "preflight"),
        ("renderer_build", "build"),
        ("renderer_runtime", "runtime"),
        ("unity_live", "unity_live"),
    ):
        _check_bound_file(
            receipts.get(key),
            expected_path=paths[path_key].resolve(),
            expected_sha=digests[path_key],
            evidence_dir=evidence_dir,
            label=f"run.receipts.{key}",
        )

    _quality_semantics(quality)
    if _parse_time(quality.get("created_at"), label="live quality") < _parse_time(run.get("created_at"), label="machine run"):
        raise LivePhysicalGateError("live quality receipt predates completed machine run")

    return {
        "schema": "bodyrig.unity_live_automatic_gate/v0.1",
        "production_activation": False,
        "pr_number": 846,
        "candidate_git_sha": expected_sha,
        "body_id": body_id,
        "package_sha256": package_sha,
        "rig_url": rig_url,
        "machine_live_proof": True,
        "machine_quality": True,
        "frame_count": frame_count,
        "quality_applied_frames": quality["applied_frames"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_automatic_evidence(
            evidence_dir=args.evidence_dir,
            expected_sha=args.expected_sha,
            repo_root=ROOT,
            require_git_state=True,
        )
    except LivePhysicalGateError as exc:
        print(f"BODYRIG UNITY LIVE AUTOMATIC GATE: FAIL — {exc}", file=sys.stderr)
        return 1
    print(
        "BODYRIG UNITY LIVE AUTOMATIC GATE: PASS — "
        f"#846 @ {result['candidate_git_sha']} · {result['body_id']} · "
        f"{result['quality_applied_frames']} applied live frames"
    )
    print("production_activation=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
