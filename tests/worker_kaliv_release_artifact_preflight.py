"""Fail-closed checks for the isolated artifact preflight."""
from __future__ import annotations

import tempfile
from pathlib import Path

from kaliv_release_artifact_preflight import AttestationError, preflight
from kaliv_system_release_gate import REQUIRED_GATES, REQUIRED_REPOSITORIES


def run() -> None:
    manifest = {
        "schema": "kaliv-system-release-manifest/v1",
        "release_id": "kaliv-rc-preflight-test",
        "repositories": [
            {"repository": repo, "git_sha": format(i + 1, "x") * 40}
            for i, repo in enumerate(REQUIRED_REPOSITORIES)
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
        except AttestationError as exc:
            assert "not fully qualified" in str(exc)
        else:
            raise AssertionError("PENDING evidence must never qualify")


if __name__ == "__main__":
    run()
    print("Artifact preflight pending-gate rejection: PASS")
