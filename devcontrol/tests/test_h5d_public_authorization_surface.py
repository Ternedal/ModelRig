from __future__ import annotations

import ast
import importlib
import inspect
import unittest

import kaliv_dev_control.publisher_authorization as public_authorization
from kaliv_dev_control import _publisher_authorization_legacy as legacy_shim
from kaliv_dev_control._compatibility_v1 import (
    local_candidate_materialization as legacy_local_candidate,
)
from kaliv_dev_control._compatibility_v1 import (
    publisher_authorization as legacy_authorization,
)


class PublisherAuthorizationPublicSurfaceH5DTests(unittest.TestCase):
    def test_public_namespace_contains_no_shared_secret_authority(self) -> None:
        forbidden = {
            "HmacPublisherAuthorizationIssuer",
            "TrustedAuthorizationIssuerKey",
            "PublisherAuthorizationVerifier",
            "PublisherAuthorizationLease",
            "PublisherReplayLedger",
            "PublisherReplayLedgerEntry",
            "PublisherPreflightReceipt",
            "PublisherPostconditionReceipt",
            "PUBLISHER_AUTHORIZATION_LEASE_SCHEMA",
        }
        self.assertTrue(forbidden.isdisjoint(public_authorization.__all__))
        for name in forbidden:
            with self.subTest(name=name):
                self.assertFalse(hasattr(public_authorization, name))

        tree = ast.parse(inspect.getsource(public_authorization))
        imported_names = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertNotIn("*", imported_names)
        self.assertTrue(forbidden.isdisjoint(imported_names))

    def test_from_public_import_of_hmac_issuer_fails(self) -> None:
        namespace: dict[str, object] = {}
        with self.assertRaises(ImportError):
            exec(
                "from kaliv_dev_control.publisher_authorization "
                "import HmacPublisherAuthorizationIssuer",
                namespace,
                namespace,
            )

    def test_legacy_implementation_is_internal_and_shimmed(self) -> None:
        self.assertTrue(
            legacy_authorization.HmacPublisherAuthorizationIssuer.__module__.startswith(
                "kaliv_dev_control._compatibility_v1."
            )
        )
        self.assertTrue(
            legacy_authorization.PublisherAuthorizationVerifier.__module__.startswith(
                "kaliv_dev_control._compatibility_v1."
            )
        )
        self.assertIs(
            legacy_shim.HmacPublisherAuthorizationIssuer,
            legacy_authorization.HmacPublisherAuthorizationIssuer,
        )
        self.assertTrue(
            legacy_local_candidate.LocalCandidateMaterializationReceipt.__module__.startswith(
                "kaliv_dev_control._compatibility_v1."
            )
        )
        self.assertEqual(
            importlib.import_module("kaliv_dev_control._compatibility_v1").__all__,
            (),
        )

    def test_supported_surface_remains_ed25519_v2_only(self) -> None:
        expected = {
            "AsymmetricPublisherAuthorizationLease",
            "AsymmetricPublisherAuthorizationVerifier",
            "PublisherAuthorizationVerifierV2",
            "PublisherReplayLedgerV2",
            "PublisherPreflightReceiptV2",
            "PublisherPostconditionReceiptV2",
            "PublisherReplayRecoveryReceiptV2",
        }
        self.assertTrue(expected.issubset(set(public_authorization.__all__)))
        for name in expected:
            self.assertTrue(hasattr(public_authorization, name), name)


if __name__ == "__main__":
    unittest.main()
