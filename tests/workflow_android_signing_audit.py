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


    def test_audit_mode_does_not_block_legacy_files(self):
        from unittest.mock import patch
        with patch.object(audit, "tracked_signing_files", return_value=["android/signing/modelrig.keystore"]):
            self.assertEqual(audit.main([]), 0)

    def test_enforce_mode_blocks_legacy_files(self):
        from unittest.mock import patch
        with patch.object(audit, "tracked_signing_files", return_value=["android/signing/modelrig.keystore"]):
            self.assertEqual(audit.main(["--enforce"]), 1)

    def test_enforce_mode_passes_after_migration(self):
        from unittest.mock import patch
        with patch.object(audit, "tracked_signing_files", return_value=[]):
            self.assertEqual(audit.main(["--enforce"]), 0)


if __name__ == "__main__":
    unittest.main()
