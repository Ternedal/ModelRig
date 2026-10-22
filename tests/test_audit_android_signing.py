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


    @patch.object(module.subprocess, "run")
    def test_blob_baseline_rejects_changed_existing_signing_identity(self, run):
        original_sha = "a" * 40
        changed_sha = "b" * 40
        tracked = "android/signing/modelrig.keystore"
        run.side_effect = [
            CompletedProcess([], 0, (tracked + "\0").encode(), b""),
            CompletedProcess([], 0, f"100644 {changed_sha} 0\t{tracked}\0".encode(), b""),
        ]
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "known-blobs.json"
            baseline.write_text(json.dumps({tracked: original_sha}), encoding="utf-8")
            with patch.object(module.sys, "argv", ["audit", "--blob-baseline", str(baseline)]):
                with patch("builtins.print") as output:
                    self.assertEqual(module.main(), 1)
                report = json.loads(output.call_args.args[0])
                self.assertEqual(report["changed_pinned_paths"], [tracked])
                self.assertEqual(report["unpinned_blob_paths"], [])
                self.assertNotIn(original_sha, output.call_args.args[0])
                self.assertNotIn(changed_sha, output.call_args.args[0])
        self.assertEqual(run.call_count, 2)

    @patch.object(module.subprocess, "run")
    def test_blob_baseline_accepts_unchanged_signing_identity(self, run):
        sha = "a" * 40
        path = "android/signing/modelrig.keystore"
        run.side_effect = [
            CompletedProcess([], 0, (path + "\0").encode(), b""),
            CompletedProcess([], 0, f"100644 {sha} 0\t{path}\0".encode(), b""),
        ]
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "known-blobs.json"
            baseline.write_text(json.dumps({path: sha}), encoding="utf-8")
            with patch.object(module.sys, "argv", ["audit", "--blob-baseline", str(baseline)]):
                with patch("builtins.print") as output:
                    self.assertEqual(module.main(), 0)
                report = json.loads(output.call_args.args[0])
                self.assertEqual(report["changed_pinned_paths"], [])
                self.assertEqual(report["unpinned_blob_paths"], [])

    @patch.object(module.subprocess, "run")
    def test_blob_baseline_fails_closed_if_known_key_removed(self, run):
        path = "android/signing/modelrig.keystore"
        run.side_effect = [
            CompletedProcess([], 0, b"", b""),
            CompletedProcess([], 0, b"", b""),
        ]
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "known-blobs.json"
            baseline.write_text(json.dumps({path: "a" * 40}), encoding="utf-8")
            with patch.object(module.sys, "argv", ["audit", "--blob-baseline", str(baseline)]):
                with patch("builtins.print") as output:
                    self.assertEqual(module.main(), 1)
                report = json.loads(output.call_args.args[0])
                self.assertEqual(report["changed_pinned_paths"], [path])

    @patch.object(module.subprocess, "run")
    def test_blob_baseline_detects_new_credential_path(self, run):
        path = "android/signing/new-key.jks"
        pinned = "android/signing/modelrig.keystore"
        sha = "a" * 40
        run.side_effect = [
            CompletedProcess([], 0, (pinned + "\0" + path + "\0").encode(), b""),
            CompletedProcess([], 0, (
                f"100644 {sha} 0\t{pinned}\0"
                f"100644 {'b' * 40} 0\t{path}\0"
            ).encode(), b""),
        ]
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "known-blobs.json"
            baseline.write_text(json.dumps({pinned: sha}), encoding="utf-8")
            with patch.object(module.sys, "argv", ["audit", "--blob-baseline", str(baseline)]):
                with patch("builtins.print") as output:
                    self.assertEqual(module.main(), 1)
                report = json.loads(output.call_args.args[0])
                self.assertEqual(report["unpinned_blob_paths"], [path])

    @patch.object(module.subprocess, "run")
    def test_malformed_blob_baseline_fails_closed(self, run):
        run.return_value = CompletedProcess([], 0, b"", b"")
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "known-blobs.json"
            baseline.write_text(json.dumps({"android/signing/modelrig.keystore": "not-a-sha"}), encoding="utf-8")
            with patch.object(module.sys, "argv", ["audit", "--blob-baseline", str(baseline)]):
                self.assertEqual(module.main(), 2)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
