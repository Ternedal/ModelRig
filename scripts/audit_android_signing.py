#!/usr/bin/env python3
"""Read-only, redacted inventory of tracked Android signing materials.

Run from any working directory:
    python scripts/audit_android_signing.py
    python scripts/audit_android_signing.py --strict

Never opens a keystore or prints signing-property values. Does not rotate keys.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNING_PREFIX = "android/signing/"
SENSITIVE_SUFFIXES = (".keystore", ".jks", ".p12", ".pfx")
SENSITIVE_NAMES = {"keystore.properties", "key.properties"}


def inventory() -> dict:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", SIGNING_PREFIX],
        capture_output=True,
        check=True,
    )
    paths = sorted(
        path.decode("utf-8", errors="replace")
        for path in result.stdout.split(b"\0")
        if path
    )
    flagged = [
        path for path in paths
        if Path(path).name.lower() in SENSITIVE_NAMES
        or path.lower().endswith(SENSITIVE_SUFFIXES)
    ]
    return {
        "schema_version": 1,
        "tracked_signing_files": len(paths),
        "exposed_paths": flagged,
        "finding": "TRACKED_SIGNING_MATERIAL" if flagged else "NO_TRACKED_SIGNING_MATERIAL",
        "note": "Path-only inventory. No credential contents or history scan.",
    }


def _tracked_sensitive_blob_ids() -> dict[str, str]:
    """Read index blob IDs only: never read or print signing file contents."""
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--stage", "-z", "--", SIGNING_PREFIX],
        capture_output=True,
        check=True,
    )
    tracked: dict[str, str] = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            mode, sha, stage = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
            if (
                stage != "0" or mode not in ("100644", "100755")
                or len(sha) != 40
                or any(ch not in "0123456789abcdef" for ch in sha)
                or not path.startswith(SIGNING_PREFIX)
            ):
                raise ValueError("invalid Git index entry")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("invalid signing Git index entry") from exc
        if Path(path).name.lower() in SENSITIVE_NAMES or path.lower().endswith(SENSITIVE_SUFFIXES):
            if path in tracked:
                raise ValueError("duplicate signing index path")
            tracked[path] = sha
    return tracked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Exit 1 if material is tracked")
    parser.add_argument("--baseline", help="JSON list of known tracked signing paths; fail on newly introduced paths")
    parser.add_argument("--blob-baseline", help="JSON object of expected Git blob IDs; fail on changed or removed signing files")
    args = parser.parse_args()
    try:
        report = inventory()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"inventory unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2
    if args.baseline:
        try:
            allowed = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            if not isinstance(allowed, list) or not all(isinstance(p, str) for p in allowed):
                raise ValueError("baseline must be a JSON array of paths")
        except (OSError, ValueError) as exc:
            print(f"invalid baseline: {type(exc).__name__}", file=sys.stderr)
            return 2
        report["new_paths"] = sorted(set(report["exposed_paths"]) - set(allowed))
    if args.blob_baseline:
        try:
            expected = json.loads(Path(args.blob_baseline).read_text(encoding="utf-8"))
            if (
                not isinstance(expected, dict) or not expected
                or any(
                    not isinstance(path, str) or not path.startswith(SIGNING_PREFIX)
                    or not isinstance(sha, str) or len(sha) != 40
                    or any(ch not in "0123456789abcdef" for ch in sha)
                    for path, sha in expected.items()
                )
            ):
                raise ValueError("blob baseline must be a non-empty path-to-sha mapping")
            observed = _tracked_sensitive_blob_ids()
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"invalid signing blob baseline: {type(exc).__name__}", file=sys.stderr)
            return 2
        report["changed_pinned_paths"] = sorted(
            path for path, sha in expected.items() if observed.get(path) != sha
        )
        report["unpinned_blob_paths"] = sorted(set(observed) - set(expected))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return int(
        bool(report.get("new_paths"))
        or bool(report.get("changed_pinned_paths"))
        or bool(report.get("unpinned_blob_paths"))
        or (args.strict and bool(report["exposed_paths"]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
