#!/usr/bin/env python3
"""Bind a physically accepted BodyRig release to one installed ModelRig body.

This is a proof/reference bridge for ModelRig #704. It deliberately does NOT
activate BodyRig in ModelRig. The upstream BodyRig receipt may carry
``production_activation=true``; the ModelRig binding receipt always carries
``production_activation=false`` until ModelRig's own physical/integration gates
are complete.

The bridge is intentionally strict:
- BodyRig release receipt must be canonical ``bodyrig-release-acceptance`` v2;
- both Windows and Quest machine evidence must be present and identity-coherent;
- BodyRig checkout must be the exact clean revision named by the receipt;
- ModelRig checkout must be clean;
- the exact body/package must already be installed and freshly revalidated by
  ModelRig's ``MRBodyProfileStore``;
- output contains only hash/identity/proof metadata, never source paths,
  credentials, raw frames or model-asset paths.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyrig.profile_store import (  # noqa: E402
    MRBodyProfileNotFoundError,
    MRBodyProfileStore,
    MRBodyProfileStoreError,
)

UPSTREAM_FORMAT = "bodyrig-release-acceptance"
UPSTREAM_VERSION = 2
BINDING_SCHEMA = "modelrig.bodyrig_upstream_release/v0.1"
UPSTREAM_REPOSITORY = "Ternedal/BodyRig"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BODY_ID = re.compile(r"^bodyid-[0-9a-f]{24}$")

_TOP_KEYS = {
    "format",
    "version",
    "completed_at",
    "bodyrig_revision",
    "automated_acceptance",
    "renderer_acceptance",
    "release_gate_pass",
    "production_activation",
}
_AUTOMATED_KEYS = {
    "report_sha256",
    "package_sha256",
    "body_id",
    "automated_pass",
    "physical_clone_mode",
    "physical_clone_session_sha256",
    "physical_clone_readiness_sha256",
    "skin_qa_report_sha256",
    "skin_qa_assessment",
}
_RENDERER_KEYS = {
    "bodyrig_revision",
    "probe_report_sha256",
    "deformation_report_sha256",
    "quality_report_sha256",
    "deformation_sequence_revision",
    "machine_quality_revision",
    "machine_quality_pass",
    "runtime_manifest_sha256",
    "avatar_sha256",
    "bodyprint_sha256",
    "renderer_name",
    "renderer_version",
    "unity_platform",
    "unity_version",
    "build_guid",
    "device_model",
    "graphics_device",
    "probe_observed_at",
    "deformation_observed_at",
    "quality_observed_at",
}
_RENDERER_NAMES = {"windows_unity_univrm", "android_quest_class"}
_MAX_RECEIPT_BYTES = 1024 * 1024


class UpstreamReleaseBindingError(RuntimeError):
    pass


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise UpstreamReleaseBindingError(
            f"{label} fields drifted; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _need_sha40(value: Any, label: str) -> str:
    text = str(value or "").lower()
    if SHA40.fullmatch(text) is None:
        raise UpstreamReleaseBindingError(f"{label} is not canonical lowercase Git SHA-1")
    return text


def _need_sha256(value: Any, label: str) -> str:
    text = str(value or "").lower()
    if SHA256.fullmatch(text) is None:
        raise UpstreamReleaseBindingError(f"{label} is not canonical lowercase SHA-256")
    return text


def _need_body_id(value: Any, label: str) -> str:
    text = str(value or "")
    if BODY_ID.fullmatch(text) is None:
        raise UpstreamReleaseBindingError(f"{label} is not a canonical bodyid")
    return text


def _need_timestamp(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise UpstreamReleaseBindingError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpstreamReleaseBindingError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise UpstreamReleaseBindingError(f"{label} must include timezone authority")
    return text


def _read_release(path: Path) -> tuple[dict[str, Any], str]:
    path = path.expanduser().resolve()
    try:
        info = path.lstat()
    except OSError as exc:
        raise UpstreamReleaseBindingError("BodyRig release receipt is unavailable") from exc
    if path.is_symlink() or not path.is_file():
        raise UpstreamReleaseBindingError("BodyRig release receipt must be a non-symlink regular file")
    if info.st_size <= 0 or info.st_size > _MAX_RECEIPT_BYTES:
        raise UpstreamReleaseBindingError("BodyRig release receipt size is outside the proof boundary")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamReleaseBindingError("BodyRig release receipt is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise UpstreamReleaseBindingError("BodyRig release receipt must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise UpstreamReleaseBindingError(
            f"git {' '.join(args)} failed for {repo_root.name}: {result.stderr.strip()[-300:]}"
        )
    return result.stdout.strip()


def _assert_repo(repo_root: Path, *, expected_sha: str | None, expected_remote_suffix: str, label: str) -> str:
    repo_root = repo_root.expanduser().resolve()
    if repo_root.is_symlink() or not repo_root.is_dir():
        raise UpstreamReleaseBindingError(f"{label} repo root is missing or symlinked")
    top = Path(_git(repo_root, "rev-parse", "--show-toplevel")).resolve()
    if top != repo_root:
        raise UpstreamReleaseBindingError(f"{label} repo root is not the checkout root")
    head = _need_sha40(_git(repo_root, "rev-parse", "HEAD"), f"{label} HEAD")
    if expected_sha is not None and head != expected_sha:
        raise UpstreamReleaseBindingError(f"{label} HEAD differs from receipt authority")
    if _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise UpstreamReleaseBindingError(f"{label} checkout must be fully clean")
    remote = _git(repo_root, "remote", "get-url", "origin").replace("\\", "/").rstrip("/")
    normalized = remote.removesuffix(".git")
    if not normalized.lower().endswith(expected_remote_suffix.lower().removesuffix(".git")):
        raise UpstreamReleaseBindingError(f"{label} origin is not the expected repository")
    return head


def _renderer(value: Any, *, name: str, revision: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UpstreamReleaseBindingError(f"upstream renderer {name} is missing")
    _exact_keys(value, _RENDERER_KEYS, f"upstream renderer {name}")
    if _need_sha40(value.get("bodyrig_revision"), f"{name}.bodyrig_revision") != revision:
        raise UpstreamReleaseBindingError(f"{name} renderer revision mismatch")
    if value.get("machine_quality_pass") is not True:
        raise UpstreamReleaseBindingError(f"{name} machine quality did not PASS")
    if value.get("deformation_sequence_revision") != "humanoid-muscle-sweep-v1":
        raise UpstreamReleaseBindingError(f"{name} deformation sequence authority drifted")
    if value.get("machine_quality_revision") != "skinned-mesh-geometry-v1":
        raise UpstreamReleaseBindingError(f"{name} machine quality authority drifted")
    expected_platform = "WindowsPlayer" if name == "windows_unity_univrm" else "Android"
    if value.get("unity_platform") != expected_platform:
        raise UpstreamReleaseBindingError(f"{name} Unity platform mismatch")
    for field in (
        "probe_report_sha256",
        "deformation_report_sha256",
        "quality_report_sha256",
        "runtime_manifest_sha256",
        "avatar_sha256",
        "bodyprint_sha256",
    ):
        _need_sha256(value.get(field), f"{name}.{field}")
    for field in (
        "renderer_name",
        "renderer_version",
        "unity_version",
        "build_guid",
        "device_model",
        "graphics_device",
    ):
        if not str(value.get(field) or "").strip():
            raise UpstreamReleaseBindingError(f"{name}.{field} is missing")
    for field in ("probe_observed_at", "deformation_observed_at", "quality_observed_at"):
        _need_timestamp(value.get(field), f"{name}.{field}")
    return dict(value)


def validate_release(
    release: Mapping[str, Any],
    *,
    release_sha256: str,
    installed_body_id: str,
    installed_package_sha256: str,
) -> dict[str, Any]:
    """Validate upstream v2 release semantics and return path-free binding data."""
    _exact_keys(release, _TOP_KEYS, "upstream release")
    if release.get("format") != UPSTREAM_FORMAT or release.get("version") != UPSTREAM_VERSION:
        raise UpstreamReleaseBindingError("upstream release format/version mismatch")
    _need_timestamp(release.get("completed_at"), "upstream completed_at")
    revision = _need_sha40(release.get("bodyrig_revision"), "upstream bodyrig_revision")
    if release.get("release_gate_pass") is not True or release.get("production_activation") is not True:
        raise UpstreamReleaseBindingError("upstream release is not the final production PASS receipt")

    automated = release.get("automated_acceptance")
    if not isinstance(automated, Mapping):
        raise UpstreamReleaseBindingError("upstream automated_acceptance is missing")
    _exact_keys(automated, _AUTOMATED_KEYS, "upstream automated_acceptance")
    body_id = _need_body_id(automated.get("body_id"), "upstream body_id")
    package_sha = _need_sha256(automated.get("package_sha256"), "upstream package_sha256")
    if automated.get("automated_pass") is not True:
        raise UpstreamReleaseBindingError("upstream automated acceptance did not PASS")
    if automated.get("physical_clone_mode") != "stash-sith-high-fidelity":
        raise UpstreamReleaseBindingError("upstream physical clone mode is not production high-fidelity")
    if automated.get("skin_qa_assessment") != "low-risk":
        raise UpstreamReleaseBindingError("upstream skin QA is not low-risk")
    for field in (
        "report_sha256",
        "physical_clone_session_sha256",
        "physical_clone_readiness_sha256",
        "skin_qa_report_sha256",
    ):
        _need_sha256(automated.get(field), f"upstream automated_acceptance.{field}")

    if body_id != _need_body_id(installed_body_id, "installed body_id"):
        raise UpstreamReleaseBindingError("upstream body_id differs from installed ModelRig body")
    if package_sha != _need_sha256(installed_package_sha256, "installed package_sha256"):
        raise UpstreamReleaseBindingError("upstream package bytes differ from installed ModelRig body")

    renderers = release.get("renderer_acceptance")
    if not isinstance(renderers, Mapping) or set(renderers) != _RENDERER_NAMES:
        raise UpstreamReleaseBindingError("upstream renderer acceptance must contain exactly Windows + Quest")
    windows = _renderer(renderers["windows_unity_univrm"], name="windows_unity_univrm", revision=revision)
    quest = _renderer(renderers["android_quest_class"], name="android_quest_class", revision=revision)
    for field in (
        "runtime_manifest_sha256",
        "avatar_sha256",
        "bodyprint_sha256",
        "renderer_name",
        "renderer_version",
        "unity_version",
    ):
        if windows[field] != quest[field]:
            raise UpstreamReleaseBindingError(f"cross-platform upstream identity mismatch: {field}")

    return {
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_release_format": UPSTREAM_FORMAT,
        "upstream_release_version": UPSTREAM_VERSION,
        "upstream_release_receipt_sha256": _need_sha256(release_sha256, "release receipt SHA-256"),
        "upstream_completed_at": str(release["completed_at"]),
        "bodyrig_revision": revision,
        "body_id": body_id,
        "package_sha256": package_sha,
        "physical_clone_session_sha256": str(automated["physical_clone_session_sha256"]),
        "physical_clone_readiness_sha256": str(automated["physical_clone_readiness_sha256"]),
        "skin_qa_report_sha256": str(automated["skin_qa_report_sha256"]),
        "runtime_manifest_sha256": str(windows["runtime_manifest_sha256"]),
        "avatar_sha256": str(windows["avatar_sha256"]),
        "bodyprint_sha256": str(windows["bodyprint_sha256"]),
        "windows_probe_report_sha256": str(windows["probe_report_sha256"]),
        "windows_deformation_report_sha256": str(windows["deformation_report_sha256"]),
        "windows_quality_report_sha256": str(windows["quality_report_sha256"]),
        "quest_probe_report_sha256": str(quest["probe_report_sha256"]),
        "quest_deformation_report_sha256": str(quest["deformation_report_sha256"]),
        "quest_quality_report_sha256": str(quest["quality_report_sha256"]),
        "upstream_release_gate_pass": True,
        "upstream_production_activation": True,
    }


def build_binding(
    *,
    release_path: Path,
    store_root: Path,
    bodyrig_repo: Path,
    modelrig_repo: Path = ROOT,
    require_git_state: bool = True,
) -> dict[str, Any]:
    release, release_sha = _read_release(release_path)
    automated = release.get("automated_acceptance")
    if not isinstance(automated, Mapping):
        raise UpstreamReleaseBindingError("upstream automated_acceptance is missing")
    body_id = _need_body_id(automated.get("body_id"), "upstream body_id")

    try:
        stored = MRBodyProfileStore(store_root.expanduser().resolve()).load(body_id)
    except (MRBodyProfileNotFoundError, MRBodyProfileStoreError) as exc:
        raise UpstreamReleaseBindingError(f"installed ModelRig body cannot be validated: {exc}") from exc

    core = validate_release(
        release,
        release_sha256=release_sha,
        installed_body_id=stored.receipt.body_id,
        installed_package_sha256=stored.receipt.package_sha256,
    )
    upstream_revision = str(core["bodyrig_revision"])
    if require_git_state:
        bodyrig_head = _assert_repo(
            bodyrig_repo,
            expected_sha=upstream_revision,
            expected_remote_suffix="Ternedal/BodyRig",
            label="BodyRig",
        )
        modelrig_head = _assert_repo(
            modelrig_repo,
            expected_sha=None,
            expected_remote_suffix="Ternedal/ModelRig",
            label="ModelRig",
        )
        bodyrig_verified = bodyrig_head == upstream_revision
        modelrig_verified = bool(SHA40.fullmatch(modelrig_head))
    else:
        bodyrig_head = upstream_revision
        modelrig_head = "0" * 40
        bodyrig_verified = False
        modelrig_verified = False

    return {
        "schema": BINDING_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "modelrig_candidate_git_sha": modelrig_head,
        "production_activation": False,
        "bodyrig_checkout_verified": bodyrig_verified,
        "modelrig_checkout_verified": modelrig_verified,
        "installed_package_verified": True,
        "upstream": core,
    }


def write_binding(binding: Mapping[str, Any], output: Path) -> None:
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise UpstreamReleaseBindingError("ModelRig upstream binding destination already exists")
    parent = output.parent
    if parent.is_symlink() or not parent.is_dir():
        raise UpstreamReleaseBindingError("ModelRig upstream binding parent must already be a regular directory")
    payload = (json.dumps(dict(binding), ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if output.exists() or output.is_symlink():
            raise UpstreamReleaseBindingError("ModelRig upstream binding destination appeared before commit")
        os.replace(temporary, output)
        temporary = Path()
    finally:
        if str(temporary) not in ("", ".") and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bodyrig-release", required=True, type=Path, help="BodyRig bodyrig-release-acceptance.json")
    parser.add_argument("--bodyrig-repo", required=True, type=Path, help="exact clean Ternedal/BodyRig checkout")
    parser.add_argument("--store", required=True, type=Path, help="ModelRig KALIV_BODY_STORE directory")
    parser.add_argument("--output", required=True, type=Path, help="new ModelRig upstream binding receipt")
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="exact clean ModelRig checkout")
    args = parser.parse_args()
    try:
        binding = build_binding(
            release_path=args.bodyrig_release,
            store_root=args.store,
            bodyrig_repo=args.bodyrig_repo,
            modelrig_repo=args.repo_root,
            require_git_state=True,
        )
        write_binding(binding, args.output)
    except UpstreamReleaseBindingError as exc:
        print(f"MODELRIG BODYRIG UPSTREAM RELEASE BINDING: FAIL | {exc}", file=sys.stderr)
        return 1
    print(
        "MODELRIG BODYRIG UPSTREAM RELEASE BINDING: PASS | "
        f"BodyRig {binding['upstream']['bodyrig_revision']} | "
        f"body {binding['upstream']['body_id']} | production_activation=false"
    )
    print(str(args.output.expanduser().resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
