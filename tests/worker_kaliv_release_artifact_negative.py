"""Executable adversarial checks of artifact byte preflight."""
from __future__ import annotations

import hashlib
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from kaliv_release_artifact_preflight import AttestationError, preflight
from kaliv_system_release_gate import REQUIRED_GATES, REQUIRED_REPOSITORIES

PINS = {repo: format(i + 1, "x") * 40 for i, repo in enumerate(REQUIRED_REPOSITORIES)}


def fixture(root: Path):
    manifest = {"gates": {gate: {"evidence_refs": []} for gate in REQUIRED_GATES}}
    attestations = {}
    for gate in REQUIRED_GATES:
        rel = f"{gate}.json"
        data = ('{"gate":"' + gate + '","status":"PASS"}').encode()
        (root / rel).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        reference = f"receipt:{gate}:{digest}"
        manifest["gates"][gate]["evidence_refs"] = [reference]
        attestations[gate] = {
            "reference": reference,
            "path": rel,
            "sha256": digest,
            "repository": REQUIRED_REPOSITORIES[0],
            "git_sha": PINS[REQUIRED_REPOSITORIES[0]],
        }
    return manifest, attestations


def rejected(manifest, attestations, root, reason):
    try:
        preflight(manifest, attestations, root)
    except (AttestationError, OSError) as exc:
        assert reason in str(exc), (reason, str(exc))
    else:
        raise AssertionError(f"unexpected acceptance: {reason}")


def run() -> None:
    # Patch structural evaluation only to isolate byte verification tests.
    # This is NEVER a real release approval and cannot change production state.
    verdict = SimpleNamespace(release_ready=True, pinned_repositories=PINS)
    with patch("kaliv_system_release_gate.evaluate_manifest", return_value=verdict):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, attestations = fixture(root)
            result = preflight(manifest, attestations, root)
            assert result["release_ready"] is False
            assert result["production_activation"] is False
            assert len(result["checked_gates"]) == len(REQUIRED_GATES)

            first = REQUIRED_GATES[0]
            item = attestations[first]
            original = dict(item)
            path = root / item["path"]
            old = path.read_bytes()

            path.write_bytes(old + b"tampered")
            rejected(manifest, attestations, root, "byte hash mismatch")
            path.write_bytes(old)

            item["sha256"] = "f" * 64
            rejected(manifest, attestations, root, "reference digest mismatch")
            item.update(original)

            item["reference"] = "receipt:wrong"
            rejected(manifest, attestations, root, "reference mismatch")
            item.update(original)

            item["sha256"] = "f" * 64
            item["reference"] = f"receipt:{first}:{item['sha256']}"
            manifest["gates"][first]["evidence_refs"] = [item["reference"]]
            rejected(manifest, attestations, root, "byte hash mismatch")
            item.update(original)
            manifest["gates"][first]["evidence_refs"] = [original["reference"]]

            item["git_sha"] = "f" * 40
            rejected(manifest, attestations, root, "repository pin mismatch")
            item.update(original)

            item["path"] = "../escape.json"
            rejected(manifest, attestations, root, "invalid relative path")
            item.update(original)

            item["path"] = "missing.json"
            rejected(manifest, attestations, root, "missing.json")
            item.update(original)

            del attestations[first]
            rejected(manifest, attestations, root, "exactly cover")
            attestations[first] = original

            path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
            rejected(manifest, attestations, root, "exceeds size limit")

    with patch("kaliv_system_release_gate.evaluate_manifest",
               return_value=SimpleNamespace(release_ready=False, pinned_repositories=PINS)):
        with tempfile.TemporaryDirectory() as directory:
            rejected({}, {}, Path(directory), "not fully qualified")


if __name__ == "__main__":
    run()
    print("Artifact preflight adversarial regression: PASS")
