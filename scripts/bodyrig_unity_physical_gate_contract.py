#!/usr/bin/env python3
"""Adversarial contract for the BodyRig M0.3 physical Unity evidence gate."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GATE_PATH = ROOT / "scripts" / "bodyrig_unity_physical_gate.py"

spec = importlib.util.spec_from_file_location("bodyrig_unity_physical_gate", GATE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load bodyrig_unity_physical_gate.py")
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def expect_error(fn, label: str) -> None:
    try:
        fn()
    except gate.PhysicalRendererGateError:
        check(True, label)
    except Exception as exc:  # pragma: no cover - diagnostics
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, label)
    else:
        check(False, label)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def glb_fixture() -> bytes:
    document = {
        "asset": {
            "version": "2.0",
            "generator": "bodyrig-physical-gate-contract",
        },
        "extensionsUsed": ["VRMC_vrm"],
        "extensions": {"VRMC_vrm": {"specVersion": "1.0"}},
    }
    payload = canonical(document)
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def write_json(path: Path, value: object) -> bytes:
    raw = canonical(value)
    path.write_bytes(raw)
    return raw


head = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()

loader_source = (
    ROOT
    / "renderers"
    / "bodyrig-unity"
    / "Assets"
    / "BodyRig"
    / "Runtime"
    / "BodyRigVrmLoader.cs"
).read_text(encoding="utf-8")
check(
    all(
        token in loader_source
        for token in (
            "BODYRIG_RUNTIME_RECEIPT",
            "BODYRIG_CANDIDATE_SHA",
            "BODYRIG_AVATAR_SHA256",
            "renderer.IsBound",
            "stream.Flush(true)",
            "File.Move(temporary, receiptPath)",
        )
    ),
    "Unity runtime commits candidate/avatar-bound receipt only after VRM bind",
)

build_source = (
    ROOT
    / "renderers"
    / "bodyrig-unity"
    / "Assets"
    / "BodyRig"
    / "Editor"
    / "BodyRigBuild.cs"
).read_text(encoding="utf-8")
check(
    all(
        token in build_source
        for token in (
            "finally",
            "AssetDatabase.DeleteAsset(ScenePath)",
            "AssetDatabase.DeleteAsset(SceneDirectory)",
        )
    ),
    "generated Unity proof scene/folder is removed even on failed builds",
)

ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
required_ignores = {
    "/renderers/bodyrig-unity/Library/",
    "/renderers/bodyrig-unity/Temp/",
    "/renderers/bodyrig-unity/Obj/",
    "/renderers/bodyrig-unity/Logs/",
    "/renderers/bodyrig-unity/UserSettings/",
    "/renderers/bodyrig-unity/Build/",
}
check(
    required_ignores.issubset(set(ignore_text.splitlines()))
    and "packages-lock.json" not in ignore_text,
    "only Unity cache/build state is ignored while dependency lock remains visible",
)

with tempfile.TemporaryDirectory(prefix="bodyrig-unity-physical-contract-") as temporary:
    base = Path(temporary)
    evidence = base / "evidence"
    evidence.mkdir()
    stage = base / "renderer-stage"
    stage.mkdir()

    avatar = glb_fixture()
    avatar_path = stage / "bodyid-aaaaaaaaaaaaaaaaaaaaaaaa.avatar.vrm"
    avatar_path.write_bytes(avatar)
    exe_path = evidence / "BodyRigRendererProof.exe"
    exe_path.write_bytes(b"synthetic-unity-build-executable")
    log_path = evidence / "unity-build.log"
    log_path.write_bytes(b"synthetic Unity build log\nBuild succeeded\n")
    runtime_path = evidence / "runtime-receipt.json"

    body_id = "bodyid-aaaaaaaaaaaaaaaaaaaaaaaa"
    package_sha = "b" * 64
    avatar_sha = sha(avatar)
    exe_sha = sha(exe_path.read_bytes())
    log_sha = sha(log_path.read_bytes())

    runtime = {
        "schema": gate.RUNTIME_SCHEMA,
        "created_at": "2026-08-24T06:05:00Z",
        "production_activation": False,
        "visual_acceptance": False,
        "vrm_loaded": True,
        "renderer_bound": True,
        "candidate_git_sha": head,
        "body_id": body_id,
        "package_sha256": package_sha,
        "avatar_sha256": avatar_sha,
        "unity_version": "6000.3.21f1",
        "vrm_path": str(avatar_path.resolve()),
    }
    runtime_raw = write_json(runtime_path, runtime)
    runtime_sha = sha(runtime_raw)

    build = {
        "schema": gate.BUILD_SCHEMA,
        "created_at": "2026-08-24T06:06:00Z",
        "production_activation": False,
        "visual_acceptance": False,
        "pr_number": 720,
        "candidate": {
            "git_sha": head,
            "branch": "agent/bodyrig-unity-renderer",
            "origin_main_sha": "c" * 40,
            "origin_main_stable_during_build": True,
            "origin_main_stable_through_runtime": True,
            "clean_checkout_before_build": True,
            "working_tree_clean_after_runtime": True,
        },
        "profile": {
            "body_id": body_id,
            "package_sha256": package_sha,
            "avatar_sha256": avatar_sha,
            "vrm_path": str(avatar_path.resolve()),
        },
        "renderer": {
            "unity_project_version": gate.EXPECTED_UNITY,
            "unity_exe": (
                r"C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe"
            ),
            "unity_product_version": "6000.3.21f1",
            "univrm_gltf": gate.EXPECTED_DEPS["com.vrmc.gltf"],
            "univrm_vrm": gate.EXPECTED_DEPS["com.vrmc.vrm"],
        },
        "build": {
            "success": True,
            "exit_code": 0,
            "launched": True,
            "runtime_load_verified": True,
        },
        "artifacts": {
            "executable": {
                "path": str(exe_path.resolve()),
                "bytes": exe_path.stat().st_size,
                "sha256": exe_sha,
            },
            "unity_log": {
                "path": str(log_path.resolve()),
                "bytes": log_path.stat().st_size,
                "sha256": log_sha,
            },
            "runtime_receipt": {
                "path": str(runtime_path.resolve()),
                "bytes": runtime_path.stat().st_size,
                "sha256": runtime_sha,
            },
        },
    }
    build_raw = write_json(evidence / "build-receipt.json", build)

    visual = {
        "schema": gate.VISUAL_SCHEMA,
        "accepted_at": "2026-08-24T06:10:00Z",
        "production_activation": False,
        "visual_acceptance": True,
        "pr_number": 720,
        "candidate_git_sha": head,
        "build_receipt_sha256": sha(build_raw),
        "runtime_receipt_sha256": runtime_sha,
        "profile": {
            "body_id": body_id,
            "package_sha256": package_sha,
            "avatar_sha256": avatar_sha,
        },
        "executable_sha256": exe_sha,
        "checks": {key: True for key in gate.EXPECTED_VISUAL_CHECKS},
        "operator": {
            "user": "contract-user",
            "machine": "contract-rig",
            "attestation": (
                "directly observed on the physical Windows renderer rig"
            ),
        },
    }
    write_json(evidence / "visual-receipt.json", visual)

    result = gate.validate_evidence(
        evidence_dir=evidence,
        expected_sha=head,
        repo_root=ROOT,
        require_git_state=True,
    )
    check(
        result["status"] == "pass"
        and result["candidate_git_sha"] == head
        and result["runtime_vrm_loaded"] is True
        and result["runtime_renderer_bound"] is True
        and result["visual_acceptance"] is True
        and result["production_activation"] is False,
        "complete build + runtime load/bind + visual evidence passes",
    )

    original_exe = exe_path.read_bytes()
    exe_path.write_bytes(b"tampered executable")
    expect_error(
        lambda: gate.validate_evidence(
            evidence_dir=evidence,
            expected_sha=head,
            repo_root=ROOT,
            require_git_state=True,
        ),
        "post-build executable tampering fails closed",
    )
    exe_path.write_bytes(original_exe)

    original_runtime = runtime_path.read_bytes()
    runtime_bad = json.loads(original_runtime.decode("utf-8"))
    runtime_bad["renderer_bound"] = False
    write_json(runtime_path, runtime_bad)
    expect_error(
        lambda: gate.validate_evidence(
            evidence_dir=evidence,
            expected_sha=head,
            repo_root=ROOT,
            require_git_state=True,
        ),
        "tampered or non-bound runtime receipt fails closed",
    )
    runtime_path.write_bytes(original_runtime)

    visual_bad = json.loads(json.dumps(visual))
    visual_bad["checks"]["states_distinct"] = False
    write_json(evidence / "visual-receipt.json", visual_bad)
    expect_error(
        lambda: gate.validate_evidence(
            evidence_dir=evidence,
            expected_sha=head,
            repo_root=ROOT,
            require_git_state=True,
        ),
        "partial visual acceptance cannot pass",
    )

    visual_bad = json.loads(json.dumps(visual))
    visual_bad["production_activation"] = True
    write_json(evidence / "visual-receipt.json", visual_bad)
    expect_error(
        lambda: gate.validate_evidence(
            evidence_dir=evidence,
            expected_sha=head,
            repo_root=ROOT,
            require_git_state=True,
        ),
        "production activation in physical evidence fails closed",
    )

    write_json(evidence / "visual-receipt.json", visual)
    build_changed = json.loads(json.dumps(build))
    build_changed["renderer"]["unity_product_version"] = "6000.3.22f1"
    write_json(evidence / "build-receipt.json", build_changed)
    expect_error(
        lambda: gate.validate_evidence(
            evidence_dir=evidence,
            expected_sha=head,
            repo_root=ROOT,
            require_git_state=True,
        ),
        "visual receipt cannot be replayed against changed build receipt bytes",
    )

    write_json(evidence / "build-receipt.json", build)
    write_json(evidence / "visual-receipt.json", visual)
    expect_error(
        lambda: gate.validate_evidence(
            evidence_dir=evidence,
            expected_sha="d" * 40,
            repo_root=ROOT,
            require_git_state=True,
        ),
        "stale/wrong expected draft SHA fails closed",
    )

    if hasattr(os, "symlink"):
        original_log_bytes = log_path.read_bytes()
        real_log = evidence / "real-unity-build.log"
        real_log.write_bytes(original_log_bytes)
        log_path.unlink()
        os.symlink(real_log, log_path)
        build_for_symlink = json.loads(json.dumps(build))
        build_for_symlink["artifacts"]["unity_log"] = {
            "path": str(log_path.absolute()),
            "bytes": len(original_log_bytes),
            "sha256": sha(original_log_bytes),
        }
        symlink_build_raw = write_json(
            evidence / "build-receipt.json", build_for_symlink
        )
        visual_for_symlink = json.loads(json.dumps(visual))
        visual_for_symlink["build_receipt_sha256"] = sha(symlink_build_raw)
        write_json(evidence / "visual-receipt.json", visual_for_symlink)
        expect_error(
            lambda: gate.validate_evidence(
                evidence_dir=evidence,
                expected_sha=head,
                repo_root=ROOT,
                require_git_state=True,
            ),
            "symlinked physical build artifact is rejected rather than followed",
        )

print(
    f"\n===== BODYRIG UNITY PHYSICAL GATE CONTRACT: "
    f"{passed} passed, {failed} failed ====="
)
if failed:
    raise SystemExit(1)
