#!/usr/bin/env python3
"""Adversarial contract for BodyRig M2.7 current-profile selection/runtime binding."""
from __future__ import annotations

import binascii
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.mrbody import REQUIRED_PATHS, validate_mrbody  # noqa: E402
from bodyrig.profile_selection import (  # noqa: E402
    CURRENT_PROFILE_FORMAT,
    MRBodyCurrentProfileError,
    MRBodyCurrentProfileNotSelectedError,
    MRBodyCurrentProfileStaleError,
    MRBodyCurrentProfileStore,
)
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def expect_error(fn, exc_type, label: str) -> None:
    try:
        fn()
    except exc_type:
        check(True, label)
    except Exception as exc:  # pragma: no cover - diagnostics
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, label)
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


def glb_fixture() -> bytes:
    document = {
        "asset": {"version": "2.0"},
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


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind)
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png_fixture(seed: int) -> bytes:
    rgba = bytes((seed & 0xFF, (seed * 3) & 0xFF, (seed * 7) & 0xFF, 255))
    raw = b"\x00" + rgba
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def regular_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    return info


def package_fixture(body_id: str, *, name: str, seed: int) -> tuple[bytes, dict[str, bytes]]:
    suffix = body_id.removeprefix("bodyid-")
    avatar = glb_fixture()
    bodyprint = canonical(
        {
            "format": "modelrig-bodyprint",
            "version": 1,
            "motion": {
                "energy": round(0.2 + (seed % 5) * 0.1, 3),
                "gesture_frequency": round(0.3 + (seed % 4) * 0.1, 3),
            },
            "expression": {"blink_rate_per_min": float(10 + seed)},
        }
    )
    provenance = canonical(
        {
            "format": "modelrig-body-provenance",
            "version": 1,
            "created_at": "2026-08-24T00:00:00Z",
            "source": {"kind": "user-supplied-local-media", "count": 1},
            "synthetic_avatar": True,
            "pipeline": [
                {
                    "stage": "identity_content",
                    "adapter": "modelrig.bodyrig.identity_bundle",
                    "revision": suffix,
                },
                {"stage": "mrbody_builder", "adapter": "bodyrig", "revision": "0.1.0"},
            ],
        }
    )
    thumbnail = png_fixture(seed)
    motion = f"vrma-data-{seed}".encode("ascii")
    payloads = {
        "avatar.vrm": avatar,
        "bodyprint.json": bodyprint,
        "provenance.json": provenance,
        "thumbnail.png": thumbnail,
        "motions/idle.vrma": motion,
    }
    checksums = canonical(
        {path: hashlib.sha256(data).hexdigest() for path, data in payloads.items()}
    )
    manifest = canonical(
        {
            "format": "modelrig-body",
            "format_version": 1,
            "id": body_id,
            "name": name,
            "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
            "bodyprint": "bodyprint.json",
            "provenance": "provenance.json",
            "thumbnail": "thumbnail.png",
            "builder": {"name": "bodyrig", "version": "0.1.0"},
        }
    )
    entries = {
        "manifest.json": manifest,
        "checksums.json": checksums,
        **payloads,
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        order = [*REQUIRED_PATHS, "motions/idle.vrma"]
        for path in order:
            archive.writestr(regular_info(path), entries[path])
    package = output.getvalue()
    validate_mrbody(package, expected_identity_id=body_id)
    return package, payloads


def temp_siblings(marker_path: Path) -> list[Path]:
    return list(marker_path.parent.glob(f".{marker_path.name}.*.tmp"))


body_a = "bodyid-111111111111111111111111"
body_b = "bodyid-222222222222222222222222"
package_a1, payloads_a1 = package_fixture(body_a, name="Current A / harmless name", seed=1)
package_a2, payloads_a2 = package_fixture(body_a, name="Current A replacement", seed=2)
package_b, payloads_b = package_fixture(body_b, name="Current B", seed=3)

with tempfile.TemporaryDirectory(prefix="bodyrig-m27-") as temporary:
    base = Path(temporary)
    root = base / "profiles"
    store = MRBodyProfileStore(root)
    current = MRBodyCurrentProfileStore(store)

    expect_error(
        current.load_current,
        MRBodyCurrentProfileNotSelectedError,
        "missing current marker fails closed",
    )

    receipt_a1 = store.install(package_a1, expected_identity_id=body_a)
    store.install(package_b, expected_identity_id=body_b)
    marker_a = current.select(body_a)
    marker_bytes_a = current.marker_path.read_bytes()

    check(marker_a.body_id == body_a, "selection binds canonical bodyid")
    check(marker_a.package_sha256 == receipt_a1.package_sha256, "selection pins exact package SHA-256")
    check(current.marker_path == base / ".profiles.current-profile.json", "marker uses fixed sibling state path")
    check(current.marker_path.parent == root.parent, "marker remains outside archive-only store")
    check(all(path.suffix == ".mrbody" for path in root.iterdir()), "M2.6 store remains archive-only")
    check(b"Current A / harmless name" not in str(current.marker_path).encode(), "display name cannot influence marker path")

    parsed_marker = json.loads(marker_bytes_a)
    check(parsed_marker["format"] == CURRENT_PROFILE_FORMAT, "marker format is explicit")
    check(marker_bytes_a == canonical(parsed_marker), "marker bytes are canonical deterministic JSON")

    resolved_a = current.load_current()
    check(resolved_a.stored.archive_bytes == package_a1, "current load returns exact freshly validated selected archive")
    binding_a = current.bind_current_runtime()
    check(binding_a.body_id == body_a and binding_a.package_sha256 == marker_a.package_sha256, "runtime binding remains bodyid/digest bound")
    check(binding_a.avatar_vrm == payloads_a1["avatar.vrm"], "runtime binding exposes exact validated VRM bytes in memory")
    check(binding_a.bodyprint_json == payloads_a1["bodyprint.json"], "runtime binding exposes exact portable bodyprint JSON bytes")
    check(binding_a.thumbnail_png == payloads_a1["thumbnail.png"], "runtime binding exposes exact validated thumbnail bytes")
    check(binding_a.motions == (("motions/idle.vrma", payloads_a1["motions/idle.vrma"]),), "runtime binding preserves fixed data-only motion path/bytes")
    check(not list(root.rglob("avatar.vrm")) and not list(root.rglob("*.vrma")), "runtime binding never extracts archive payloads to filesystem")

    current.select(body_a)
    check(current.marker_path.read_bytes() == marker_bytes_a, "re-selecting unchanged package is byte-deterministic")

    store.install(package_a2, expected_identity_id=body_a)
    expect_error(
        current.load_current,
        MRBodyCurrentProfileStaleError,
        "same-bodyid replacement cannot silently change current runtime body",
    )
    marker_a2 = current.select(body_a)
    check(marker_a2.package_sha256 != marker_a.package_sha256, "explicit re-selection adopts replacement digest")
    check(current.bind_current_runtime().thumbnail_png == payloads_a2["thumbnail.png"], "re-selection binds replacement payloads only after explicit commit")

    current.select(body_b)
    prior_marker = current.marker_path.read_bytes()

    def fail_after_fsync(stage: str, path: Path) -> None:
        if stage == "after_marker_fsync":
            raise RuntimeError("injected after marker fsync")

    failing = MRBodyCurrentProfileStore(store, failure_injector=fail_after_fsync)
    expect_error(lambda: failing.select(body_a), RuntimeError, "injected failure after marker fsync aborts selection")
    check(current.marker_path.read_bytes() == prior_marker, "failure after marker fsync preserves previous marker byte-for-byte")
    check(not temp_siblings(current.marker_path), "failure after marker fsync cleans temporary sibling")

    def fail_after_revalidation(stage: str, path: Path) -> None:
        if stage == "after_marker_revalidation":
            raise RuntimeError("injected before marker replace")

    failing = MRBodyCurrentProfileStore(store, failure_injector=fail_after_revalidation)
    expect_error(lambda: failing.select(body_a), RuntimeError, "last pre-commit failure point aborts selection")
    check(current.marker_path.read_bytes() == prior_marker, "last pre-commit failure preserves previous marker")
    check(not temp_siblings(current.marker_path), "last pre-commit failure cleans temporary sibling")

    def corrupt_stage(stage: str, path: Path) -> None:
        if stage == "after_marker_fsync":
            path.write_bytes(b"{}")

    corrupting = MRBodyCurrentProfileStore(store, failure_injector=corrupt_stage)
    expect_error(lambda: corrupting.select(body_a), MRBodyCurrentProfileError, "staged marker corruption is detected before commit")
    check(current.marker_path.read_bytes() == prior_marker, "staged marker corruption cannot replace previous selection")
    check(not temp_siblings(current.marker_path), "corrupted marker staging file is cleaned")

    current.select(body_b)
    good_marker = current.marker_path.read_bytes()
    current.marker_path.write_bytes(good_marker + b"\n")
    expect_error(current.load_current, MRBodyCurrentProfileError, "non-canonical marker whitespace fails closed")
    current.select(body_b)

    duplicate = (
        b'{"body_id":"' + body_b.encode() + b'","body_id":"' + body_b.encode()
        + b'","format":"bodyrig.current_profile","package_sha256":"'
        + hashlib.sha256(package_b).hexdigest().encode()
        + b'","version":1}'
    )
    current.marker_path.write_bytes(duplicate)
    expect_error(current.load_current, MRBodyCurrentProfileError, "duplicate marker JSON keys fail closed")
    current.select(body_b)

    marker_value = json.loads(current.marker_path.read_bytes())
    marker_value["package_sha256"] = "0" * 64
    current.marker_path.write_bytes(canonical(marker_value))
    expect_error(current.load_current, MRBodyCurrentProfileStaleError, "canonical marker digest tampering is detected against installed package")
    current.select(body_b)

    marker_value = json.loads(current.marker_path.read_bytes())
    marker_value["body_id"] = "bodyid-333333333333333333333333"
    current.marker_path.write_bytes(canonical(marker_value))
    expect_error(current.load_current, MRBodyCurrentProfileStaleError, "marker pointing to missing installed body fails stale/closed")
    current.select(body_b)

    if hasattr(os, "symlink"):
        target = base / "marker-target.json"
        target.write_bytes(current.marker_path.read_bytes())
        current.marker_path.unlink()
        os.symlink(target, current.marker_path)
        expect_error(current.load_current, MRBodyCurrentProfileError, "symlink current marker is rejected rather than followed")
        current.marker_path.unlink()
        current.select(body_b)

    before_invalid = current.marker_path.read_bytes()
    expect_error(lambda: current.select("../bodyid-evil"), MRBodyCurrentProfileError, "invalid selection id fails before marker mutation")
    check(current.marker_path.read_bytes() == before_invalid, "invalid selection preserves previous valid marker")

print(f"\n===== BODYRIG M2.7 CURRENT PROFILE: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
