#!/usr/bin/env python3
"""Independent fail-closed gate for BodyRig Unity live-frame evidence (#846)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_BRANCH = "feat/unity-frame-source"

RUN_SCHEMA = "bodyrig.unity_live_run/v0.1"
PREFLIGHT_SCHEMA = "bodyrig.live_stream_probe/v0.1"
UNITY_LIVE_SCHEMA = "bodyrig.unity_live_stream/v0.1"
BUILD_SCHEMA = "bodyrig.unity_physical_build/v0.2"
RUNTIME_SCHEMA = "bodyrig.unity_runtime_load/v0.1"
VISUAL_SCHEMA = "bodyrig.unity_live_visual_acceptance/v0.1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_BODY_ID = re.compile(r"^bodyid-[0-9a-f]{24}$")
MAX_JSON_BYTES = 2_000_000
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024
EXPECTED_VISUAL_CHECKS = {
    "idle_listening_thinking_speaking_interrupted_are_visibly_distinct",
    "gaze_blink_breath_are_visible",
    "mouth_motion_tracks_live_speech_playback",
    "interruption_immediately_neutralizes_mouth_and_gesture",
}


class LivePhysicalGateError(RuntimeError):
    """Live renderer evidence is missing, stale, malformed or tampered."""


def _sha_file(path: Path, *, maximum: int = MAX_ARTIFACT_BYTES) -> tuple[str, int]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise LivePhysicalGateError(f"cannot inspect artifact: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise LivePhysicalGateError(f"artifact must be a non-symlink regular file: {path}")
    if info.st_size <= 0 or info.st_size > maximum:
        raise LivePhysicalGateError(f"artifact size is invalid: {path}")
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise LivePhysicalGateError(f"artifact exceeds safety cap: {path}")
                digest.update(chunk)
    except OSError as exc:
        raise LivePhysicalGateError(f"cannot read artifact: {path}") from exc
    return digest.hexdigest(), total


def _load_json(path: Path) -> tuple[dict[str, Any], str, int]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise LivePhysicalGateError(f"evidence JSON missing: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise LivePhysicalGateError(f"evidence JSON must be a regular file: {path}")
    if info.st_size <= 0 or info.st_size > MAX_JSON_BYTES:
        raise LivePhysicalGateError(f"evidence JSON size is invalid: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LivePhysicalGateError(f"evidence JSON is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise LivePhysicalGateError(f"evidence JSON must be an object: {path}")
    return value, hashlib.sha256(raw).hexdigest(), len(raw)


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise LivePhysicalGateError(f"{label} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LivePhysicalGateError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise LivePhysicalGateError(f"{label} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _require_git_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise LivePhysicalGateError(f"{label} must be a full lowercase git SHA")
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LivePhysicalGateError(f"{label} must be lowercase SHA-256")
    return value


def _require_body_id(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _BODY_ID.fullmatch(value) is None:
        raise LivePhysicalGateError(f"{label} is invalid")
    return value


def _git(*args: str, root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LivePhysicalGateError(f"git {' '.join(args)} failed") from exc
    return result.stdout.strip()


def _inside_evidence(path_value: Any, *, evidence_dir: Path, label: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise LivePhysicalGateError(f"{label} path is invalid")
    raw = Path(path_value).expanduser()
    try:
        info = raw.lstat()
    except OSError as exc:
        raise LivePhysicalGateError(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode):
        raise LivePhysicalGateError(f"{label} must not be a symlink")
    resolved = raw.resolve()
    try:
        resolved.relative_to(evidence_dir)
    except ValueError as exc:
        raise LivePhysicalGateError(f"{label} must live inside the evidence directory") from exc
    return resolved


def _check_bound_file(
    metadata: Any,
    *,
    expected_path: Path,
    expected_sha: str,
    evidence_dir: Path,
    label: str,
) -> None:
    if not isinstance(metadata, Mapping):
        raise LivePhysicalGateError(f"{label} metadata is missing")
    path = _inside_evidence(metadata.get("path"), evidence_dir=evidence_dir, label=label)
    if path != expected_path:
        raise LivePhysicalGateError(f"{label} path mismatch")
    sha = _require_sha256(metadata.get("sha256"), label=f"{label}.sha256")
    if sha != expected_sha:
        raise LivePhysicalGateError(f"{label} SHA-256 binding mismatch")


def _check_build_artifact(
    metadata: Any,
    *,
    evidence_dir: Path,
    label: str,
) -> tuple[Path, str, int]:
    if not isinstance(metadata, Mapping):
        raise LivePhysicalGateError(f"{label} metadata is missing")
    path = _inside_evidence(metadata.get("path"), evidence_dir=evidence_dir, label=label)
    expected_sha = _require_sha256(metadata.get("sha256"), label=f"{label}.sha256")
    expected_bytes = metadata.get("bytes")
    actual_sha, actual_bytes = _sha_file(path)
    if actual_sha != expected_sha:
        raise LivePhysicalGateError(f"{label} SHA-256 mismatch")
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes != actual_bytes:
        raise LivePhysicalGateError(f"{label} byte count mismatch")
    return path, actual_sha, actual_bytes


def validate_evidence(
    *,
    evidence_dir: Path,
    expected_sha: str,
    repo_root: Path = ROOT,
    require_git_state: bool = True,
) -> dict[str, Any]:
    expected_sha = _require_git_sha(expected_sha, label="expected_sha")
    raw_dir = evidence_dir.expanduser()
    try:
        info = raw_dir.lstat()
    except OSError as exc:
        raise LivePhysicalGateError("evidence directory is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise LivePhysicalGateError("evidence directory is missing or irregular")
    evidence_dir = raw_dir.resolve()

    if require_git_state:
        if _git("rev-parse", "HEAD", root=repo_root) != expected_sha:
            raise LivePhysicalGateError("current HEAD differs from expected live candidate")
        if _git("status", "--porcelain=v1", "--untracked-files=all", root=repo_root):
            raise LivePhysicalGateError("repository is not fully clean")

    paths = {
        "run": evidence_dir / "live-run-receipt.json",
        "preflight": evidence_dir / "live-preflight-receipt.json",
        "unity_live": evidence_dir / "unity-live-receipt.json",
        "build": evidence_dir / "renderer" / "build-receipt.json",
        "runtime": evidence_dir / "renderer" / "runtime-receipt.json",
        "visual": evidence_dir / "live-visual-receipt.json",
    }
    loaded = {name: _load_json(path) for name, path in paths.items()}
    run, run_sha, _ = loaded["run"]
    preflight, preflight_sha, _ = loaded["preflight"]
    unity_live, unity_live_sha, _ = loaded["unity_live"]
    build, build_sha, _ = loaded["build"]
    runtime, runtime_sha, _ = loaded["runtime"]
    visual, _visual_sha, _ = loaded["visual"]

    schemas = {
        "run": (run, RUN_SCHEMA),
        "preflight": (preflight, PREFLIGHT_SCHEMA),
        "unity_live": (unity_live, UNITY_LIVE_SCHEMA),
        "build": (build, BUILD_SCHEMA),
        "runtime": (runtime, RUNTIME_SCHEMA),
        "visual": (visual, VISUAL_SCHEMA),
    }
    for name, (value, schema) in schemas.items():
        if value.get("schema") != schema:
            raise LivePhysicalGateError(f"{name} receipt schema mismatch")
        if value.get("production_activation") is not False:
            raise LivePhysicalGateError(f"{name} receipt activated production")

    if run.get("visual_acceptance") is not False:
        raise LivePhysicalGateError("machine live run cannot self-assert visual acceptance")
    if visual.get("visual_acceptance") is not True:
        raise LivePhysicalGateError("human live visual acceptance is not true")
    if run.get("pr_number") != 846 or visual.get("pr_number") != 846:
        raise LivePhysicalGateError("live evidence is not bound to PR #846")

    sha_values = {
        "run": run.get("candidate_git_sha"),
        "preflight": preflight.get("candidate_git_sha"),
        "unity_live": unity_live.get("candidate_git_sha"),
        "build": (build.get("candidate") or {}).get("git_sha") if isinstance(build.get("candidate"), Mapping) else None,
        "runtime": runtime.get("candidate_git_sha"),
        "visual": visual.get("candidate_git_sha"),
    }
    for name, value in sha_values.items():
        if _require_git_sha(value, label=f"{name}.candidate_git_sha") != expected_sha:
            raise LivePhysicalGateError(f"{name} candidate SHA mismatch")

    authority = run.get("authority")
    if not isinstance(authority, Mapping):
        raise LivePhysicalGateError("machine live run authority is missing")
    if authority.get("remote_branch") != CANDIDATE_BRANCH:
        raise LivePhysicalGateError("machine live run remote branch mismatch")
    recorded_remote_head = _require_git_sha(
        authority.get("remote_pr_head_sha"), label="run.authority.remote_pr_head_sha"
    )
    recorded_main = _require_git_sha(
        authority.get("origin_main_sha"), label="run.authority.origin_main_sha"
    )
    if recorded_remote_head != expected_sha:
        raise LivePhysicalGateError("machine live run was not bound to expected remote PR head")
    if authority.get("remote_pr_head_verified") is not True:
        raise LivePhysicalGateError("machine live run did not verify remote PR head")
    if authority.get("origin_main_stable_during_run") is not True:
        raise LivePhysicalGateError("machine live run did not prove stable origin/main")
    if authority.get("clean_checkout") is not True:
        raise LivePhysicalGateError("machine live run did not start/end from a clean checkout")

    if require_git_state:
        _git("fetch", "--quiet", "origin", "main", CANDIDATE_BRANCH, root=repo_root)
        current_remote_head = _git("rev-parse", f"origin/{CANDIDATE_BRANCH}", root=repo_root)
        current_main = _git("rev-parse", "origin/main", root=repo_root)
        if current_remote_head != expected_sha:
            raise LivePhysicalGateError("remote #846 head moved after machine evidence was collected")
        if current_main != recorded_main:
            raise LivePhysicalGateError("origin/main moved after machine evidence was collected")
        behind = _git("rev-list", "--count", f"{expected_sha}..origin/main", root=repo_root)
        if behind != "0":
            raise LivePhysicalGateError("#846 candidate is behind current origin/main")

    profile = run.get("profile")
    if not isinstance(profile, Mapping):
        raise LivePhysicalGateError("run profile metadata is missing")
    body_id = _require_body_id(profile.get("body_id"), label="run.profile.body_id")
    package_sha = _require_sha256(profile.get("package_sha256"), label="run.profile.package_sha256")

    body_values = {
        "preflight": preflight.get("active_body_id"),
        "unity_live": unity_live.get("body_id"),
        "build": (build.get("profile") or {}).get("body_id") if isinstance(build.get("profile"), Mapping) else None,
        "runtime": runtime.get("body_id"),
        "visual": (visual.get("profile") or {}).get("body_id") if isinstance(visual.get("profile"), Mapping) else None,
    }
    package_values = {
        "preflight": preflight.get("active_package_sha256"),
        "unity_live": unity_live.get("package_sha256"),
        "build": (build.get("profile") or {}).get("package_sha256") if isinstance(build.get("profile"), Mapping) else None,
        "runtime": runtime.get("package_sha256"),
        "visual": (visual.get("profile") or {}).get("package_sha256") if isinstance(visual.get("profile"), Mapping) else None,
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
    if preflight.get("base_url") != rig_url or unity_live.get("source_url") != rig_url or visual.get("rig_url") != rig_url:
        raise LivePhysicalGateError("rig/source URL differs across live evidence")
    if preflight.get("token_source") != "environment":
        raise LivePhysicalGateError("preflight token did not come from environment")
    if preflight.get("canonical_frame_validation") is not True:
        raise LivePhysicalGateError("preflight did not validate canonical frames")
    frame_count = preflight.get("frame_count")
    first_ts = preflight.get("first_timestamp_ms")
    last_ts = preflight.get("last_timestamp_ms")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 2:
        raise LivePhysicalGateError("preflight frame count is insufficient")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (first_ts, last_ts)) or last_ts <= first_ts:
        raise LivePhysicalGateError("preflight timestamp interval is invalid")

    if unity_live.get("bearer_auth_used") is not True:
        raise LivePhysicalGateError("Unity live source did not attest Bearer auth")
    if unity_live.get("renderer_bound") is not True or unity_live.get("frame_applied") is not True:
        raise LivePhysicalGateError("Unity did not attest an applied frame on a bound renderer")
    unity_first_ts = unity_live.get("first_frame_timestamp_ms")
    if isinstance(unity_first_ts, bool) or not isinstance(unity_first_ts, int) or unity_first_ts < 0:
        raise LivePhysicalGateError("Unity first-frame timestamp is invalid")
    if not isinstance(unity_live.get("first_frame_state"), str) or not unity_live.get("first_frame_state"):
        raise LivePhysicalGateError("Unity first-frame state is missing")

    build_state = build.get("build")
    if not isinstance(build_state, Mapping):
        raise LivePhysicalGateError("renderer build state is missing")
    if build_state.get("success") is not True or build_state.get("exit_code") != 0:
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
    runtime_artifact_path, runtime_artifact_sha, _ = _check_build_artifact(
        artifacts.get("runtime_receipt"), evidence_dir=evidence_dir, label="renderer runtime receipt"
    )
    if runtime_artifact_path != paths["runtime"].resolve() or runtime_artifact_sha != runtime_sha:
        raise LivePhysicalGateError("build receipt does not bind the consumed runtime receipt")

    receipts = run.get("receipts")
    if not isinstance(receipts, Mapping):
        raise LivePhysicalGateError("run receipt bindings are missing")
    for key, expected_path, expected_digest in (
        ("preflight", paths["preflight"].resolve(), preflight_sha),
        ("renderer_build", paths["build"].resolve(), build_sha),
        ("renderer_runtime", paths["runtime"].resolve(), runtime_sha),
        ("unity_live", paths["unity_live"].resolve(), unity_live_sha),
    ):
        _check_bound_file(
            receipts.get(key), expected_path=expected_path, expected_sha=expected_digest,
            evidence_dir=evidence_dir, label=f"run.receipts.{key}",
        )

    evidence_hashes = visual.get("evidence_sha256")
    if not isinstance(evidence_hashes, Mapping):
        raise LivePhysicalGateError("visual evidence hash bindings are missing")
    expected_visual_hashes = {
        "live_run": run_sha,
        "preflight": preflight_sha,
        "unity_live": unity_live_sha,
        "renderer_build": build_sha,
        "renderer_runtime": runtime_sha,
    }
    for key, expected in expected_visual_hashes.items():
        if _require_sha256(evidence_hashes.get(key), label=f"visual.evidence_sha256.{key}") != expected:
            raise LivePhysicalGateError(f"visual evidence hash mismatch: {key}")

    checks = visual.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != EXPECTED_VISUAL_CHECKS:
        raise LivePhysicalGateError("visual check set is incomplete or contains unexpected checks")
    if any(checks.get(name) is not True for name in EXPECTED_VISUAL_CHECKS):
        raise LivePhysicalGateError("one or more live visual checks were not accepted")

    operator = visual.get("operator")
    if not isinstance(operator, Mapping) or not operator.get("user") or not operator.get("machine") or not operator.get("attestation"):
        raise LivePhysicalGateError("human operator attestation is incomplete")

    run_time = _parse_time(run.get("created_at"), label="run")
    visual_time = _parse_time(visual.get("accepted_at"), label="visual acceptance")
    _parse_time(preflight.get("created_at"), label="preflight")
    _parse_time(unity_live.get("created_at"), label="Unity live")
    _parse_time(build.get("created_at"), label="renderer build")
    _parse_time(runtime.get("created_at"), label="renderer runtime")
    if visual_time < run_time:
        raise LivePhysicalGateError("visual acceptance predates the completed machine live run")

    return {
        "schema": "bodyrig.unity_live_physical_gate/v0.1",
        "production_activation": False,
        "pr_number": 846,
        "candidate_git_sha": expected_sha,
        "body_id": body_id,
        "package_sha256": package_sha,
        "rig_url": rig_url,
        "machine_live_proof": True,
        "visual_acceptance": True,
        "frame_count": frame_count,
        "first_live_state": unity_live["first_frame_state"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_evidence(
            evidence_dir=args.evidence_dir,
            expected_sha=args.expected_sha,
            repo_root=ROOT,
            require_git_state=True,
        )
    except LivePhysicalGateError as exc:
        print(f"BODYRIG UNITY LIVE PHYSICAL GATE: FAIL — {exc}", file=sys.stderr)
        return 1
    print(
        "BODYRIG UNITY LIVE PHYSICAL GATE: PASS — "
        f"#846 @ {result['candidate_git_sha']} · {result['body_id']} · "
        f"{result['frame_count']} preflight frames"
    )
    print("production_activation=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
