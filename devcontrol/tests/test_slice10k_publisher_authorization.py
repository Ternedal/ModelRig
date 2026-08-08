"""Historical v1 schema retention without v1 runtime authority."""
from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

import kaliv_dev_control.publisher_authorization as public_authorization

ROOT = Path(__file__).parents[1]


class HistoricalPublisherAuthorizationV1Tests(unittest.TestCase):
    def test_v1_schema_is_retained_as_data_only(self) -> None:
        schema = json.loads(
            (
                ROOT
                / "schemas"
                / "development-publisher-authorization-lease-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["algorithm"]["const"],
            "hmac-sha256",
        )
        self.assertNotIn(
            "HmacPublisherAuthorizationIssuer",
            public_authorization.__all__,
        )

    def test_v1_runtime_is_not_distributed(self) -> None:
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module(
                "kaliv_dev_control._compatibility_v1.publisher_authorization"
            )
        with self.assertRaises(ImportError):
            exec(
                "from kaliv_dev_control.publisher_authorization "
                "import HmacPublisherAuthorizationIssuer",
                {},
                {},
            )

    def test_static_support_has_no_issuer_or_secret_api(self) -> None:
        support = importlib.import_module(
            "kaliv_dev_control._publisher_authorization_legacy"
        )
        for name in (
            "HmacPublisherAuthorizationIssuer",
            "TrustedAuthorizationIssuerKey",
            "_secret",
            "_authorization_signature",
        ):
            self.assertFalse(hasattr(support, name), name)


if __name__ == "__main__":
    unittest.main()
