#!/usr/bin/env python3
"""Dependency-free adversarial contract for BodyRig M2.5 `.mrbody` archives."""
from __future__ import annotations

import binascii
import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
import struct
import sys
import warnings
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.identity import build_identity_bundle  # noqa: E402
from bodyrig.mrbody import (  # noqa: E402
    MRBodyError,
    OPTIONAL_MOTION_PATHS,
    REQUIRED_PATHS,
    build_mrbody,
    validate_mrbody,
    validate_png_bytes,
    validate_vrm1_bytes,
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


def expect_error(fn, label: str) -> None:
    try:
        fn()
    except MRBodyError:
        check(True, label)
    except Exception as exc:  # pragma: no cover - diagnostic boundary
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, label)
    else:
        check(False, label)


def point(x: float, y: float, z: float = 0.0, confidence: float = 0.9) -> dict:
    return {"x": x, "y": y, "z": z, "confidence": confidence}


def tracking_fixture(source_name: str = "mrbody-private-source.mov") -> dict:
    frames = []
    for index in range(8):
        ts = index * 100_000
        swing = 0.12 if index % 2 == 0 else -0.12
        head = 0.018 if index % 2 == 0 else -0.018
        blink = 0.85 if index in {2, 6} else 0.05
        smile = 0.12 + index * 0.04
        body = {
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
        }
        face = {
            "nose_tip": point(0.5 + head, 0.20, confidence=0.88),
            "left_eye_inner": point(0.485 + head, 0.185, confidence=0.86),
            "right_eye_inner": point(0.515 + head, 0.185, confidence=0.86),
            "mouth_left": point(0.475 + head, 0.235, confidence=0.84),
            "mouth_right": point(0.525 + head, 0.235, confidence=0.84),
        }
        expressions = {
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
        }
        frames.append(
            {
                "timestamp_us": ts,
                "body": body,
                "left_hand": {"wrist": point(0.30 + swing, 0.62, confidence=0.82)},
                "right_hand": {"wrist": point(0.70 - swing, 0.62, confidence=0.80)},
                "face": face,
                "expressions": expressions,
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
            "id": "mrbody-fixture",
            "version": "1.0.0",
            "model_revision": "mrbody-fixture-r1",
        },
        "frames": frames,
        "coverage": {
            "body": {
                "observed_frames": 8,
                "total_frames": 8,
                "coverage": 1.0,
                "confidence_frames": 8,
                "mean_confidence": 0.9,
            },
            "hands": {
                "observed_frames": 8,
                "total_frames": 8,
                "coverage": 1.0,
                "confidence_frames": 8,
                "mean_confidence": 0.81,
            },
            "face": {
                "observed_frames": 8,
                "total_frames": 8,
                "coverage": 1.0,
                "confidence_frames": 8,
                "mean_confidence": 0.86,
            },
        },
        "recommendations": [],
        "production_activation": False,
    }


def glb_from_json_text(text: str) -> bytes:
    payload = text.encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload)
    return struct.pack("<4sII", b"glTF", 2, total) + struct.pack(
        "<II", len(payload), 0x4E4F534A
    ) + payload


def vrm_fixture(*, spec_version: str = "1.0", include_vrm: bool = True) -> bytes:
    document: dict[str, object] = {"asset": {"version": "2.0"}}
    if include_vrm:
        document["extensionsUsed"] = ["VRMC_vrm"]
        document["extensions"] = {"VRMC_vrm": {"specVersion": spec_version}}
    return glb_from_json_text(json.dumps(document, separators=(",", ":"), sort_keys=True))


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png_fixture() -> bytes:
    raw = b"\x00\x00\x00\x00\xff"  # filter byte + one RGBA pixel
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def regular_info(path: str, *, compression: int = zipfile.ZIP_STORED) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def package_entries(package: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(package), "r") as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def write_archive(entries: dict[str, bytes], *, compression: int = zipfile.ZIP_STORED) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        for path, data in entries.items():
            archive.writestr(regular_info(path, compression=compression), data)
    return output.getvalue()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def replace_payload(package: bytes, path: str, data: bytes, *, refresh_checksum: bool = True) -> bytes:
    entries = package_entries(package)
    entries[path] = data
    if refresh_checksum and path not in {"manifest.json", "checksums.json"}:
        checksums = json.loads(entries["checksums.json"])
        checksums[path] = hashlib.sha256(data).hexdigest()
        entries["checksums.json"] = canonical_json(checksums)
    return write_archive(entries)


def with_path(package: bytes, path: str, data: bytes = b"x") -> bytes:
    entries = package_entries(package)
    entries[path] = data
    return write_archive(entries)


def duplicate_entry_archive(package: bytes, duplicate_path: str) -> bytes:
    entries = package_entries(package)
    output = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
            for path, data in entries.items():
                archive.writestr(regular_info(path), data)
            archive.writestr(regular_info(duplicate_path), entries[duplicate_path])
    return output.getvalue()


def symlink_archive(package: bytes, path: str) -> bytes:
    entries = package_entries(package)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        for name, data in entries.items():
            info = regular_info(name)
            if name == path:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
    return output.getvalue()


def mark_zip_encrypted(package: bytes) -> bytes:
    data = bytearray(package)
    offset = 0
    patched = 0
    while True:
        offset = data.find(b"PK\x03\x04", offset)
        if offset < 0:
            break
        flags = struct.unpack_from("<H", data, offset + 6)[0]
        struct.pack_into("<H", data, offset + 6, flags | 0x1)
        patched += 1
        offset += 4
    offset = 0
    while True:
        offset = data.find(b"PK\x01\x02", offset)
        if offset < 0:
            break
        flags = struct.unpack_from("<H", data, offset + 8)[0]
        struct.pack_into("<H", data, offset + 8, flags | 0x1)
        patched += 1
        offset += 4
    if patched == 0:
        raise AssertionError("fixture ZIP headers were not found")
    return bytes(data)


source_name = "mrbody-private-source.mov"
tracking = tracking_fixture(source_name)
identity = build_identity_bundle(tracking)
avatar = vrm_fixture()
thumbnail = png_fixture()
validate_vrm1_bytes(avatar)
validate_png_bytes(thumbnail)

package = build_mrbody(
    identity,
    display_name="M2.5 Fixture",
    avatar_vrm=avatar,
    thumbnail_png=thumbnail,
    motions={"motions/idle.vrma": b"deterministic-vrma-fixture"},
    builder_revision="1" * 40,
)
repeat = build_mrbody(
    copy.deepcopy(identity),
    display_name="M2.5 Fixture",
    avatar_vrm=avatar,
    thumbnail_png=thumbnail,
    motions={"motions/idle.vrma": b"deterministic-vrma-fixture"},
    builder_revision="1" * 40,
)
inspection = validate_mrbody(package, expected_identity_id=identity["id"])

check(package == repeat, "same identity/assets produce byte-identical deterministic archive")
check(inspection.body_id == identity["id"], "manifest identity equals the M2.4 bodyid")
check(inspection.identity_content_id == identity["id"], "provenance binds the same M2.4 bodyid")
check(inspection.name == "M2.5 Fixture", "validated display name round-trips")
check("shape" not in inspection.bodyprint, "M1.3 torso ratios are not falsely projected as height ratios")
check(b"mrbody-private-source.mov" not in package, "source filename/path is absent from portable archive bytes")
check(b"permission_assertion" not in package, "source permission assertion is not exported as an identity/rights claim")
check(set(REQUIRED_PATHS).issubset(dict(inspection.payload_sizes)), "all V1 required paths are present")
check("motions/idle.vrma" in inspection.checksums, "optional fixed VRMA path is checksummed as bounded data")

with zipfile.ZipFile(BytesIO(package), "r") as archive:
    infos = archive.infolist()
    expected_order = [*REQUIRED_PATHS, "motions/idle.vrma"]
    check([item.filename for item in infos] == expected_order, "archive entry order is deterministic and spec-aligned")
    check(all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in infos), "archive timestamps are fixed")
    check(all(item.compress_type == zipfile.ZIP_STORED for item in infos), "builder uses deterministic stored ZIP payloads")

changed = build_mrbody(
    identity,
    display_name="M2.5 Fixture",
    avatar_vrm=avatar,
    thumbnail_png=thumbnail,
    motions={"motions/idle.vrma": b"different-vrma-fixture"},
    builder_revision="1" * 40,
)
changed_inspection = validate_mrbody(changed, expected_identity_id=identity["id"])
check(changed != package, "payload mutation changes package bytes")
check(
    changed_inspection.checksums["motions/idle.vrma"] != inspection.checksums["motions/idle.vrma"],
    "payload mutation changes its exact SHA-256 checksum",
)

# Archive/path hardening before any extraction.
expect_error(lambda: validate_mrbody(with_path(package, "../evil")), "traversal path is rejected")
expect_error(lambda: validate_mrbody(with_path(package, "/evil")), "absolute path is rejected")
expect_error(lambda: validate_mrbody(with_path(package, "motions\\evil.vrma")), "backslash path is rejected")
expect_error(lambda: validate_mrbody(with_path(package, "C:/evil")), "Windows drive-style path is rejected")
expect_error(lambda: validate_mrbody(with_path(package, "unexpected.txt")), "unknown package file is rejected")
expect_error(lambda: validate_mrbody(duplicate_entry_archive(package, "avatar.vrm")), "duplicate ZIP entry is rejected")
expect_error(lambda: validate_mrbody(mark_zip_encrypted(package)), "encrypted ZIP flag is rejected before payload read")
expect_error(lambda: validate_mrbody(symlink_archive(package, "thumbnail.png")), "symlink/special ZIP entry is rejected")

entries = package_entries(package)
missing = dict(entries)
missing.pop("thumbnail.png")
expect_error(lambda: validate_mrbody(write_archive(missing)), "missing required V1 file is rejected")

too_large = dict(entries)
too_large["thumbnail.png"] = b"x" * (8 * 1024 * 1024 + 1)
expect_error(lambda: validate_mrbody(write_archive(too_large)), "oversized declared thumbnail is rejected before read")

try:
    bzip2_package = write_archive(entries, compression=zipfile.ZIP_BZIP2)
except RuntimeError:
    print("  SKIP: BZIP2 unavailable in this Python runtime")
else:
    expect_error(lambda: validate_mrbody(bzip2_package), "unsupported ZIP compression is rejected")

# Checksum surface must cover exactly the actual payload set.
tampered = bytearray(entries["avatar.vrm"])
tampered[-1] ^= 0x01
expect_error(
    lambda: validate_mrbody(replace_payload(package, "avatar.vrm", bytes(tampered), refresh_checksum=False)),
    "payload tampering without checksum refresh is rejected",
)
checksums = json.loads(entries["checksums.json"])
checksums.pop("thumbnail.png")
bad_entries = dict(entries)
bad_entries["checksums.json"] = canonical_json(checksums)
expect_error(lambda: validate_mrbody(write_archive(bad_entries)), "missing checksum entry is rejected")
checksums = json.loads(entries["checksums.json"])
checksums["manifest.json"] = "0" * 64
bad_entries = dict(entries)
bad_entries["checksums.json"] = canonical_json(checksums)
expect_error(lambda: validate_mrbody(write_archive(bad_entries)), "extra/unsupported checksum entry is rejected")

# JSON parsers reject malformed, non-canonical/ambiguous surfaces.
expect_error(lambda: validate_mrbody(replace_payload(package, "manifest.json", b"{")), "malformed manifest JSON is rejected")
expect_error(lambda: validate_mrbody(replace_payload(package, "bodyprint.json", b"{")), "malformed bodyprint JSON is rejected")
expect_error(lambda: validate_mrbody(replace_payload(package, "provenance.json", b"{")), "malformed provenance JSON is rejected")
expect_error(lambda: validate_mrbody(replace_payload(package, "checksums.json", b"{", refresh_checksum=False)), "malformed checksums JSON is rejected")
duplicate_bodyprint = b'{"format":"modelrig-bodyprint","format":"modelrig-bodyprint","version":1,"motion":{"energy":0.5}}'
expect_error(
    lambda: validate_mrbody(replace_payload(package, "bodyprint.json", duplicate_bodyprint)),
    "duplicate package JSON keys are rejected fail-closed",
)

# Asset validation is structural only, but it must be strict within that boundary.
expect_error(
    lambda: validate_mrbody(replace_payload(package, "avatar.vrm", b"not-a-glb")),
    "invalid GLB is rejected even with a refreshed checksum",
)
expect_error(
    lambda: validate_mrbody(replace_payload(package, "avatar.vrm", vrm_fixture(include_vrm=False))),
    "glTF 2.0 without VRMC_vrm is rejected",
)
expect_error(
    lambda: validate_mrbody(replace_payload(package, "avatar.vrm", vrm_fixture(spec_version="0.0"))),
    "VRMC_vrm with wrong specVersion is rejected",
)
duplicate_glb_json = glb_from_json_text(
    '{"asset":{"version":"2.0"},"extensionsUsed":["VRMC_vrm"],'
    '"extensions":{"VRMC_vrm":{"specVersion":"0.0","specVersion":"1.0"}}}'
)
expect_error(
    lambda: validate_mrbody(replace_payload(package, "avatar.vrm", duplicate_glb_json)),
    "duplicate GLB JSON keys are rejected instead of accepting last-key-wins ambiguity",
)

bad_png = bytearray(thumbnail)
bad_png[-5] ^= 0x01
expect_error(
    lambda: validate_mrbody(replace_payload(package, "thumbnail.png", bytes(bad_png))),
    "PNG structural/CRC corruption is rejected with refreshed checksum",
)

# Identity/content binding is fail-closed on both build and import.
tampered_identity = copy.deepcopy(identity)
tampered_identity["builder"]["version"] = "0.1.1"
expect_error(
    lambda: build_mrbody(
        tampered_identity,
        display_name="Tampered",
        avatar_vrm=avatar,
        thumbnail_png=thumbnail,
    ),
    "tampered M2.4 identity cannot be packaged",
)
manifest = json.loads(entries["manifest.json"])
manifest["id"] = "bodyid-" + "0" * 24
expect_error(
    lambda: validate_mrbody(replace_payload(package, "manifest.json", canonical_json(manifest))),
    "manifest/provenance bodyid disagreement is rejected",
)
expect_error(
    lambda: validate_mrbody(package, expected_identity_id="bodyid-" + "0" * 24),
    "caller expected-identity mismatch is rejected",
)
expect_error(
    lambda: build_mrbody(
        identity,
        display_name="Bad motion path",
        avatar_vrm=avatar,
        thumbnail_png=thumbnail,
        motions={"motions/custom.vrma": b"x"},
    ),
    "builder accepts only the fixed V1 optional motion paths",
)
check(len(OPTIONAL_MOTION_PATHS) == 6, "V1 optional motion surface remains fixed to six paths")

print(f"\n===== BODYRIG M2.5 MRBODY ARCHIVE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
