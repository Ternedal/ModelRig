#!/usr/bin/env python3
"""Adversarial M2.9 contract for cross-repo `.mrbody` identity authorities."""
from __future__ import annotations

import binascii
import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
import struct
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.mrbody import MRBodyError, validate_mrbody  # noqa: E402
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402

passed = failed = 0
BODY_ID = "bodyid-1234567890abcdef12345678"
REVISION = BODY_ID.removeprefix("bodyid-")


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
    except Exception:
        check(True, label)
    else:
        check(False, label)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def glb(document: dict) -> bytes:
    payload = canonical(document)
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def vrm() -> bytes:
    return glb(
        {
            "asset": {"version": "2.0"},
            "extensionsUsed": ["VRMC_vrm"],
            "extensions": {"VRMC_vrm": {"specVersion": "1.0"}},
        }
    )


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png() -> bytes:
    raw = b"\x00\x00\x00\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def package(
    *,
    authority: str = "bodyrig.portable_identity",
    revision: str = REVISION,
    manifest_id: str = BODY_ID,
    extra_identity_stage: dict[str, str] | None = None,
) -> bytes:
    pipeline = [
        {"stage": "body-recovery", "adapter": "hmr2-4dhumans", "revision": "fixture-r1"},
        {"stage": "identity_content", "adapter": authority, "revision": revision},
        {"stage": "avatar-fitting", "adapter": "sith-smplx-vrm", "revision": "1"},
    ]
    if extra_identity_stage is not None:
        pipeline.insert(2, extra_identity_stage)
    provenance = {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": "2026-08-24T07:00:00Z",
        "source": {"kind": "user-supplied-local-media", "count": 2},
        "synthetic_avatar": True,
        "pipeline": pipeline,
    }
    bodyprint = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "shape": {
            "shoulder_to_height": 0.24,
            "hip_to_height": 0.19,
            "arm_to_height": 0.44,
            "leg_to_height": 0.53,
        },
        "motion": {"energy": 0.42, "head_motion": 0.21},
    }
    payloads = {
        "avatar.vrm": vrm(),
        "bodyprint.json": canonical(bodyprint),
        "provenance.json": canonical(provenance),
        "thumbnail.png": png(),
    }
    checksums = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    manifest = {
        "format": "modelrig-body",
        "format_version": 1,
        "id": manifest_id,
        "name": "Upstream portable identity fixture",
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": "0.1.0"},
    }
    entries = {
        "manifest.json": canonical(manifest),
        "checksums.json": canonical(checksums),
        **payloads,
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        for name in (
            "manifest.json",
            "checksums.json",
            "avatar.vrm",
            "bodyprint.json",
            "provenance.json",
            "thumbnail.png",
        ):
            archive.writestr(zip_info(name), entries[name])
    return output.getvalue()


portable = package()
inspection = validate_mrbody(portable, expected_identity_id=BODY_ID)
check(inspection.body_id == BODY_ID, "upstream portable authority validates canonical manifest bodyid")
check(inspection.identity_content_id == BODY_ID, "upstream portable authority binds the expected identity")

with tempfile.TemporaryDirectory(prefix="bodyrig-m29-") as temp:
    store = MRBodyProfileStore(Path(temp) / "profiles")
    receipt = store.install(portable)
    check(receipt.body_id == BODY_ID, "M2.6 staged install accepts upstream portable authority")
    loaded = store.load(BODY_ID)
    check(loaded.archive_bytes == portable, "fresh M2.6 load revalidates and returns exact upstream bytes")
    check(loaded.inspection.identity_content_id == BODY_ID, "fresh stored-profile validation preserves portable identity binding")

legacy = package(authority="modelrig.bodyrig.identity_bundle")
legacy_inspection = validate_mrbody(legacy, expected_identity_id=BODY_ID)
check(legacy_inspection.identity_content_id == BODY_ID, "existing ModelRig identity authority remains valid")

unknown = package(authority="bodyrig.untrusted_identity")
unknown_inspection = validate_mrbody(unknown)
check(unknown_inspection.identity_content_id is None, "unknown identity authority is not treated as canonical binding")
expect_error(
    lambda: validate_mrbody(unknown, expected_identity_id=BODY_ID),
    "unknown identity authority cannot satisfy expected identity",
)
with tempfile.TemporaryDirectory(prefix="bodyrig-m29-unknown-") as temp:
    expect_error(
        lambda: MRBodyProfileStore(Path(temp) / "profiles").install(unknown),
        "M2.6 staged revalidation rejects unknown identity authority",
    )

expect_error(
    lambda: validate_mrbody(
        package(
            extra_identity_stage={
                "stage": "identity_content",
                "adapter": "bodyrig.untrusted_identity",
                "revision": REVISION,
            }
        )
    ),
    "multiple identity_content stages are rejected as ambiguous even if one authority is unknown",
)
expect_error(
    lambda: validate_mrbody(package(revision="A" * 24), expected_identity_id=BODY_ID),
    "recognized authority requires exact 24 lowercase hex revision",
)
expect_error(
    lambda: validate_mrbody(
        package(manifest_id="bodyid-ffffffffffffffffffffffff"),
        expected_identity_id=BODY_ID,
    ),
    "manifest identity cannot disagree with provenance authority",
)

print(f"\nBodyRig M2.9 portable identity authority contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
