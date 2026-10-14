#!/usr/bin/env python3
"""Independent, fail-closed *local artifact* attestation preflight.

This is not a release qualifier. It verifies that a supplied manifest's PASS
references have independently retrieved bytes matching operator-supplied
SHA-256 values. Producer-specific semantic replay and human approval are still
required before release authorization. No network access or production writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_BYTES = 16 * 1024 * 1024


class AttestationError(ValueError):
    pass


def preflight(manifest: dict, attestations: dict, root: Path) -> dict:
    """Check exact one-to-one coverage, bounded regular files, hashes and pins."""
    from kaliv_system_release_gate import REQUIRED_GATES, REQUIRED_REPOSITORIES, evaluate_manifest

    verdict = evaluate_manifest(manifest)
    if not verdict.release_ready:
        raise AttestationError("structural release manifest is not fully qualified")
    if not isinstance(attestations, dict) or set(attestations) != set(REQUIRED_GATES):
        raise AttestationError("attestation set must exactly cover required gates")
    if not root.is_dir():
        raise AttestationError("artifact root does not exist")
    root = root.resolve(strict=True)
    checked = []
    for gate in REQUIRED_GATES:
        item = attestations[gate]
        if not isinstance(item, dict) or set(item) != {"reference", "path", "sha256", "repository", "git_sha"}:
            raise AttestationError(f"{gate}: invalid attestation fields")
        refs = manifest["gates"][gate]["evidence_refs"]
        if len(refs) != 1 or item["reference"] != refs[0]:
            raise AttestationError(f"{gate}: reference mismatch")
        repo = item["repository"]
        if repo not in REQUIRED_REPOSITORIES or item["git_sha"] != verdict.pinned_repositories[repo]:
            raise AttestationError(f"{gate}: repository pin mismatch")
        if not isinstance(item["git_sha"], str) or not SHA40.fullmatch(item["git_sha"]):
            raise AttestationError(f"{gate}: invalid git SHA")
        digest = item["sha256"]
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise AttestationError(f"{gate}: invalid SHA-256")
        # Canonical reference digests may hash producer payloads rather than
        # the artifact file bytes. Do not equate these independent digests.
        # Producer-specific semantic replay must validate reference payloads.
        rel = item["path"]
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise AttestationError(f"{gate}: invalid relative path")
        # Reject symlinks in every path component: a resolved-path check alone
        # can silently accept a link to another artifact inside the root.
        candidate = root
        for part in Path(rel).parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise AttestationError(f"{gate}: symlink artifact path")
        path = candidate.resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise AttestationError(f"{gate}: unsafe or missing artifact")
        if path.stat().st_size > MAX_BYTES:
            raise AttestationError(f"{gate}: artifact exceeds size limit")
        hasher = hashlib.sha256()
        with path.open("rb") as artifact:
            total = 0
            while chunk := artifact.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise AttestationError(f"{gate}: artifact exceeds size limit")
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise AttestationError(f"{gate}: artifact byte hash mismatch")
        checked.append(gate)
    return {
        "schema": "kaliv-artifact-byte-preflight/v1",
        "state": "BYTE_HASHES_VERIFIED_ONLY",
        "release_ready": False,
        "production_activation": False,
        "checked_gates": checked,
        "requires": ["producer_semantic_replay", "human_approval", "trusted_provenance"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("attestations", type=Path)
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args()
    try:
        output = preflight(json.loads(args.manifest.read_text(encoding="utf-8")),
                           json.loads(args.attestations.read_text(encoding="utf-8")),
                           args.artifact_root)
    except (AttestationError, ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"state": "INVALID", "release_ready": False, "error": str(exc)}))
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
