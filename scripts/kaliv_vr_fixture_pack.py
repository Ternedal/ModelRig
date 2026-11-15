#!/usr/bin/env python3
"""Pack an already finished VRM into a normal, validated .mrbody V1 fixture.

This intentionally skips source/model generation. The package goes through
the regular ModelRig body store and API; no VR-client bypass is needed.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import zipfile
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bodyrig.mrbody import (
    MRBODY_BUILDER_VERSION, REQUIRED_PATHS, _canonical_json_bytes,
    _zip_info, validate_mrbody, validate_png_bytes, validate_vrm1_bytes,
)

def package(vrm: bytes, thumbnail: bytes, name: str) -> bytes:
    validate_vrm1_bytes(vrm)
    validate_png_bytes(thumbnail)
    # Stable fixture identity derived from source VRM bytes, not a claimed
    # completed BodyRig recovery/identity-capture run.
    revision = hashlib.sha256(b"kaliv-vr-fixture-v1\0" + vrm).hexdigest()[:24]
    body_id = "bodyid-" + revision
    manifest = {
        "format": "modelrig-body", "format_version": 1,
        "id": body_id, "name": name,
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json", "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": MRBODY_BUILDER_VERSION},
    }
    # Neutral renderer-local test values, NOT inferred biological attributes.
    bodyprint = {"format": "modelrig-bodyprint", "version": 1,
                 "runtime": {"idle_strength": 0.0}}
    provenance = {
        "format": "modelrig-body-provenance", "version": 1,
        "created_at": "2026-11-15T00:00:00Z",
        "source": {"kind": "user-supplied-local-media", "count": 1},
        "synthetic_avatar": True,
        "pipeline": [
            {"stage": "fixture_packaging", "adapter": "kaliv_vr_fixture",
             "revision": "v1"},
            {"stage": "identity_content", "adapter": "bodyrig.portable_identity",
             "revision": revision},
        ],
    }
    payload = {
        "avatar.vrm": vrm,
        "bodyprint.json": _canonical_json_bytes(bodyprint),
        "provenance.json": _canonical_json_bytes(provenance),
        "thumbnail.png": thumbnail,
    }
    checksums = {k: hashlib.sha256(v).hexdigest() for k, v in sorted(payload.items())}
    entries = {
        "manifest.json": _canonical_json_bytes(manifest),
        "checksums.json": _canonical_json_bytes(checksums),
        **payload,
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        for path in REQUIRED_PATHS:
            archive.writestr(_zip_info(path), entries[path])
    data = output.getvalue()
    validate_mrbody(data, expected_identity_id=body_id)
    return data

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vrm", type=Path, required=True)
    parser.add_argument("--thumbnail", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", default="Kaliv hologram test")
    args = parser.parse_args()
    if not args.name or len(args.name) > 160:
        parser.error("--name must have 1..160 characters")
    try:
        result = package(args.vrm.read_bytes(), args.thumbnail.read_bytes(), args.name)
        args.output.write_bytes(result)
        print(f"Validated fixture: {args.output} ({len(result)} bytes)")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Fixture build FAILED: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
