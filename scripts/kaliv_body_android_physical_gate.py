#!/usr/bin/env python3
"""Independent fail-closed gate for current Kaliv Body Android live-body evidence."""
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
HOST_SCHEMA = "modelrig.kaliv-body.android-host-qualification/v1"
VISUAL_SCHEMA = "modelrig.kaliv-body.android-visual-acceptance/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_JSON_BYTES = 2_000_000
MAX_APK_BYTES = 8 * 1024 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024
EXPECTED_VISUAL_CHECKS = {
    "avatar_visible_and_stable",
    "placement_matches_tapped_plane",
    "camera_background_tracks_room",
    "body_animation_continues_after_placement",
    "no_visible_credential_or_debug_leak",
}


class AndroidPhysicalGateError(RuntimeError):
    """Android physical evidence is missing, stale, malformed or tampered."""


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AndroidPhysicalGateError(f"git {' '.join(args)} failed") from exc
    return result.stdout.strip()


def _require_git_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise AndroidPhysicalGateError(f"{label} must be a full lowercase git SHA")
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AndroidPhysicalGateError(f"{label} must be lowercase SHA-256")
    return value


def _load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise AndroidPhysicalGateError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AndroidPhysicalGateError(f"{label} must be a non-symlink regular file")
    if info.st_size <= 0 or info.st_size > MAX_JSON_BYTES:
        raise AndroidPhysicalGateError(f"{label} size is invalid")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AndroidPhysicalGateError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise AndroidPhysicalGateError(f"{label} must be a JSON object")
    return value, raw


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AndroidPhysicalGateError(f"{label} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AndroidPhysicalGateError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise AndroidPhysicalGateError(f"{label} timestamp needs timezone")
    return parsed.astimezone(timezone.utc)


def _hash_file(path_value: Any, *, label: str, maximum: int) -> tuple[Path, str, int]:
    if not isinstance(path_value, str) or not path_value:
        raise AndroidPhysicalGateError(f"{label} path is missing")
    path = Path(path_value).expanduser()
    try:
        info = path.lstat()
    except OSError as exc:
        raise AndroidPhysicalGateError(f"{label} artifact is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AndroidPhysicalGateError(f"{label} must be a non-symlink regular file")
    if info.st_size <= 0 or info.st_size > maximum:
        raise AndroidPhysicalGateError(f"{label} size is invalid")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise AndroidPhysicalGateError(f"{label} exceeds safety cap")
            digest.update(chunk)
    return path.resolve(), digest.hexdigest(), total


def validate(
    *,
    expected_sha: str,
    host_receipt_path: Path,
    visual_receipt_path: Path,
    require_git_state: bool = True,
) -> dict[str, Any]:
    expected_sha = _require_git_sha(expected_sha, label="expected_sha")
    host, host_raw = _load_json(host_receipt_path, label="host receipt")
    visual, visual_raw = _load_json(visual_receipt_path, label="visual receipt")

    if host.get("schema") != HOST_SCHEMA:
        raise AndroidPhysicalGateError("host receipt schema mismatch")
    if visual.get("schema") != VISUAL_SCHEMA:
        raise AndroidPhysicalGateError("visual receipt schema mismatch")
    if host.get("exact_head") != expected_sha or visual.get("exact_head") != expected_sha:
        raise AndroidPhysicalGateError("physical receipts are not bound to expected exact head")

    for receipt, label in ((host, "host"), (visual, "visual")):
        if receipt.get("production_activation") is not False:
            raise AndroidPhysicalGateError(f"{label} receipt activated production")
        if receipt.get("release_gate_satisfied") is not False:
            raise AndroidPhysicalGateError(f"{label} receipt self-asserted release gate")

    if host.get("build_exit_code") != 0:
        raise AndroidPhysicalGateError("Android build exit code was not zero")
    if host.get("checkout_clean_after_build") is not True:
        raise AndroidPhysicalGateError("checkout was not clean after Android build")
    if host.get("installed") is not True or host.get("launched") is not True:
        raise AndroidPhysicalGateError("host receipt lacks physical install+launch proof")
    if not isinstance(host.get("app_pid"), str) or not host.get("app_pid"):
        raise AndroidPhysicalGateError("host receipt has no live app PID")
    if host.get("fatal_package_crash_observed") is not False:
        raise AndroidPhysicalGateError("host receipt observed a package-scoped fatal crash")
    if host.get("rig_link_qualified") is not True:
        raise AndroidPhysicalGateError("intent RigLink was not physically qualified")
    if host.get("rig_link_token_leak_observed") is not False:
        raise AndroidPhysicalGateError("RigLink token leakage was observed")
    if host.get("arcore_runtime_qualified") is not True:
        raise AndroidPhysicalGateError("strong ARCore runtime was not physically qualified")
    if host.get("plane_placement_qualified") is not True:
        raise AndroidPhysicalGateError("detected-plane placement was not qualified")
    if host.get("avatar_from_rig_qualified") is not True:
        raise AndroidPhysicalGateError("digest-bound remote avatar was not qualified")
    if host.get("live_frame_qualified") is not True:
        raise AndroidPhysicalGateError("authenticated live frame was not qualified")
    if host.get("live_body_qualified") is not True:
        raise AndroidPhysicalGateError("end-to-end live BodyRig was not qualified")
    if host.get("visual_acceptance") is not False:
        raise AndroidPhysicalGateError("host receipt may not self-assert visual acceptance")

    apk_path, apk_sha, apk_bytes = _hash_file(
        host.get("apk_path"), label="APK", maximum=MAX_APK_BYTES
    )
    if apk_sha != _require_sha256(host.get("apk_sha256"), label="host.apk_sha256"):
        raise AndroidPhysicalGateError("APK SHA-256 mismatch")
    if host.get("apk_size_bytes") != apk_bytes:
        raise AndroidPhysicalGateError("APK byte count mismatch")

    logcat_path, logcat_sha, logcat_bytes = _hash_file(
        host.get("logcat_path"), label="logcat", maximum=MAX_LOG_BYTES
    )
    if logcat_sha != _require_sha256(host.get("logcat_sha256"), label="host.logcat_sha256"):
        raise AndroidPhysicalGateError("logcat SHA-256 mismatch")
    if host.get("logcat_size_bytes") != logcat_bytes:
        raise AndroidPhysicalGateError("logcat byte count mismatch")

    host_time = _parse_time(host.get("timestamp_utc"), label="host")
    visual_time = _parse_time(visual.get("accepted_at"), label="visual")
    if visual_time < host_time:
        raise AndroidPhysicalGateError("visual acceptance predates host qualification")

    host_receipt_sha = hashlib.sha256(host_raw).hexdigest()
    if _require_sha256(
        visual.get("host_receipt_sha256"), label="visual.host_receipt_sha256"
    ) != host_receipt_sha:
        raise AndroidPhysicalGateError("visual receipt is not SHA-bound to host receipt")

    visual_host_path = visual.get("host_receipt_path")
    if not isinstance(visual_host_path, str) or not visual_host_path:
        raise AndroidPhysicalGateError("visual receipt host path is missing")
    if Path(visual_host_path).expanduser().resolve() != host_receipt_path.resolve():
        raise AndroidPhysicalGateError("visual receipt points at a different host receipt")
    if visual.get("visual_acceptance") is not True:
        raise AndroidPhysicalGateError("human visual acceptance is not true")

    prerequisites = visual.get("prerequisites")
    if not isinstance(prerequisites, Mapping):
        raise AndroidPhysicalGateError("visual prerequisites are missing")
    expected_prerequisites = {
        "installed": True,
        "launched": True,
        "rig_link_qualified": True,
        "rig_link_token_leak_observed": False,
        "arcore_runtime_qualified": True,
        "plane_placement_qualified": True,
        "avatar_from_rig_qualified": True,
        "live_frame_qualified": True,
        "live_body_qualified": True,
    }
    if dict(prerequisites) != expected_prerequisites:
        raise AndroidPhysicalGateError("visual prerequisite projection mismatches host receipt")

    checks = visual.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != EXPECTED_VISUAL_CHECKS:
        raise AndroidPhysicalGateError("visual acceptance check set is incomplete or unexpected")
    if any(checks[name] is not True for name in EXPECTED_VISUAL_CHECKS):
        raise AndroidPhysicalGateError("one or more visual acceptance checks are false")

    operator = visual.get("operator")
    if not isinstance(operator, Mapping):
        raise AndroidPhysicalGateError("visual operator attestation is missing")
    if operator.get("attestation") != "directly observed on the physical Android Kaliv Body host":
        raise AndroidPhysicalGateError("visual operator attestation text mismatch")
    if not isinstance(operator.get("user"), str) or not operator.get("user"):
        raise AndroidPhysicalGateError("visual operator user is missing")
    if not isinstance(operator.get("machine"), str) or not operator.get("machine"):
        raise AndroidPhysicalGateError("visual operator machine is missing")

    if require_git_state:
        current_sha = _require_git_sha(_git("rev-parse", "HEAD"), label="current HEAD")
        if current_sha != expected_sha:
            raise AndroidPhysicalGateError("current checkout differs from accepted SHA")
        if _git("status", "--porcelain=v1", "--untracked-files=all"):
            raise AndroidPhysicalGateError("repository is not fully clean")

    result = {
        "schema": "modelrig.kaliv-body.android-physical-gate/v1",
        "status": "pass",
        "exact_head": expected_sha,
        "production_activation": False,
        "release_gate_satisfied": False,
        "apk_path": str(apk_path),
        "apk_sha256": apk_sha,
        "apk_size_bytes": apk_bytes,
        "logcat_path": str(logcat_path),
        "logcat_sha256": logcat_sha,
        "logcat_size_bytes": logcat_bytes,
        "host_receipt_sha256": host_receipt_sha,
        "visual_receipt_sha256": hashlib.sha256(visual_raw).hexdigest(),
        "rig_link_qualified": True,
        "arcore_runtime_qualified": True,
        "plane_placement_qualified": True,
        "avatar_from_rig_qualified": True,
        "live_frame_qualified": True,
        "live_body_qualified": True,
        "visual_acceptance": True,
    }
    canonical = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    result["evidence_ref"] = (
        "kaliv-body-android-physical-gate:"
        + expected_sha
        + ":"
        + hashlib.sha256(canonical).hexdigest()
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate exact-head Kaliv Body Android live-body + visual physical evidence."
    )
    parser.add_argument("--expected-sha", default=None)
    parser.add_argument(
        "--host-receipt",
        default=str(ROOT / "validation" / "kaliv-body-android-latest.json"),
    )
    parser.add_argument(
        "--visual-receipt",
        default=str(ROOT / "validation" / "kaliv-body-android-visual-latest.json"),
    )
    args = parser.parse_args()

    expected_sha = args.expected_sha or _git("rev-parse", "HEAD")
    try:
        result = validate(
            expected_sha=expected_sha,
            host_receipt_path=Path(args.host_receipt),
            visual_receipt_path=Path(args.visual_receipt),
            require_git_state=True,
        )
    except AndroidPhysicalGateError as exc:
        print(f"KALIV BODY ANDROID PHYSICAL GATE: FAIL — {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    print("KALIV BODY ANDROID PHYSICAL GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
