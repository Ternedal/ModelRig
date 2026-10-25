"""Contract tests for the APK certificate fingerprint gate."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_android_apk_certificate.py"
spec = importlib.util.spec_from_file_location("apk_certificate_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

A = "ab" * 32
B = "cd" * 32


class ApkCertificateGateTests(unittest.TestCase):
    def test_normalize_colon_separated(self):
        self.assertEqual(gate.normalize_digest(":".join(["ab"] * 32)), A)

    def test_invalid_digest_rejected(self):
        for value in ["", "abc", "zz" * 32, "a" * 65]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    gate.normalize_digest(value)

    def test_extract_exact_signer_line(self):
        self.assertEqual(gate.extract_signer_digests(
            "Signer #1 certificate SHA-256 digest: " + A + "\n"
        ), [A])

    @patch.object(gate.subprocess, "run")
    def test_matching_single_signer(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "Signer #1 certificate SHA-256 digest: " + A, "")
        gate.verify("apksigner", "test.apk", A)
        run.assert_called_once()

    @patch.object(gate.subprocess, "run")
    def test_mismatched_signer_rejected(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "Signer #1 certificate SHA-256 digest: " + B, "")
        with self.assertRaisesRegex(ValueError, "does not match"):
            gate.verify("apksigner", "test.apk", A)

    @patch.object(gate.subprocess, "run")
    def test_missing_or_multiple_signers_rejected(self, run):
        for output in ["", "Signer #1 certificate SHA-256 digest: " + A + "\nSigner #2 certificate SHA-256 digest: " + B]:
            run.return_value = subprocess.CompletedProcess([], 0, output, "")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                gate.verify("apksigner", "test.apk", A)

    @patch.object(gate.subprocess, "run")
    def test_invalid_signature_rejected(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "")
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            gate.verify("apksigner", "test.apk", A)


if __name__ == "__main__":
    unittest.main()
