#!/usr/bin/env python3
"""Vendor VisionRig's Kaliv producer into android/visionrig-producer from ONE exact VisionRig SHA.

ModelRig #2275 (decision 6478056078): the Android app consumes VisionRig's
producer as a pinned, verified copy in its own Gradle module, not through a
composite build, which would need a VisionRig checkout in every workflow that
builds the APK, release pipeline included.

    python scripts/sync_visionrig_producer.py --visionrig ../VisionRig --sha <40-hex>

The VisionRig checkout must be clean and at exactly --sha. The copy is
deterministic: the same SHA always gives the same files and the same
VENDORED_FROM.json (upstream path, destination path and SHA-256 per file,
plus provenance and license). tests/workflow_visionrig_vendored_producer.py
verifies that offline and fails on any hand edit, missing or extra file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "android/visionrig-producer"
DEST = MODULE / "src/main/kotlin"
MANIFEST = MODULE / "VENDORED_FROM.json"
LICENSE_COPY = MODULE / "LICENSE-VisionRig"
SOURCES = (
    "clients/kaliv-producer-core/src/main/kotlin",
    "clients/kaliv-android-producer/library/src/main/kotlin",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--visionrig", required=True, type=Path, help="VisionRig checkout")
    parser.add_argument("--sha", required=True, help="exact 40-hex VisionRig commit")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full 40-hex commit")
    repo = args.visionrig.resolve()
    head = git(repo, "rev-parse", "HEAD")
    if head != args.sha:
        print(f"refused: VisionRig checkout is at {head}, not {args.sha}", file=sys.stderr)
        return 2
    if git(repo, "status", "--porcelain"):
        print("refused: VisionRig checkout has local changes", file=sys.stderr)
        return 2

    if DEST.exists():
        shutil.rmtree(DEST)
    entries = []
    for source in SOURCES:
        src_root = repo / source
        for path in sorted(src_root.rglob("*.kt")):
            relative = path.relative_to(src_root)
            out = DEST / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)
            entries.append({
                "upstream": f"{source}/{relative.as_posix()}",
                "destination": out.relative_to(MODULE).as_posix(),
                "sha256": sha256(out),
            })
    shutil.copyfile(repo / "LICENSE", LICENSE_COPY)
    manifest = {
        "schema": "modelrig/vendored-source/v1",
        "provenance": {
            "repository": "https://github.com/Ternedal/VisionRig",
            "sha": args.sha,
            "upstream_roots": list(SOURCES),
            "synced_by": "scripts/sync_visionrig_producer.py",
        },
        "license": {
            "spdx": "MIT",
            "file": LICENSE_COPY.name,
            "sha256": sha256(LICENSE_COPY),
        },
        "files": sorted(entries, key=lambda e: e["destination"]),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"vendored {len(entries)} files from VisionRig {args.sha} into {MODULE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
