#!/usr/bin/env python3
"""Adversarial contract for BodyRig M2.6 atomic `.mrbody` profile storage."""
from __future__ import annotations

import binascii
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bodyrig.profile_store as profile_store_module  # noqa: E402
from bodyrig.identity import build_identity_bundle  # noqa: E402
from bodyrig.mrbody import MRBodyError, build_mrbody, validate_mrbody  # noqa: E402
from bodyrig.profile_store import (  # noqa: E402
    MRBodyProfileNotFoundError,
    MRBodyProfileStore,
    MRBodyProfileStoreError,
    MRBodyStoredProfileError,
)
from bodyrig.tracking import COORDINATE_SPACE, SCHEMA as TRACKING_SCHEMA  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def expect_error(fn, expected: tuple[type[BaseException], ...], label: str) -> None:
    try:
        fn()
    except expected:
        check(True, label)
    except Exception as exc:  # pragma: no cover - diagnostic boundary
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, label)
    else:
        check(False, label)


def point(x: float, y: float, z: float = 0.0, confidence: float = 0.9) -> dict:
    return {"x": x, "y": y, "z": z, "confidence": confidence}


def tracking_fixture(source_name: str = "private-profile-store-source.mov") -> dict:
    frames = []
    for index in range(8):
        ts = index * 100_000
        swing = 0.12 if index % 2 == 0 else -0.12
        head = 0.018 if index % 2 == 0 else -0.018
        blink = 0.85 if index in {2, 6} else 0.05
        smile = 0.12 + index * 0.04
        frames.append(
            {
                "timestamp_us": ts,
                "body": {
                    "nose": point(0.5 + head, 0.20),
                    "left_shoulder": point(0.40, 0.36),
                    "right_shoulder": point(0.60, 0.36),
                    "left_elbow": point(0.34 + swing * 0.25, 0.50),
                    "right_elbow": point(0.66 - swing * 0.25, 0.50),
                    "left_wrist": point(0.30 + swing, 0.62),
                    "right_wrist": point(0.70 - swing, 0.62),
                    "left_hip": point(0.44, 0.60),
                    "right_hip": point(0.56, 0.60),
                    "left_knee": point(0.44, 0.77),
                    "right_knee": point(0.56, 0.77),
                    "left_ankle": point(0.43, 0.94),
                    "right_ankle": point(0.57, 0.94),
                },
                "left_hand": {"wrist": point(0.30 + swing, 0.62, confidence=0.82)},
                "right_hand": {"wrist": point(0.70 - swing, 0.62, confidence=0.80)},
                "face": {
                    "nose_tip": point(0.5 + head, 0.20, confidence=0.88),
                    "left_eye_inner": point(0.485 + head, 0.185, confidence=0.86),
                    "right_eye_inner": point(0.515 + head, 0.185, confidence=0.86),
                    "mouth_left": point(0.475 + head, 0.235, confidence=0.84),
                    "mouth_right": point(0.525 + head, 0.235, confidence=0.84),
                },
                "expressions": {
                    "blink_left": blink,
                    "blink_right": max(0.0, blink - 0.03),
                    "jaw_open": 0.10 + index * 0.02,
                    "mouth_smile_left": smile,
                    "mouth_smile_right": max(0.0, smile - 0.02),
                    "mouth_frown_left": 0.03,
                    "mouth_frown_right": 0.04,
                    "brow_inner_up": 0.15 + index * 0.01,
                    "brow_down_left": 0.05,
                    "brow_down_right": 0.06,
                },
            }
        )
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": hashlib.sha256(source_name.encode("utf-8")).hexdigest(),
            "bytes": 24680,
            "permission_assertion": "synthetic local fixture licensed for repository tests",
            "media": {
                "codec": "h264",
                "width": 1280,
                "height": 720,
                "duration_us": 800_000,
                "nominal_fps": 10.0,
            },
        },
        "backend": {
            "id": "profile-store-fixture",
            "version": "1.0.0",
            "model_revision": "profile-store-fixture-r1",
        },
        "frames": frames,
        "coverage": {
            "body": {"observed_frames": 8, "total_frames": 8, "coverage": 1.0, "confidence_frames": 8, "mean_confidence": 0.9},
            "hands": {"observed_frames": 8, "total_frames": 8, "coverage": 1.0, "confidence_frames": 8, "mean_confidence": 0.81},
            "face": {"observed_frames": 8, "total_frames": 8, "coverage": 1.0, "confidence_frames": 8, "mean_confidence": 0.86},
        },
        "recommendations": [],
        "production_activation": False,
    }


def vrm_fixture(marker: str) -> bytes:
    document = {
        "asset": {"version": "2.0", "generator": marker},
        "extensionsUsed": ["VRMC_vrm"],
        "extensions": {"VRMC_vrm": {"specVersion": "1.0"}},
    }
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload)
    return struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(payload), 0x4E4F534A) + payload


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png_fixture() -> bytes:
    raw = b"\x00\x00\x00\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


identity = build_identity_bundle(tracking_fixture())
body_id = identity["id"]
thumbnail = png_fixture()
package_a = build_mrbody(
    identity,
    display_name="../../Display name is never a path",
    avatar_vrm=vrm_fixture("profile-a"),
    thumbnail_png=thumbnail,
    builder_revision="2" * 40,
)
package_b = build_mrbody(
    identity,
    display_name="Replacement display",
    avatar_vrm=vrm_fixture("profile-b"),
    thumbnail_png=thumbnail,
    builder_revision="3" * 40,
)
check(package_a != package_b, "same bodyid can carry distinct validated visual package bytes")
check(validate_mrbody(package_a).body_id == validate_mrbody(package_b).body_id == body_id, "replacement fixtures retain one canonical bodyid")


class InjectedFailure(RuntimeError):
    pass


with tempfile.TemporaryDirectory(prefix="bodyrig-m26-") as temp:
    base = Path(temp)

    invalid_root = base / "invalid-store"
    expect_error(
        lambda: MRBodyProfileStore(invalid_root).install(b"not-a-package"),
        (MRBodyError,),
        "invalid input is rejected before store creation",
    )
    check(not invalid_root.exists(), "invalid pre-validation does not mutate the filesystem store")

    root = base / "profiles"
    store = MRBodyProfileStore(root)
    receipt_a = store.install(package_a, expected_identity_id=body_id)
    final_path = root / f"{body_id}.mrbody"
    check(final_path.read_bytes() == package_a, "first install materializes the exact validated archive")
    check(receipt_a.filename == f"{body_id}.mrbody", "final filename derives only from canonical bodyid")
    check("Display" not in receipt_a.filename and ".." not in receipt_a.filename, "display name cannot influence destination path")
    check(receipt_a.package_sha256 == hashlib.sha256(package_a).hexdigest(), "install receipt binds exact package SHA-256")
    check([item.name for item in root.iterdir()] == [f"{body_id}.mrbody"], "successful install leaves no staging artifact or extracted payload")

    loaded = store.load(body_id)
    check(loaded.archive_bytes == package_a, "load returns exact stored bytes after fresh validation")
    check(loaded.inspection.body_id == body_id and loaded.receipt.package_sha256 == receipt_a.package_sha256, "load receipt remains identity/content bound")

    # Prove install validates twice: once before filesystem mutation and once on
    # the staged sibling immediately before the commit boundary.
    calls = 0
    real_validate = profile_store_module.validate_mrbody

    def counting_validate(*args, **kwargs):
        global calls
        calls += 1
        return real_validate(*args, **kwargs)

    profile_store_module.validate_mrbody = counting_validate
    try:
        store.install(package_a)
    finally:
        profile_store_module.validate_mrbody = real_validate
    check(calls == 2, "install revalidates staged bytes instead of trusting initial validation")

    receipt_b = store.install(package_b)
    check(final_path.read_bytes() == package_b, "same-bodyid valid replacement commits the new exact bytes")
    check(receipt_b.package_sha256 != receipt_a.package_sha256, "replacement receipt exposes changed package content")

    previous = final_path.read_bytes()
    wrong_id = "bodyid-" + ("0" * 24 if body_id != "bodyid-" + "0" * 24 else "1" * 24)
    expect_error(
        lambda: store.install(package_a, expected_identity_id=wrong_id),
        (MRBodyError,),
        "expected-identity mismatch fails before replacement",
    )
    check(final_path.read_bytes() == previous, "expected-identity failure leaves prior valid package byte-identical")

    def fail_after_write(stage: str, _path: Path) -> None:
        if stage == "after_stage_fsync":
            raise InjectedFailure("after stage fsync")

    expect_error(
        lambda: MRBodyProfileStore(root, failure_injector=fail_after_write).install(package_a),
        (InjectedFailure,),
        "injected failure after durable stage write aborts before commit",
    )
    check(final_path.read_bytes() == previous, "failure after stage fsync preserves prior valid profile")
    check(not any(item.suffix == ".tmp" for item in root.iterdir()), "failed staged write cleans temporary sibling")

    def fail_after_revalidation(stage: str, _path: Path) -> None:
        if stage == "after_stage_revalidation":
            raise InjectedFailure("before replace")

    expect_error(
        lambda: MRBodyProfileStore(root, failure_injector=fail_after_revalidation).install(package_a),
        (InjectedFailure,),
        "injected failure after staged revalidation aborts before atomic replace",
    )
    check(final_path.read_bytes() == previous, "last pre-commit failure point preserves prior valid profile")
    check(not any(item.suffix == ".tmp" for item in root.iterdir()), "pre-commit failure leaves no temporary sibling")

    def corrupt_staged_bytes(stage: str, path: Path) -> None:
        if stage == "after_stage_fsync":
            path.write_bytes(b"corrupted-after-initial-validation")

    expect_error(
        lambda: MRBodyProfileStore(root, failure_injector=corrupt_staged_bytes).install(package_a),
        (MRBodyProfileStoreError, MRBodyError),
        "staged-byte mutation is detected before replacement",
    )
    check(final_path.read_bytes() == previous, "staged-byte corruption cannot replace prior valid profile")
    check(not any(item.suffix == ".tmp" for item in root.iterdir()), "corrupted stage file is cleaned")

    final_path.write_bytes(b"tampered-installed-package")
    expect_error(
        lambda: store.load(body_id),
        (MRBodyError,),
        "stored-file tampering is detected on every load",
    )
    final_path.write_bytes(package_b)

    expect_error(
        lambda: store.load("../not-a-bodyid"),
        (MRBodyProfileStoreError,),
        "malformed lookup id is rejected before path construction",
    )
    expect_error(
        lambda: store.load("bodyid-" + "f" * 24),
        (MRBodyProfileNotFoundError,),
        "unknown canonical bodyid reports not installed",
    )

    # A symlink at the canonical final path must never be followed as an
    # installed profile. Keep the test conditional for platforms without
    # unprivileged symlink support.
    symlink_supported = True
    external = base / "external.mrbody"
    external.write_bytes(package_b)
    final_path.unlink()
    try:
        final_path.symlink_to(external)
    except (OSError, NotImplementedError):
        symlink_supported = False
        final_path.write_bytes(package_b)
    if symlink_supported:
        expect_error(
            lambda: store.load(body_id),
            (MRBodyStoredProfileError,),
            "stored-profile symlink is rejected rather than followed",
        )
        final_path.unlink()
        final_path.write_bytes(package_b)
    else:
        check(True, "symlink rejection fixture skipped where symlink creation is unavailable")

    # install_file uses the same bounded-read and atomic install boundary.
    input_path = base / "input.mrbody"
    input_path.write_bytes(package_a)
    file_store_root = base / "file-store"
    file_receipt = MRBodyProfileStore(file_store_root).install_file(input_path, expected_identity_id=body_id)
    check((file_store_root / file_receipt.filename).read_bytes() == package_a, "install_file delegates to exact atomic package install boundary")
    check(all(item.suffix == ".mrbody" for item in file_store_root.iterdir()), "profile store contains archives only, never extracted package files")

    # If the destination is an incompatible filesystem object, os.replace must
    # fail before any visible profile replacement and staging must still clean.
    blocked_root = base / "blocked-store"
    blocked_root.mkdir()
    blocked_destination = blocked_root / f"{body_id}.mrbody"
    blocked_destination.mkdir()
    expect_error(
        lambda: MRBodyProfileStore(blocked_root).install(package_a),
        (MRBodyProfileStoreError,),
        "non-file destination prevents atomic replacement",
    )
    check(blocked_destination.is_dir(), "failed atomic replacement leaves incompatible destination untouched")
    check(not any(item.suffix == ".tmp" for item in blocked_root.iterdir()), "replacement I/O failure cleans temporary sibling")

print(f"\n===== BODYRIG M2.6 PROFILE STORE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
