"""Negative regression cases for isolated artifact byte preflight."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from kaliv_release_artifact_preflight import AttestationError, preflight
from kaliv_system_release_gate import REQUIRED_GATES, REQUIRED_REPOSITORIES


def test_pending_is_rejected() -> None:
    manifest = {
        "schema": "kaliv-system-release-manifest/v1",
        "release_id": "kaliv-rc-negative",
        "repositories": [
            {"repository": repo, "git_sha": format(index + 1, "x") * 40}
            for index, repo in enumerate(REQUIRED_REPOSITORIES)
        ],
        "gates": {
            gate: {"status": "PENDING", "evidence_refs": []}
            for gate in REQUIRED_GATES
        },
        "production_activation": False,
    }
    with tempfile.TemporaryDirectory() as directory:
        try:
            preflight(manifest, {}, Path(directory))
        except AttestationError:
            pass
        else:
            raise AssertionError("pending gates must fail closed")


def test_digest_example() -> None:
    with tempfile.TemporaryDirectory() as directory:
        artifact = Path(directory) / "sample.json"
        artifact.write_bytes(b'{"state":"PENDING"}')
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert len(digest) == 64
        artifact.write_bytes(b'{"state":"PASS"}')
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() != digest


if __name__ == "__main__":
    test_pending_is_rejected()
    test_digest_example()
    print("Negative preflight cases: PASS")
