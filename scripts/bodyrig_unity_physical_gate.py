#!/usr/bin/env python3
"""Fail-closed validator for BodyRig M0.3 physical Unity evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BUILD_SCHEMA = "bodyrig.unity_physical_build/v0.2"
RUNTIME_SCHEMA = "bodyrig.unity_runtime_load/v0.1"
VISUAL_SCHEMA = "bodyrig.unity_visual_acceptance/v0.2"
EXPECTED_UNITY = "6000.3.21f1"
EXPECTED_DEPS = {
    "com.vrmc.gltf": "https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#v0.131.2",
    "com.vrmc.vrm": "https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#v0.131.2",
}
EXPECTED_VISUAL_CHECKS = {
    "states_distinct",
    "gaze_blink_breath_visible",
    "explain_gesture_visible",
    "speech_modes_visibly_differ",
    "interruption_immediately_neutralizes_mouth_and_gesture",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_BODY_ID = re.compile(r"^bodyid-[0-9a-f]{24}$")
MAX_JSON_BYTES = 2_000_000
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024
MAX_VRM_BYTES = 192 * 1024 * 1024


class PhysicalRendererGateError(RuntimeError):
    """Physical renderer evidence is missing, stale, malformed or tampered."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path, *, maximum: int = MAX_ARTIFACT_BYTES) -> tuple[str, int]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PhysicalRendererGateError(f"cannot inspect artifact: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PhysicalRendererGateError(
            f"artifact must be a non-symlink regular file: {path}"
        )
    if info.st_size <= 0 or info.st_size > maximum:
        raise PhysicalRendererGateError(f"artifact size is invalid: {path}")
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
                    raise PhysicalRendererGateError(
                        f"artifact exceeds safety cap: {path}"
                    )
                digest.update(chunk)
    except OSError as exc:
        raise PhysicalRendererGateError(f"cannot read artifact: {path}") from exc
    return digest.hexdigest(), total


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PhysicalRendererGateError(f"evidence JSON missing: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PhysicalRendererGateError(
            f"evidence JSON must be a regular file: {path}"
        )
    if info.st_size <= 0 or info.st_size > MAX_JSON_BYTES:
        raise PhysicalRendererGateError(f"evidence JSON size is invalid: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhysicalRendererGateError(f"evidence JSON is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise PhysicalRendererGateError(f"evidence JSON must be an object: {path}")
    return value, raw


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PhysicalRendererGateError(f"{label} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PhysicalRendererGateError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise PhysicalRendererGateError(f"{label} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _git(*args: str, root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PhysicalRendererGateError(f"git {' '.join(args)} failed") from exc
    return result.stdout.strip()


def _repo_fully_clean(root: Path) -> bool:
    return not _git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        root=root,
    )


def _non_symlink_path(path_value: str, *, label: str) -> Path:
    path = Path(path_value).expanduser()
    try:
        info = path.lstat()
    except OSError as exc:
        raise PhysicalRendererGateError(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode):
        raise PhysicalRendererGateError(f"{label} must not be a symlink")
    return path.resolve()


def _evidence_artifact(
    evidence_dir: Path,
    value: Any,
    *,
    label: str,
) -> tuple[Path, str, int]:
    if not isinstance(value, Mapping):
        raise PhysicalRendererGateError(f"{label} metadata is missing")
    path_value = value.get("path")
    expected_sha = value.get("sha256")
    expected_bytes = value.get("bytes")
    if not isinstance(path_value, str) or not path_value:
        raise PhysicalRendererGateError(f"{label} path is invalid")
    path = _non_symlink_path(path_value, label=label)
    try:
        path.relative_to(evidence_dir)
    except ValueError as exc:
        raise PhysicalRendererGateError(
            f"{label} must live inside the evidence directory"
        ) from exc
    actual_sha, actual_bytes = _sha_file(path)
    if not isinstance(expected_sha, str) or _SHA256.fullmatch(expected_sha) is None:
        raise PhysicalRendererGateError(f"{label} SHA-256 is invalid")
    if actual_sha != expected_sha:
        raise PhysicalRendererGateError(f"{label} SHA-256 mismatch")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes != actual_bytes
    ):
        raise PhysicalRendererGateError(f"{label} byte count mismatch")
    return path, actual_sha, actual_bytes


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PhysicalRendererGateError(f"{label} must be lowercase SHA-256")
    return value


def _require_git_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise PhysicalRendererGateError(f"{label} must be a full git SHA")
    return value


def _validate_project_pins(repo_root: Path) -> None:
    try:
        project_version = (
            repo_root
            / "renderers"
            / "bodyrig-unity"
            / "ProjectSettings"
            / "ProjectVersion.txt"
        ).read_text(encoding="utf-8").strip()
        manifest = json.loads(
            (
                repo_root
                / "renderers"
                / "bodyrig-unity"
                / "Packages"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhysicalRendererGateError("cannot read renderer project pins") from exc
    if project_version != f"m_EditorVersion: {EXPECTED_UNITY}":
        raise PhysicalRendererGateError("Unity project version pin changed")
    if not isinstance(manifest, dict) or manifest.get("dependencies") != EXPECTED_DEPS:
        raise PhysicalRendererGateError("UniVRM dependency pins changed")


def _validate_runtime_receipt(
    runtime: Mapping[str, Any],
    *,
    candidate_sha: str,
    body_id: str,
    package_sha: str,
    avatar_sha: str,
    vrm_path: Path,
) -> datetime:
    if runtime.get("schema") != RUNTIME_SCHEMA:
        raise PhysicalRendererGateError("runtime receipt schema mismatch")
    if runtime.get("production_activation") is not False:
        raise PhysicalRendererGateError("runtime receipt activated production")
    if runtime.get("visual_acceptance") is not False:
        raise PhysicalRendererGateError(
            "runtime receipt cannot self-assert visual acceptance"
        )
    if runtime.get("vrm_loaded") is not True or runtime.get("renderer_bound") is not True:
        raise PhysicalRendererGateError(
            "runtime receipt does not prove VRM load + renderer bind"
        )
    if runtime.get("candidate_git_sha") != candidate_sha:
        raise PhysicalRendererGateError("runtime receipt candidate SHA mismatch")
    if runtime.get("body_id") != body_id:
        raise PhysicalRendererGateError("runtime receipt body_id mismatch")
    if runtime.get("package_sha256") != package_sha:
        raise PhysicalRendererGateError("runtime receipt package digest mismatch")
    if runtime.get("avatar_sha256") != avatar_sha:
        raise PhysicalRendererGateError("runtime receipt avatar digest mismatch")
    unity_version = runtime.get("unity_version")
    if not isinstance(unity_version, str) or not unity_version.startswith("6000.3.21"):
        raise PhysicalRendererGateError("runtime receipt Unity version mismatch")
    runtime_vrm_path = runtime.get("vrm_path")
    if not isinstance(runtime_vrm_path, str) or not runtime_vrm_path:
        raise PhysicalRendererGateError("runtime receipt VRM path is invalid")
    if _non_symlink_path(runtime_vrm_path, label="runtime receipt VRM path") != vrm_path:
        raise PhysicalRendererGateError("runtime receipt VRM path mismatch")
    return _parse_time(runtime.get("created_at"), label="runtime")


def validate_evidence(
    *,
    evidence_dir: Path,
    expected_sha: str,
    repo_root: Path = ROOT,
    require_git_state: bool = True,
) -> dict[str, Any]:
    raw_evidence_dir = evidence_dir.expanduser()
    try:
        evidence_info = raw_evidence_dir.lstat()
    except OSError as exc:
        raise PhysicalRendererGateError("evidence directory is missing") from exc
    if stat.S_ISLNK(evidence_info.st_mode) or not stat.S_ISDIR(evidence_info.st_mode):
        raise PhysicalRendererGateError("evidence directory is missing or irregular")
    evidence_dir = raw_evidence_dir.resolve()
    expected_sha = _require_git_sha(expected_sha, label="expected_sha")

    build, build_raw = _load_json(evidence_dir / "build-receipt.json")
    visual, _visual_raw = _load_json(evidence_dir / "visual-receipt.json")
    if build.get("schema") != BUILD_SCHEMA:
        raise PhysicalRendererGateError("build receipt schema mismatch")
    if visual.get("schema") != VISUAL_SCHEMA:
        raise PhysicalRendererGateError("visual receipt schema mismatch")
    if (
        build.get("production_activation") is not False
        or visual.get("production_activation") is not False
    ):
        raise PhysicalRendererGateError(
            "physical evidence must keep production_activation=false"
        )
    if build.get("visual_acceptance") is not False:
        raise PhysicalRendererGateError("build receipt cannot self-assert visual acceptance")
    if visual.get("visual_acceptance") is not True:
        raise PhysicalRendererGateError("visual receipt does not accept rendering")
    if build.get("pr_number") != 720 or visual.get("pr_number") != 720:
        raise PhysicalRendererGateError("physical evidence is not bound to PR #720")

    build_time = _parse_time(build.get("created_at"), label="build")
    visual_time = _parse_time(visual.get("accepted_at"), label="visual acceptance")
    if visual_time < build_time:
        raise PhysicalRendererGateError("visual acceptance predates build receipt")

    candidate = build.get("candidate")
    if not isinstance(candidate, Mapping):
        raise PhysicalRendererGateError("build candidate metadata is missing")
    candidate_sha = _require_git_sha(candidate.get("git_sha"), label="candidate.git_sha")
    if candidate_sha != expected_sha:
        raise PhysicalRendererGateError("physical build candidate differs from expected SHA")
    branch = candidate.get("branch")
    if not isinstance(branch, str) or not branch or branch == "main":
        raise PhysicalRendererGateError("physical proof must run from draft, not main")
    _require_git_sha(candidate.get("origin_main_sha"), label="candidate.origin_main_sha")
    for key in (
        "origin_main_stable_during_build",
        "origin_main_stable_through_runtime",
        "clean_checkout_before_build",
        "working_tree_clean_after_runtime",
    ):
        if candidate.get(key) is not True:
            raise PhysicalRendererGateError(f"candidate.{key} is not true")

    build_state = build.get("build")
    if not isinstance(build_state, Mapping):
        raise PhysicalRendererGateError("build state is missing")
    if build_state.get("success") is not True or build_state.get("exit_code") != 0:
        raise PhysicalRendererGateError("Unity build did not succeed")
    if build_state.get("launched") is not True:
        raise PhysicalRendererGateError("physical renderer was not launched")
    if build_state.get("runtime_load_verified") is not True:
        raise PhysicalRendererGateError("runtime VRM load + bind was not verified")

    renderer = build.get("renderer")
    if not isinstance(renderer, Mapping):
        raise PhysicalRendererGateError("renderer metadata is missing")
    if renderer.get("unity_project_version") != EXPECTED_UNITY:
        raise PhysicalRendererGateError("build Unity project version mismatch")
    product_version = renderer.get("unity_product_version")
    if not isinstance(product_version, str) or not product_version.startswith("6000.3.21"):
        raise PhysicalRendererGateError("Unity executable product version mismatch")
    if renderer.get("univrm_gltf") != EXPECTED_DEPS["com.vrmc.gltf"]:
        raise PhysicalRendererGateError("UniGLTF receipt pin mismatch")
    if renderer.get("univrm_vrm") != EXPECTED_DEPS["com.vrmc.vrm"]:
        raise PhysicalRendererGateError("VRM10 receipt pin mismatch")

    profile = build.get("profile")
    if not isinstance(profile, Mapping):
        raise PhysicalRendererGateError("profile metadata is missing")
    body_id = profile.get("body_id")
    if not isinstance(body_id, str) or _BODY_ID.fullmatch(body_id) is None:
        raise PhysicalRendererGateError("profile body_id is invalid")
    package_sha = _require_sha(profile.get("package_sha256"), label="profile.package_sha256")
    avatar_sha = _require_sha(profile.get("avatar_sha256"), label="profile.avatar_sha256")
    vrm_path_value = profile.get("vrm_path")
    if not isinstance(vrm_path_value, str) or not vrm_path_value:
        raise PhysicalRendererGateError("profile vrm_path is invalid")
    vrm_path = _non_symlink_path(vrm_path_value, label="digest-bound staged avatar")
    actual_avatar_sha, _avatar_bytes = _sha_file(vrm_path, maximum=MAX_VRM_BYTES)
    if actual_avatar_sha != avatar_sha:
        raise PhysicalRendererGateError("staged avatar changed after physical build")
    try:
        from bodyrig.mrbody import validate_vrm1_bytes

        validate_vrm1_bytes(vrm_path.read_bytes())
    except Exception as exc:
        raise PhysicalRendererGateError("staged avatar fails VRM 1.0 validation") from exc

    artifacts = build.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise PhysicalRendererGateError("build artifacts metadata is missing")
    exe_path, exe_sha, _exe_bytes = _evidence_artifact(
        evidence_dir, artifacts.get("executable"), label="renderer executable"
    )
    _log_path, _log_sha, _log_bytes = _evidence_artifact(
        evidence_dir, artifacts.get("unity_log"), label="Unity build log"
    )
    runtime_path, runtime_sha, _runtime_bytes = _evidence_artifact(
        evidence_dir,
        artifacts.get("runtime_receipt"),
        label="runtime VRM-load receipt",
    )
    runtime, _runtime_raw = _load_json(runtime_path)
    runtime_time = _validate_runtime_receipt(
        runtime,
        candidate_sha=candidate_sha,
        body_id=body_id,
        package_sha=package_sha,
        avatar_sha=avatar_sha,
        vrm_path=vrm_path,
    )
    if runtime_time > build_time:
        raise PhysicalRendererGateError("runtime receipt postdates build receipt")

    if _require_git_sha(
        visual.get("candidate_git_sha"), label="visual.candidate_git_sha"
    ) != candidate_sha:
        raise PhysicalRendererGateError("visual candidate differs from build")
    if _require_sha(
        visual.get("build_receipt_sha256"), label="visual.build_receipt_sha256"
    ) != _sha_bytes(build_raw):
        raise PhysicalRendererGateError("visual receipt is not bound to build receipt")
    if _require_sha(
        visual.get("runtime_receipt_sha256"), label="visual.runtime_receipt_sha256"
    ) != runtime_sha:
        raise PhysicalRendererGateError("visual runtime receipt digest mismatch")
    if _require_sha(
        visual.get("executable_sha256"), label="visual.executable_sha256"
    ) != exe_sha:
        raise PhysicalRendererGateError("visual executable digest mismatch")

    visual_profile = visual.get("profile")
    if not isinstance(visual_profile, Mapping):
        raise PhysicalRendererGateError("visual profile metadata is missing")
    if visual_profile.get("body_id") != body_id:
        raise PhysicalRendererGateError("visual body_id mismatch")
    if visual_profile.get("package_sha256") != package_sha:
        raise PhysicalRendererGateError("visual package digest mismatch")
    if visual_profile.get("avatar_sha256") != avatar_sha:
        raise PhysicalRendererGateError("visual avatar digest mismatch")

    checks = visual.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != EXPECTED_VISUAL_CHECKS:
        raise PhysicalRendererGateError("visual check set is incomplete or unexpected")
    if any(checks[key] is not True for key in EXPECTED_VISUAL_CHECKS):
        raise PhysicalRendererGateError("one or more visual checks are not accepted")

    operator = visual.get("operator")
    if not isinstance(operator, Mapping):
        raise PhysicalRendererGateError("operator attestation is missing")
    if (
        operator.get("attestation")
        != "directly observed on the physical Windows renderer rig"
    ):
        raise PhysicalRendererGateError("operator attestation text mismatch")
    if not isinstance(operator.get("user"), str) or not operator.get("user"):
        raise PhysicalRendererGateError("operator user is missing")
    if not isinstance(operator.get("machine"), str) or not operator.get("machine"):
        raise PhysicalRendererGateError("operator machine is missing")

    _validate_project_pins(repo_root)
    if require_git_state:
        current_sha = _require_git_sha(
            _git("rev-parse", "HEAD", root=repo_root), label="current HEAD"
        )
        if current_sha != candidate_sha:
            raise PhysicalRendererGateError("current checkout differs from accepted SHA")
        if not _repo_fully_clean(repo_root):
            raise PhysicalRendererGateError(
                "repository is not fully clean after physical acceptance"
            )

    return {
        "schema": "bodyrig.unity_physical_gate/v0.2",
        "status": "pass",
        "production_activation": False,
        "candidate_git_sha": candidate_sha,
        "origin_main_sha_at_build": candidate.get("origin_main_sha"),
        "body_id": body_id,
        "package_sha256": package_sha,
        "avatar_sha256": avatar_sha,
        "runtime_receipt_sha256": runtime_sha,
        "runtime_vrm_loaded": True,
        "runtime_renderer_bound": True,
        "renderer_executable": str(exe_path),
        "renderer_executable_sha256": exe_sha,
        "visual_acceptance": True,
    }


def _default_evidence_dir(expected_sha: str) -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
    if not base:
        raise PhysicalRendererGateError(
            "cannot infer evidence directory; pass --evidence-dir explicitly"
        )
    return Path(base) / "ModelRig" / "BodyRigEvidence" / expected_sha


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate exact-SHA Unity build, runtime VRM load/bind and explicit "
            "visual acceptance for BodyRig PR #720. Never activates production."
        )
    )
    parser.add_argument(
        "--expected-sha",
        default=None,
        help="exact 40-hex draft SHA; defaults to current git HEAD",
    )
    parser.add_argument(
        "--evidence-dir",
        default=None,
        help=(
            "physical evidence directory; defaults to "
            "LOCALAPPDATA/ModelRig/BodyRigEvidence/<SHA>"
        ),
    )
    args = parser.parse_args()
    expected_sha = args.expected_sha or _git("rev-parse", "HEAD", root=ROOT)
    evidence_dir = (
        Path(args.evidence_dir)
        if args.evidence_dir
        else _default_evidence_dir(expected_sha)
    )
    try:
        result = validate_evidence(
            evidence_dir=evidence_dir,
            expected_sha=expected_sha,
            repo_root=ROOT,
            require_git_state=True,
        )
    except PhysicalRendererGateError as exc:
        print(f"BODYRIG UNITY PHYSICAL GATE: FAIL — {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    print("BODYRIG UNITY PHYSICAL GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
