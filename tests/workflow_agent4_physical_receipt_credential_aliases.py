#!/usr/bin/env python3
"""Credential and path-bound digest hardening for the offline physical receipt verifier."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SUPPORT = ROOT / "tests" / "workflow_agent4_physical_receipt_offline_verifier.py"
sys.path.insert(0, str(SCRIPTS))

import agent4_physical_receipt_verify_offline as verifier  # noqa: E402

spec = importlib.util.spec_from_file_location("offline_verifier_cases", SUPPORT)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load offline verifier support cases")
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)


class CredentialAliasHardeningTests(unittest.TestCase):
    def assertAliasRejected(self, key: str, value: object) -> None:
        receipt = cases.valid_receipt()
        receipt["debug"] = {key: value}
        cases.resign(receipt)
        with self.assertRaisesRegex(verifier.VerificationError, "forbidden credential field"):
            verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_camel_case_device_token_key_is_rejected(self) -> None:
        self.assertAliasRejected("deviceToken", "opaque-value")

    def test_camel_case_pairing_code_key_is_rejected(self) -> None:
        self.assertAliasRejected("pairingCode", "opaque-value")

    def test_kebab_case_admin_key_is_rejected(self) -> None:
        self.assertAliasRejected("admin-key", "opaque-value")

    def test_authorization_header_alias_is_rejected(self) -> None:
        self.assertAliasRejected("AuthorizationHeader", "opaque-value")

    def test_nested_client_secret_alias_is_rejected(self) -> None:
        receipt = cases.valid_receipt()
        receipt["debug"] = {"nested": {"clientSecretValue": "opaque-value"}}
        cases.resign(receipt)
        with self.assertRaisesRegex(verifier.VerificationError, "forbidden credential field"):
            verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_unlabelled_raw_pairing_code_in_note_is_rejected(self) -> None:
        receipt = cases.valid_receipt()
        receipt["trials"]["network_recovery"]["note"] = "temporary value ABCD-EFGH was redacted too late"
        cases.resign(receipt)
        with self.assertRaisesRegex(verifier.VerificationError, "credential-like value"):
            verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_unlabelled_raw_device_token_in_note_is_rejected(self) -> None:
        receipt = cases.valid_receipt()
        raw_token = "0123456789abcdef" * 4
        receipt["trials"]["network_recovery"]["note"] = f"temporary value {raw_token} was redacted too late"
        cases.resign(receipt)
        with self.assertRaisesRegex(verifier.VerificationError, "credential-like value"):
            verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_sha256_prefixed_raw_token_in_note_is_rejected(self) -> None:
        receipt = cases.valid_receipt()
        raw_token = "0123456789abcdef" * 4
        receipt["trials"]["network_recovery"]["note"] = f"temporary digest sha256:{raw_token} was redacted too late"
        cases.resign(receipt)
        with self.assertRaisesRegex(verifier.VerificationError, "credential-like value"):
            verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_unknown_digest_extension_cannot_create_hash_authority(self) -> None:
        receipt = cases.valid_receipt()
        receipt["debug"] = {
            "sha256": "sha256:" + ("0123456789abcdef" * 4),
            "artifactDigest": "sha256:" + ("fedcba9876543210" * 4),
        }
        cases.resign(receipt)
        with self.assertRaisesRegex(verifier.VerificationError, "credential-like value"):
            verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_canonical_receipt_hash_slots_remain_allowed(self) -> None:
        receipt = cases.valid_receipt()
        self.assertRegex(receipt["receipt_sha256"], verifier.SHA256_RE)
        self.assertRegex(receipt["fixture"]["latest_timeline_hash"], verifier.SHA256_RE)
        self.assertRegex(receipt["mutations"][0]["receipt_sha256"], verifier.SHA256_RE)
        self.assertRegex(receipt["trials"]["grant_same_token_200"]["payload_sha256"], verifier.SHA256_RE)
        self.assertRegex(receipt["artifacts"][0]["sha256"], verifier.SHA256_RE)
        self.assertRegex(receipt["safety_hardening"]["pixel_serial_sha256"], verifier.SHA256_RE)
        self.assertRegex(receipt["safety_hardening"]["binding_file"]["sha256"], verifier.SHA256_RE)
        verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_noncredential_metadata_names_remain_allowed(self) -> None:
        receipt = cases.valid_receipt()
        receipt["debug"] = {
            "requestIdentifier": "req-123",
            "credentialDataIncludedMirror": False,
            "artifactDigest": "redacted-observation",
        }
        cases.resign(receipt)
        verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_schema_cleanup_admin_key_deleted_marker_remains_allowed(self) -> None:
        receipt = cases.valid_receipt()
        self.assertIs(receipt["cleanup"]["admin_key_deleted"], True)
        verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)

    def test_admin_key_deleted_alias_outside_cleanup_is_still_rejected(self) -> None:
        self.assertAliasRejected("admin_key_deleted", True)


if __name__ == "__main__":
    unittest.main()
