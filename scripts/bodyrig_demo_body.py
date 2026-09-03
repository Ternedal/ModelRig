#!/usr/bin/env python3
"""Make one body from a VRM and nothing else -- the first live body.

The real pipeline is video -> tracking -> identity bundle -> .mrbody, and
that is the product. But the first time a body has to reach the screen,
all anyone has is a VRM 1.0 avatar (VRoid Studio exports one) and an hour
at the rig. This builds a `.mrbody` from that avatar plus a demo identity
bundle, installs it into a profile store, and selects it as current -- so
`/body/active` answers, the Unity renderer has something to show, and the
frames have a body to drive.

The demo identity is a fixture, not a person: its bodyprint carries no
measurements from anyone. Rebuild from real tracking when the pipeline
has run.

    python scripts\\bodyrig_demo_body.py --vrm C:\\path\\Kaliv.vrm --name Kaliv ^
        --store C:\\Users\\admin\\Desktop\\ModelRig-appliance\\bodyrig-profiles
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from bodyrig.identity import build_identity_bundle  # noqa: E402
from bodyrig.mrbody import MRBodyError, build_mrbody, validate_mrbody  # noqa: E402
from bodyrig.profile_selection import MRBodyCurrentProfileStore  # noqa: E402
from bodyrig.profile_store import MRBodyProfileStore  # noqa: E402
from bodyrig_fixtures import tracking_fixture  # noqa: E402


def _png_1x1() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)
    raw = b"\x00\x8c\x8c\x8c\xff"  # one grey RGBA pixel, filter byte 0
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def make_demo_body(*, vrm_path: Path, name: str, thumbnail: Path | None, source_name: str) -> tuple[bytes, str]:
    avatar = vrm_path.read_bytes()
    identity = build_identity_bundle(tracking_fixture(source_name))
    thumb = thumbnail.read_bytes() if thumbnail else _png_1x1()
    package = build_mrbody(identity, display_name=name, avatar_vrm=avatar, thumbnail_png=thumb)
    inspection = validate_mrbody(package)
    return package, inspection.body_id


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vrm", required=True, type=Path, help="VRM 1.0 avatar (.vrm / GLB)")
    ap.add_argument("--name", required=True, help="display name")
    ap.add_argument("--store", required=True, type=Path, help="profile-store directory (KALIV_BODY_STORE)")
    ap.add_argument("--thumbnail", type=Path, default=None, help="PNG thumbnail (default: a grey pixel)")
    ap.add_argument("--source-name", default="demo-body.mov",
                    help="identity source label; change it to get a second, distinct demo body")
    ap.add_argument("--no-select", action="store_true", help="install but do not make it current")
    ap.add_argument("--keep", type=Path, default=None, help="also write the .mrbody here")
    a = ap.parse_args()
    try:
        package, body_id = make_demo_body(vrm_path=a.vrm, name=a.name, thumbnail=a.thumbnail, source_name=a.source_name)
    except MRBodyError as exc:
        raise SystemExit(f"could not build a body from {a.vrm}: {exc}")
    if a.keep:
        a.keep.write_bytes(package)
    store = MRBodyProfileStore(a.store)
    receipt = store.install(package)
    selected = not a.no_select
    if selected:
        MRBodyCurrentProfileStore(store).select(body_id)
    print(json.dumps({
        "body_id": body_id, "name": a.name, "package_sha256": receipt.package_sha256,
        "store": str(a.store), "selected": selected, "demo_identity": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
