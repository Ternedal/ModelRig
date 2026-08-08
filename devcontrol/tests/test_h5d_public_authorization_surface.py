from __future__ import annotations

import ast
import importlib
import inspect
import unittest
from pathlib import Path

import kaliv_dev_control.publisher_authorization as public_authorization
from kaliv_dev_control import _publisher_authorization_legacy as static_support


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

    def test_rejected_legacy_files_are_not_distributed(self) -> None:
        package_root = Path(public_authorization.__file__).parent
        self.assertFalse((package_root / "_publisher_authorization_legacy.py").exists())
        self.assertFalse((package_root / "_compatibility_v1").exists())
        support_source = inspect.getsource(static_support)
        for forbidden in (
            "import hmac",
            "HmacPublisherAuthorizationIssuer",
            "TrustedAuthorizationIssuerKey",
            "Ed25519PrivateKey",
            "private_key",
            ".sign(",
            "subprocess",
            "requests.",
            "urllib",
        ):
            self.assertNotIn(forbidden, support_source)

    def test_static_support_is_a_package_not_dynamic_proxy(self) -> None:
        module = importlib.import_module(
            "kaliv_dev_control._publisher_authorization_legacy"
        )
        self.assertTrue(Path(module.__file__).name == "__init__.py")
        source = inspect.getsource(module)
        self.assertNotIn("globals().update", source)
        self.assertNotIn("sys.modules", source)

    def test_supported_surface_remains_ed25519_v2_v3_only(self) -> None:
        expected = {
            "AsymmetricPublisherAuthorizationLease",
            "AsymmetricPublisherAuthorizationVerifier",
            "PublisherAuthorizationVerifierV2",
            "PublisherReplayLedgerV2",
            "PublisherReplayLedgerV3",
            "PublisherPreflightReceiptV2",
            "PublisherPostconditionReceiptV2",
            "PublisherReplayRecoveryReceiptV2",
            "PublisherReplayRecoveryReceiptV3",
        }
        self.assertTrue(expected.issubset(set(public_authorization.__all__)))
        for name in expected:
            self.assertTrue(hasattr(public_authorization, name), name)


if __name__ == "__main__":
    unittest.main()
