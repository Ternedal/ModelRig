"""Fail-closed tests for offline producer-file inventory (NOT a release gate)."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "kaliv_release_producer_file_inventory.py"
SPEC = importlib.util.spec_from_file_location("kaliv_release_producer_file_inventory", SCRIPT)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

SHA = {"ModelRig": "1" * 40, "BodyRig": "2" * 40,
       "VisionRig": "3" * 40, "VoiceRig": "4" * 40}
REPORT_UNSIGNED = {
    "schema": "kaliv-system/software-exact-green-verdict/v1",
    "state": "QUALIFIED",
    "software_exact_green_gate_satisfied": True,
    "release_gate_satisfied": False,
    "production_activation": False,
    "repositories": [
        {"repository": "Ternedal/" + name, "git_sha": sha,
         "evidence_ref": "test-only-source:" + name}
        for name, sha in SHA.items()
    ],
}
REPORT_DIGEST = hashlib.sha256(
    json.dumps(
        REPORT_UNSIGNED, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
).hexdigest()
REF = (
    "kaliv-software-exact-green:" + SHA["ModelRig"] + ":"
    + SHA["BodyRig"] + ":" + SHA["VisionRig"] + ":"
    + SHA["VoiceRig"] + ":" + REPORT_DIGEST
)


def manifest():
    return {
        "schema": audit.release_gate.SCHEMA,
        "release_id": "kaliv-rc-producer-inventory-test",
        "repositories": [
            {"repository": "Ternedal/" + name, "git_sha": sha}
            for name, sha in SHA.items()
        ],
        "gates": {
            gate: {
                "status": "PASS" if gate == "software_exact_green" else "PENDING",
                "evidence_refs": [REF] if gate == "software_exact_green" else [],
            }
            for gate in audit.release_gate.REQUIRED_GATES
        },
        "production_activation": False,
    }


def reject(m, i, root, phrase):
    try:
        audit.inventory(m, i, root)
    except audit.InventoryError as exc:
        assert phrase in str(exc), (phrase, str(exc))
    else:
        raise AssertionError(f"accepted unsafe producer-file input ({phrase})")


def run_contract():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        report_path = root / "producer.json"
        report = dict(REPORT_UNSIGNED, release_evidence_ref=REF)
        def write_report(value):
            raw = (json.dumps(value, sort_keys=True) + "\n").encode()
            report_path.write_bytes(raw)
            return hashlib.sha256(raw).hexdigest()
        digest = write_report(report)
        idx = {"schema": audit.SCHEMA, "entries": [
            {"gate": "software_exact_green",
             "report_path": "producer.json", "sha256": digest}
        ]}
        m = manifest()
        result = audit.inventory(m, idx, root)
        assert result["state"] == "SOURCE_FILES_ACCOUNTED_FOR"
        assert result["declared_pass_gates"] == 1
        assert len(result["pending_gates"]) == 9
        assert result["files"][0]["report_sha256"] == digest
        for key in ("producer_authenticity_proven", "physical_acceptance_proven",
                    "release_gate_satisfied", "release_ready", "production_activation"):
            assert result[key] is False

        bad = copy.deepcopy(idx)
        bad["entries"][0]["sha256"] = "f" * 64
        reject(m, bad, root, "do not match indexed SHA-256")

        bad = copy.deepcopy(idx)
        bad["entries"][0]["report_path"] = "../producer.json"
        reject(m, bad, root, "must not be absolute or escaped")

        bad = copy.deepcopy(idx)
        bad["entries"][0]["report_path"] = "/tmp/producer.json"
        reject(m, bad, root, "must not be absolute or escaped")

        bad = copy.deepcopy(idx)
        bad["entries"][0]["gate"] = "other"
        reject(m, bad, root, "unknown indexed gate")

        bad = copy.deepcopy(idx)
        bad["entries"].append(copy.deepcopy(bad["entries"][0]))
        reject(m, bad, root, "duplicate or unknown indexed gate")

        bad = copy.deepcopy(idx)
        bad["entries"] = []
        reject(m, bad, root, "declared PASS gates")

        # A newly indexed hash over tampered bytes is not sufficient when
        # the source verdict also has its own canonical ref digest.
        bad_report = copy.deepcopy(report)
        bad_report["repositories"][1]["git_sha"] = "f" * 40
        bad_index = copy.deepcopy(idx)
        bad_index["entries"][0]["sha256"] = write_report(bad_report)
        reject(m, bad_index, root, "producer repository revisions do not match manifest pins")

        bad_report = copy.deepcopy(report)
        bad_report["repositories"][3] = copy.deepcopy(bad_report["repositories"][2])
        bad_index = copy.deepcopy(idx)
        bad_index["entries"][0]["sha256"] = write_report(bad_report)
        reject(m, bad_index, root, "producer repository revisions do not match manifest pins")

        bad_report = copy.deepcopy(report)
        bad_report["software_exact_green_gate_satisfied"] = False
        bad_index = copy.deepcopy(idx)
        bad_index["entries"][0]["sha256"] = write_report(bad_report)
        reject(m, bad_index, root, "self-digest mismatch")

        bad_report = copy.deepcopy(report)
        bad_report["schema"] = "kaliv-system/modified-verdict/v1"
        bad_index = copy.deepcopy(idx)
        bad_index["entries"][0]["sha256"] = write_report(bad_report)
        reject(m, bad_index, root, "source report schema mismatch")

        bad_report = copy.deepcopy(report)
        bad_report["release_evidence_ref"] = REF[:-1] + "f"
        bad["entries"] = [dict(idx["entries"][0])]
        bad["entries"][0]["sha256"] = write_report(bad_report)
        reject(m, bad, root, "differs from manifest ref")

        for field, value, fragment in (
            ("production_activation", True, "overclaims production"),
            ("release_gate_satisfied", True, "overclaims system release"),
            ("state", "INVALID", "not successful"),
        ):
            bad_report = copy.deepcopy(report)
            bad_report[field] = value
            bad_idx = copy.deepcopy(idx)
            bad_idx["entries"][0]["sha256"] = write_report(bad_report)
            reject(m, bad_idx, root, fragment)

        # Ensure the parser cannot silently discard conflicting JSON keys.
        try:
            audit._json_bytes(b'{"schema":"one","schema":"two"}', "input")
        except audit.InventoryError as exc:
            assert "duplicate JSON field" in str(exc)
        else:
            raise AssertionError("duplicate JSON key was accepted")

        write_report(report)
        link = root / "shortcut.json"
        try:
            link.symlink_to(report_path)
        except (NotImplementedError, OSError):
            pass  # Symlinks can require elevated privilege on Windows.
        else:
            bad_idx = copy.deepcopy(idx)
            bad_idx["entries"][0]["report_path"] = "shortcut.json"
            reject(m, bad_idx, root, "symlink")

        # No amount of syntactically valid local evidence inventory can
        # produce a release-ready or production-active verdict.
        assert "release_ready" in result and result["release_ready"] is False
    print("PASS: fail-closed local producer-file accounting (no release authority)")


if __name__ == "__main__":
    run_contract()
