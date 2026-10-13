#!/usr/bin/env python3
"""Fail-closed preflight for a release manifest and locally supplied evidence.

This is NOT physical attestation: hashes of local files alone do not prove that
the files came from the canonical producer or a human-approved physical run.
Never promote this preflight's output into a production authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import kaliv_system_release_gate as gate

SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_BYTES = 4 * 1024 * 1024


def check(manifest_path: Path, ledger_path: Path) -> dict:
    """Require an independently prepared ledger for every PASS reference."""
    manifest = gate.load_manifest(manifest_path)
    structural = gate.evaluate_manifest(manifest)
    if not structural.release_ready:
        raise ValueError("structural release gate is BLOCKED")
    if ledger_path.is_symlink() or not ledger_path.is_file():
        raise ValueError("ledger missing or symlinked")
    if ledger_path.stat().st_size > MAX_BYTES:
        raise ValueError("ledger oversized")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(ledger, dict) or set(ledger) != set(gate.REQUIRED_GATES):
        raise ValueError("ledger must cover exactly all release gates")
    root = ledger_path.resolve().parent
    if root.is_symlink():
        raise ValueError("ledger root is symlinked")
    for name in gate.REQUIRED_GATES:
        refs = manifest["gates"][name]["evidence_refs"]
        item = ledger[name]
        if not isinstance(item, dict) or set(item) != {"ref", "path", "sha256"}:
            raise ValueError(f"{name}: invalid ledger entry")
        if item["ref"] != refs[0]:
            raise ValueError(f"{name}: canonical reference mismatch")
        expected = item["sha256"]
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            raise ValueError(f"{name}: invalid sha256")
        relative = item["path"]
        if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
                or "\\" in relative or not Path(relative).parts
                or any(part in (".", "..") for part in relative.split("/"))):
            raise ValueError(f"{name}: invalid relative path")
        candidate = root / relative
        if (any(part.is_symlink() for part in (candidate, *candidate.parents)
                if part != root and part.is_relative_to(root)) or not candidate.is_file()):
            raise ValueError(f"{name}: missing or symlinked evidence")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"{name}: evidence escapes ledger directory")
        if resolved.stat().st_size > MAX_BYTES:
            raise ValueError(f"{name}: oversized evidence")
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"{name}: evidence bytes differ from ledger")
    return {
        "state": "LOCAL_BYTES_MATCH",
        "physical_provenance_verified": False,
        "human_approval_verified": False,
        "release_ready": False,
        "production_activation": False,
        "warning": "Local hash matching is not canonical producer attestation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.manifest, args.ledger), sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, gate.SystemReleaseManifestError) as exc:
        print(json.dumps({"state": "INVALID", "release_ready": False,
                          "production_activation": False, "error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
