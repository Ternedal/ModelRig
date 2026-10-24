#!/usr/bin/env python3
"""Audit tracked Android signing secrets without reading their contents.

Exit 0 in audit mode even when legacy tracked credentials exist. Use
--enforce only after the migration has removed tracked material.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

PRIVATE_SUFFIXES = (".keystore", ".jks", ".p12", ".pfx")
SIGNING_PROPERTIES = "android/signing/keystore.properties"
LEGACY_TRACKED_PATHS = frozenset({SIGNING_PROPERTIES, "android/signing/modelrig.keystore"})


def is_signing_material(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized == SIGNING_PROPERTIES:
        return True
    return normalized.startswith("android/signing/") and normalized.lower().endswith(PRIVATE_SUFFIXES)


def tracked_signing_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return sorted(
        path for path in result.stdout.decode("utf-8", errors="replace").split("\0")
        if path and is_signing_material(path)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enforce", action="store_true", help="Fail if tracked signing material exists")
    parser.add_argument("--block-new", action="store_true", help="Fail on signing material outside the two known legacy paths")
    args = parser.parse_args(argv)
    paths = tracked_signing_files()
    if paths:
        new_paths = [path for path in paths if path not in LEGACY_TRACKED_PATHS]
        print(f"Android signing audit: {len(paths)} tracked sensitive path(s), {len(new_paths)} outside legacy allowlist.")
        print("Do not publish contents. Follow docs/security/ANDROID_SIGNING_EXPOSURE_20261024.md.")
        return 1 if args.enforce or (args.block_new and new_paths) else 0
    print("Android signing audit: no tracked signing paths detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
