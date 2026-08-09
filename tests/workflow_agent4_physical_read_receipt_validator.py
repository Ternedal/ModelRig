#!/usr/bin/env python3
"""Contracts for the A4-18 physical receipt validator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate-agent4-physical-read-receipt.py"
SPEC = importlib.util.spec_from_file_location("a4_receipt_validator", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

SHA = "a" * 40


def finalize_digest(receipt: dict) -> dict:
    unsigned = json.dumps(receipt, ensure_ascii=False, separators=(",", ":"))
    receipt["receipt_sha256"] = f"sha256:{hashlib.sha256(unsigned.encode('utf-8')).hexdigest()}"
    return receipt


def valid_receipt(artifact_path: str, artifact_bytes: bytes) -> dict:
    trials = {}
    for name in validator.REQUIRED_CHECKPOINTS:
        trials[name] = {
            "status": "pass",
            "observed_at": "2026-08-09T12:00:00Z",
            "note": "redacted physical observation",
            "http_status": validator.EXPECTED_HTTP.get(name),
            "route": "/api/v1/agent4/campaigns",
            "request_id": "redacted-request-id",
            "payload_sha256": None,
            "cursor_sha256": None,
            "screenshot": None,
        }
    receipt = {
        "schema": validator.SCHEMA,
        "generated_at": "2026-08-09T12:00:00Z",
        "expected_sha": SHA,
        "observed_head": SHA,
        "branch": "agent/a4-18-physical-read-product",
        "backend_version": "1.58.151",
        "worker_version": "1.58.151",
        "fixture": {"schema": "test-fixture/v1"},
        "mutations": [],
        "pixel": {
            "model": "Pixel 6a",
            "android_release": "17",
            "sdk": "37",
            "app_package": "dk.ternedal.modelrig",
            "version_name_line": "versionName=1.58.151",
            "version_code_line": "versionCode=158151",
        },
        "trials": trials,
        "artifacts": [{
            "path": artifact_path,
            "size_bytes": len(artifact_bytes),
            "sha256": f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}",
        }],
        "cleanup": {
            "backend_stopped": True,
            "worker_stopped": True,
            "unknown_process_preserved": False,
            "firewall_removed": True,
            "ports_free": True,
            "admin_key_deleted": True,
            "passed": True,
        },
        "all_required_observations_passed": True,
        "human_decision": "GO",
        "credential_data_included": False,
        "public_network": False,
        "production_activation": False,
    }
    return finalize_digest(receipt)


class Agent4PhysicalReceiptValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.artifact = self.root / "validation" / "proof.txt"
        self.artifact.parent.mkdir(parents=True)
        self.artifact.write_bytes(b"physical-proof")
        self.receipt = valid_receipt("validation/proof.txt", b"physical-proof")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def validate(self, receipt: dict | None = None) -> list[str]:
        return validator.validate_receipt(
            receipt or self.receipt,
            expected_sha=SHA,
            repo_root=self.root,
        )

    def resign(self, receipt: dict) -> dict:
        receipt.pop("receipt_sha256", None)
        return finalize_digest(receipt)

    def test_valid_go_receipt_and_artifact_pass(self) -> None:
        self.assertEqual(self.validate(), ["validation/proof.txt"])

    def test_wrong_exact_sha_fails(self) -> None:
        with self.assertRaisesRegex(validator.ReceiptValidationError, "--expected-sha"):
            validator.validate_receipt(self.receipt, expected_sha="b" * 40, repo_root=self.root)

    def test_missing_checkpoint_fails_even_when_resigned(self) -> None:
        self.receipt["trials"].pop("revoke_same_token_403")
        self.resign(self.receipt)
        with self.assertRaisesRegex(validator.ReceiptValidationError, "exactly the 21"):
            self.validate()

    def test_wrong_security_status_fails(self) -> None:
        self.receipt["trials"]["paired_without_grant_403"]["http_status"] = 200
        self.resign(self.receipt)
        with self.assertRaisesRegex(validator.ReceiptValidationError, "wrong HTTP status"):
            self.validate()

    def test_cleanup_failure_cannot_be_go(self) -> None:
        self.receipt["cleanup"]["ports_free"] = False
        self.resign(self.receipt)
        with self.assertRaisesRegex(validator.ReceiptValidationError, "cleanup.ports_free"):
            self.validate()

    def test_credential_shaped_key_is_rejected(self) -> None:
        self.receipt["debug"] = {"bearer": "redacted"}
        self.resign(self.receipt)
        with self.assertRaisesRegex(validator.ReceiptValidationError, "forbidden credential-shaped key"):
            self.validate()

    def test_tampered_receipt_digest_fails(self) -> None:
        self.receipt["pixel"]["model"] = "Pixel 9"
        with self.assertRaisesRegex(validator.ReceiptValidationError, "receipt_sha256"):
            self.validate()

    def test_non_pixel_device_fails(self) -> None:
        self.receipt["pixel"]["model"] = "Android SDK built for x86"
        self.resign(self.receipt)
        with self.assertRaisesRegex(validator.ReceiptValidationError, "Pixel"):
            self.validate()

    def test_artifact_hash_tamper_fails(self) -> None:
        self.artifact.write_bytes(b"tampered")
        with self.assertRaisesRegex(validator.ReceiptValidationError, "artifact size mismatch|artifact hash mismatch"):
            self.validate()

    def test_artifact_path_escape_fails(self) -> None:
        self.receipt["artifacts"][0]["path"] = "../outside.txt"
        self.resign(self.receipt)
        with self.assertRaisesRegex(validator.ReceiptValidationError, "escapes repo root"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
