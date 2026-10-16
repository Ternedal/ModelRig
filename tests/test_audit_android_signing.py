"""Tests for the read-only signing-material inventory."""
import importlib.util
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_android_signing.py"
spec = importlib.util.spec_from_file_location("audit_android_signing", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SigningInventoryTest(unittest.TestCase):
    @patch.object(module.subprocess, "run")
    def test_redacts_property_values_and_lists_paths(self, run):
        run.return_value = CompletedProcess([], 0, b"android/signing/keystore.properties\0android/signing/modelrig.keystore\0", b"")
        result = module.inventory()
        self.assertEqual(result["finding"], "TRACKED_SIGNING_MATERIAL")
        self.assertEqual(len(result["exposed_paths"]), 2)
        self.assertNotIn("password", str(result).lower())
        run.assert_called_once()

    @patch.object(module.subprocess, "run")
    def test_baseline_flags_new_key_without_exposing_content(self, run):
        run.return_value = CompletedProcess([], 0, b"android/signing/modelrig.keystore\0android/signing/extra.jks\0", b"")
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "baseline.json"
            baseline.write_text(json.dumps(["android/signing/modelrig.keystore"]), encoding="utf-8")
            with patch.object(module.sys, "argv", ["audit", "--baseline", str(baseline)]):
                with patch("builtins.print") as output:
                    self.assertEqual(module.main(), 1)
                payload = json.loads(output.call_args.args[0])
                self.assertEqual(payload["new_paths"], ["android/signing/extra.jks"])

    @patch.object(module.subprocess, "run")
    def test_empty_inventory(self, run):
        run.return_value = CompletedProcess([], 0, b"", b"")
        self.assertEqual(module.inventory()["finding"], "NO_TRACKED_SIGNING_MATERIAL")


if __name__ == "__main__":
    unittest.main()
