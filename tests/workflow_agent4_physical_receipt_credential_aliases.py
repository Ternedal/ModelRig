#!/usr/bin/env python3
"""A4-20 credential-alias hardening for the offline physical receipt verifier."""

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
    def assertAliasRejected(self, key: str, value: str) -> None:
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

    def test_noncredential_metadata_names_remain_allowed(self) -> None:
        receipt = cases.valid_receipt()
        receipt["debug"] = {
            "requestIdentifier": "req-123",
            "credentialDataIncludedMirror": False,
            "artifactDigest": "redacted-observation",
        }
        cases.resign(receipt)
        verifier.verify_receipt(receipt, expected_sha=cases.EXPECTED_SHA)


if __name__ == "__main__":
    unittest.main()
