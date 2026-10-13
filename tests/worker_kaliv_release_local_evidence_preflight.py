#!/usr/bin/env python3
"""Regression tests for the release preflight's fail-closed filesystem boundary."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kaliv_release_local_evidence_preflight as preflight


class PreflightFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text("{}", encoding="utf-8")
        self.ledger = self.root / "ledger.json"
        self.source = self.root / "source.json"
        self.source.write_text('{"ok":true}', encoding="utf-8")
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.gate = "software_exact_green"
        self.ref = "canonical-ref"
        self.ledger.write_text(json.dumps({self.gate: {
            "ref": self.ref, "path": "source.json", "sha256": self.sha
        }}), encoding="utf-8")

    def run_check(self):
        class Verdict:
            release_ready = True
        with patch("kaliv_system_release_gate.load_manifest", return_value={
            "gates": {self.gate: {"evidence_refs": [self.ref]}}
        }), patch("kaliv_system_release_gate.evaluate_manifest", return_value=Verdict()), patch(
            "kaliv_system_release_gate.REQUIRED_GATES", (self.gate,)
        ):
            return preflight.check(self.manifest, self.ledger)

    def test_valid_local_bytes_never_grant_release(self):
        result = self.run_check()
        self.assertEqual(result["state"], "LOCAL_BYTES_MATCH")
        self.assertFalse(result["release_ready"])
        self.assertFalse(result["production_activation"])
        self.assertFalse(result["physical_provenance_verified"])

    def test_modified_bytes_rejected(self):
        self.source.write_text('{"ok":false}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.run_check()

    def test_attacker_replaces_bytes_and_ledger_still_cannot_authorize(self):
        self.source.write_text('{"forged":true}', encoding="utf-8")
        value = json.loads(self.ledger.read_text(encoding="utf-8"))
        value[self.gate]["sha256"] = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.ledger.write_text(json.dumps(value), encoding="utf-8")
        result = self.run_check()
        self.assertEqual(result["state"], "LOCAL_BYTES_MATCH")
        self.assertFalse(result["physical_provenance_verified"])
        self.assertFalse(result["human_approval_verified"])
        self.assertFalse(result["release_ready"])
        self.assertFalse(result["production_activation"])

    def test_missing_source_rejected(self):
        self.source.unlink()
        with self.assertRaises(ValueError):
            self.run_check()

    def test_mismatched_ref_rejected(self):
        value = json.loads(self.ledger.read_text())
        value[self.gate]["ref"] = "forged-ref"
        self.ledger.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "reference mismatch"):
            self.run_check()

    def test_traversal_rejected(self):
        value = json.loads(self.ledger.read_text())
        value[self.gate]["path"] = "../outside.json"
        self.ledger.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.run_check()

    def test_structural_block_never_reads_evidence(self):
        class Verdict:
            release_ready = False
        with patch("kaliv_system_release_gate.load_manifest", return_value={}), patch(
            "kaliv_system_release_gate.evaluate_manifest", return_value=Verdict()
        ):
            with self.assertRaisesRegex(ValueError, "structural release gate is BLOCKED"):
                preflight.check(self.manifest, self.ledger)

    def test_oversized_ledger_rejected(self):
        with self.ledger.open("ab") as stream:
            stream.write(b" " * (preflight.MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "ledger oversized"):
            self.run_check()

    def test_oversized_evidence_rejected(self):
        with self.source.open("ab") as stream:
            stream.write(b" " * (preflight.MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "oversized evidence"):
            self.run_check()

    def test_symlinked_ledger_rejected(self):
        real = self.root / "real-ledger.json"
        self.ledger.rename(real)
        try:
            self.ledger.symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "symlinked"):
            self.run_check()

    def test_symlinked_parent_rejected(self):
        directory = self.root / "real"
        directory.mkdir()
        self.source.rename(directory / "source.json")
        alias = self.root / "alias"
        try:
            alias.symlink_to(directory, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        value = json.loads(self.ledger.read_text())
        value[self.gate]["path"] = "alias/source.json"
        self.ledger.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "symlinked"):
            self.run_check()


if __name__ == "__main__":
    unittest.main()
