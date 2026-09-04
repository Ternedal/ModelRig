#!/usr/bin/env python3
"""Adversarial software contract for BodyRig M2.8 renderer asset handoff."""
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
from bodyrig.profile_selection import MRBodyCurrentProfileStore  # noqa: E402
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402
from bodyrig.renderer_handoff import (  # noqa: E402
    MRBodyRendererHandoff,
    RENDERER_PROFILE_FORMAT,
    RendererHandoffError,
)

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


def glb_fixture(seed: int) -> bytes:
    document = {
        "asset": {"version": "2.0", "generator": f"bodyrig-m28-{seed}"},
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


def package_fixture(
    body_id: str,
    *,
    name: str,
    seed: int,
) -> tuple[bytes, dict[str, bytes]]:
    suffix = body_id.removeprefix("bodyid-")
    avatar = glb_fixture(seed)
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
                {
                    "stage": "mrbody_builder",
                    "adapter": "bodyrig",
                    "revision": "0.1.0",
                },
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
        for path in [*REQUIRED_PATHS, "motions/idle.vrma"]:
            archive.writestr(regular_info(path), entries[path])
    package = output.getvalue()
    validate_mrbody(package, expected_identity_id=body_id)
    return package, payloads


def stage_temps(root: Path) -> list[Path]:
    if not root.exists() or root.is_symlink() or not root.is_dir():
        return []
    return list(root.glob("*.tmp")) + list(root.glob(".*.tmp"))


body_id = "bodyid-444444444444444444444444"
packages = [
    package_fixture(body_id, name="Renderer / harmless display name", seed=seed)
    for seed in range(1, 8)
]

with tempfile.TemporaryDirectory(prefix="bodyrig-m28-") as temporary:
    base = Path(temporary)
    store_root = base / "profiles"
    store = MRBodyProfileStore(store_root)
    current = MRBodyCurrentProfileStore(store)
    handoff_store = MRBodyRendererHandoff(store)

    expect_error(
        handoff_store.prepare_current,
        RendererHandoffError,
        "missing current selection fails before renderer staging",
    )
    check(
        not handoff_store.staging_root.exists(),
        "failed pre-validation does not create renderer staging root",
    )

    package1, payloads1 = packages[0]
    receipt1 = store.install(package1, expected_identity_id=body_id)
    current.select(body_id)
    prepared1 = handoff_store.prepare_current()
    expected_name1 = f"{body_id}.{receipt1.package_sha256}.avatar.vrm"

    check(
        prepared1.vrm_path == base / ".profiles.renderer-assets" / expected_name1,
        "renderer avatar path derives only from canonical bodyid and package digest",
    )
    check(
        prepared1.vrm_path.read_bytes() == payloads1["avatar.vrm"],
        "renderer stage contains exact validated avatar.vrm bytes",
    )
    check(
        prepared1.descriptor.avatar_sha256
        == hashlib.sha256(payloads1["avatar.vrm"]).hexdigest(),
        "renderer descriptor binds exact avatar SHA-256",
    )
    descriptor_mapping = json.loads(prepared1.descriptor.canonical_json())
    check(
        descriptor_mapping["format"] == RENDERER_PROFILE_FORMAT,
        "renderer descriptor format is explicit",
    )
    check(
        prepared1.descriptor.canonical_json().encode("utf-8")
        == canonical(descriptor_mapping),
        "renderer descriptor is canonical deterministic JSON",
    )
    check(
        "Renderer / harmless display name" not in prepared1.descriptor.canonical_json(),
        "display name cannot influence renderer descriptor or path",
    )
    check(
        all(path.suffix == ".mrbody" for path in store_root.iterdir()),
        "M2.6 profile store remains archive-only after renderer preparation",
    )
    staged_names = {path.name for path in handoff_store.staging_root.iterdir()}
    check(
        staged_names == {expected_name1},
        "renderer staging extracts only avatar.vrm and no bodyprint/thumbnail/motion payload",
    )
    check(
        not list(handoff_store.staging_root.rglob("*.vrma"))
        and not list(handoff_store.staging_root.rglob("*.json")),
        "renderer staging contains no motion or JSON archive payloads",
    )

    prepared1_again = handoff_store.prepare_current()
    check(
        prepared1_again == prepared1,
        "preparing unchanged selected package is idempotent and path-stable",
    )

    package2, payloads2 = packages[1]
    receipt2 = store.install(package2, expected_identity_id=body_id)
    expected_name2 = f"{body_id}.{receipt2.package_sha256}.avatar.vrm"
    expect_error(
        handoff_store.prepare_current,
        RendererHandoffError,
        "same-bodyid package replacement remains stale for renderer handoff",
    )
    check(
        not (handoff_store.staging_root / expected_name2).exists(),
        "stale package replacement cannot materialize a new renderer avatar",
    )
    check(
        prepared1.vrm_path.read_bytes() == payloads1["avatar.vrm"],
        "stale replacement cannot mutate prior digest-bound renderer avatar",
    )

    current.select(body_id)
    prepared2 = handoff_store.prepare_current()
    check(
        prepared2.descriptor.package_sha256 == receipt2.package_sha256
        and prepared2.vrm_path.name == expected_name2,
        "explicit re-selection adopts replacement package digest into a distinct path",
    )
    check(
        prepared2.descriptor.avatar_sha256 != prepared1.descriptor.avatar_sha256
        and prepared2.vrm_path.read_bytes() == payloads2["avatar.vrm"],
        "explicit re-selection can stage changed validated avatar bytes without rewriting old path",
    )
    check(
        prepared1.vrm_path.read_bytes() == payloads1["avatar.vrm"],
        "prior content-addressed renderer avatar remains immutable after re-selection",
    )

    package3, _payloads3 = packages[2]
    receipt3 = store.install(package3, expected_identity_id=body_id)
    current.select(body_id)
    expected3 = handoff_store.staging_root / f"{body_id}.{receipt3.package_sha256}.avatar.vrm"

    def fail_after_fsync(stage: str, path: Path) -> None:
        if stage == "after_avatar_fsync":
            raise RuntimeError("injected after avatar fsync")

    failing = MRBodyRendererHandoff(store, failure_injector=fail_after_fsync)
    expect_error(
        failing.prepare_current,
        RuntimeError,
        "injected failure after avatar fsync aborts before visible commit",
    )
    check(not expected3.exists(), "failure after fsync leaves new final avatar absent")
    check(prepared2.vrm_path.exists(), "failure after fsync preserves prior renderer avatar")
    check(not stage_temps(failing.staging_root), "failure after fsync cleans renderer temp sibling")

    package4, _payloads4 = packages[3]
    receipt4 = store.install(package4, expected_identity_id=body_id)
    current.select(body_id)
    expected4 = handoff_store.staging_root / f"{body_id}.{receipt4.package_sha256}.avatar.vrm"

    def fail_after_revalidation(stage: str, path: Path) -> None:
        if stage == "after_avatar_revalidation":
            raise RuntimeError("injected before avatar replace")

    failing = MRBodyRendererHandoff(store, failure_injector=fail_after_revalidation)
    expect_error(
        failing.prepare_current,
        RuntimeError,
        "last pre-commit failure point aborts renderer handoff",
    )
    check(not expected4.exists(), "last pre-commit failure leaves final avatar absent")
    check(prepared2.vrm_path.exists(), "last pre-commit failure preserves prior renderer avatar")
    check(not stage_temps(failing.staging_root), "last pre-commit failure cleans renderer temp sibling")

    package5, _payloads5 = packages[4]
    receipt5 = store.install(package5, expected_identity_id=body_id)
    current.select(body_id)
    expected5 = handoff_store.staging_root / f"{body_id}.{receipt5.package_sha256}.avatar.vrm"

    def corrupt_stage(stage: str, path: Path) -> None:
        if stage == "after_avatar_fsync":
            path.write_bytes(b"corrupt-staged-vrm")

    corrupting = MRBodyRendererHandoff(store, failure_injector=corrupt_stage)
    expect_error(
        corrupting.prepare_current,
        RendererHandoffError,
        "staged renderer avatar corruption is detected before commit",
    )
    check(not expected5.exists(), "corrupt staged avatar cannot become renderer-visible")
    check(not stage_temps(corrupting.staging_root), "corrupt renderer stage is cleaned")

    package6, _payloads6 = packages[5]
    receipt6 = store.install(package6, expected_identity_id=body_id)
    current.select(body_id)
    expected6 = handoff_store.staging_root / f"{body_id}.{receipt6.package_sha256}.avatar.vrm"
    if hasattr(os, "symlink"):
        symlink_target = base / "untrusted-vrm-target"
        symlink_target.write_bytes(b"do-not-touch")
        os.symlink(symlink_target, expected6)
        expect_error(
            handoff_store.prepare_current,
            RendererHandoffError,
            "renderer destination symlink is rejected rather than followed",
        )
        check(
            symlink_target.read_bytes() == b"do-not-touch",
            "symlink rejection leaves target bytes untouched",
        )
        expected6.unlink()

    package7, _payloads7 = packages[6]
    receipt7 = store.install(package7, expected_identity_id=body_id)
    current.select(body_id)
    expected7 = handoff_store.staging_root / f"{body_id}.{receipt7.package_sha256}.avatar.vrm"
    expected7.mkdir()
    expect_error(
        handoff_store.prepare_current,
        RendererHandoffError,
        "non-file renderer destination fails closed",
    )
    check(expected7.is_dir(), "incompatible renderer destination remains untouched")

print(f"\n===== BODYRIG M2.8 RENDERER HANDOFF: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
