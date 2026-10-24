"""Regression checks for Android signing exposure path classification."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_android_signing.py"
spec = importlib.util.spec_from_file_location("audit_android_signing", MODULE_PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class SigningAuditTests(unittest.TestCase):
    def test_detects_private_signing_material(self):
        for path in (
            "android/signing/modelrig.keystore",
            "android/signing/new.jks",
            "android/signing/cert.p12",
            "android/signing/cert.PFX",
            "android/signing/keystore.properties",
        ):
            with self.subTest(path=path):
                self.assertTrue(audit.is_signing_material(path))

    def test_ignores_non_signing_files(self):
        for path in (
            "android/app/build.gradle.kts",
            "android/signing/README.md",
            "docs/keystore.properties",
            "android/signing/example.properties",
        ):
            with self.subTest(path=path):
                self.assertFalse(audit.is_signing_material(path))


if __name__ == "__main__":
    unittest.main()
