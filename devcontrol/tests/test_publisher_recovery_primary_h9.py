from __future__ import annotations

import inspect
import unittest

import kaliv_dev_control.publisher_authorization as public_module
import kaliv_dev_control.publisher_recovery_authorization as h6_module
import kaliv_dev_control.publisher_recovery_authorization_strict as strict_module
import kaliv_dev_control.publisher_recovery_primary as primary_module
import kaliv_dev_control.publisher_recovery_receipt_finalizer as finalizer_module
import kaliv_dev_control.publisher_recovery_receipt_v3 as receipt_module


class PublisherRecoveryPrimaryH9Tests(unittest.TestCase):
    def test_public_boundary_uses_one_physical_ledger_and_verifier(self):
        self.assertIs(
            public_module.PublisherReplayLedgerV2,
            primary_module.PublisherReplayLedgerV3,
        )
        self.assertIs(
            public_module.PublisherReplayLedgerV3,
            primary_module.PublisherReplayLedgerV3,
        )
        self.assertIs(
            public_module.PublisherReplayRecoveryAuthorizationVerifierV1,
            primary_module.PublisherReplayRecoveryAuthorizationVerifierV1,
        )
        self.assertIs(
            strict_module.PublisherReplayRecoveryAuthorizationVerifierV1,
            primary_module.PublisherReplayRecoveryAuthorizationVerifierV1,
        )
        self.assertIs(
            finalizer_module.PublisherReplayLedgerV3,
            primary_module.PublisherReplayLedgerV3,
        )
        self.assertIs(
            finalizer_module.PublisherReplayRecoveryAuthorizationVerifierV1,
            primary_module.PublisherReplayRecoveryAuthorizationVerifierV1,
        )

    def test_primary_implementation_does_not_mutate_h6_classes(self):
        self.assertTrue(
            issubclass(
                primary_module.PublisherReplayLedgerV3,
                h6_module.PublisherReplayLedgerV3,
            )
        )
        self.assertTrue(
            issubclass(
                primary_module.PublisherReplayRecoveryAuthorizationVerifierV1,
                h6_module.PublisherReplayRecoveryAuthorizationVerifierV1,
            )
        )
        self.assertIn(
            "recover_authenticated",
            primary_module.PublisherReplayLedgerV3.__dict__,
        )
        self.assertIsNot(
            primary_module.PublisherReplayLedgerV3.recover_authenticated,
            h6_module.PublisherReplayLedgerV3.recover_authenticated,
        )
        self.assertNotIn(
            "_h7_receipt_v3_installed",
            h6_module.PublisherReplayLedgerV3.__dict__,
        )

    def test_receipt_module_is_artifact_only(self):
        receipt_source = inspect.getsource(receipt_module)
        for forbidden in (
            "recover_authenticated =",
            "PublisherReplayLedgerV3.recover_authenticated",
            "_h7_receipt_v3_installed",
            "setattr(PublisherReplayLedger",
            "_recovery_module.PublisherReplayRecoveryAuthorizationVerifierV1",
        ):
            self.assertNotIn(forbidden, receipt_source)
        self.assertNotIn(
            "PublisherReplayRecoveryAuthorizationVerifierV1",
            receipt_module.__dict__,
        )

    def test_primary_surface_has_no_writer_or_transport_authority(self):
        source = inspect.getsource(primary_module)
        for forbidden in (
            "Ed25519PrivateKey",
            "from_private_bytes",
            "load_pem_private_key",
            "import hmac",
            "github_token",
            "api.github.com",
            "import requests",
            "import socket",
            "subprocess",
            "git push",
            "pull_request",
            "merge_pull_request",
            "deployment",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
