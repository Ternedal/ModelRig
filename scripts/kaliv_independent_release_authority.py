#!/usr/bin/env python3
"""Read-only, fail-closed authority boundary for Kaliv V1 release evidence.

This entrypoint deliberately has no authority to release. The existing manifest
validator is structural; no cryptographic attestation trust root or independently
controlled evidence resolver has been provisioned yet. Never infer physical
acceptance from local files or a caller-supplied boolean.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import kaliv_system_release_gate as gate

SCHEMA = "kaliv-independent-release-authority/v1"


def evaluate(manifest_path: Path) -> dict:
    """Return a non-authorizing result even for a structurally qualified manifest."""
    manifest = gate.load_manifest(manifest_path)
    structural = gate.evaluate_manifest(manifest)
    return {
        "schema": SCHEMA,
        "release_id": structural.release_id,
        "state": "BLOCKED",
        "structural_state": structural.state,
        "structural_release_ready": structural.release_ready,
        "independent_provenance_verified": False,
        "human_approval_verified": False,
        "release_ready": False,
        "production_activation": False,
        "reason": "Independent producer attestation, artifact replay, and operator approval are not implemented.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.manifest)
    except (OSError, ValueError, KeyError, TypeError, gate.SystemReleaseManifestError) as exc:
        result = {
            "schema": SCHEMA,
            "state": "BLOCKED",
            "independent_provenance_verified": False,
            "human_approval_verified": False,
            "release_ready": False,
            "production_activation": False,
            "reason": "Invalid manifest or unavailable structural verification",
            "error": str(exc),
        }
    print(json.dumps(result, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
