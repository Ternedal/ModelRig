#!/usr/bin/env python3
"""Adversarial contract for the not-yet-provisioned independent authority."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kaliv_independent_release_authority as authority


class IndependentAuthorityTests(unittest.TestCase):
    def _evaluate(self, structural_state, structural_ready):
        verdict = SimpleNamespace(
            release_id="kaliv-rc-test",
            state=structural_state,
            release_ready=structural_ready,
        )
        with patch.object(authority.gate, "load_manifest", return_value={
            "gates": {"synthetic": {"status": "PASS", "evidence_refs": ["forged"]}}
        }), patch.object(authority.gate, "evaluate_manifest", return_value=verdict):
            return authority.evaluate(Path("synthetic.json"))

    def test_synthetic_ten_pass_structural_qualified_is_not_authorized(self):
        result = self._evaluate("QUALIFIED", True)
        self.assertEqual(result["structural_state"], "QUALIFIED")
        self.assertTrue(result["structural_release_ready"])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["independent_provenance_verified"])
        self.assertFalse(result["release_ready"])
        self.assertFalse(result["production_activation"])

    def test_structural_block_remains_blocked(self):
        result = self._evaluate("BLOCKED", False)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["release_ready"])

    def test_no_caller_supplied_trust_override(self):
        result = self._evaluate("QUALIFIED", True)
        self.assertNotIn("override", result)
        self.assertFalse(result["human_approval_verified"])
        self.assertFalse(result["production_activation"])


if __name__ == "__main__":
    unittest.main()
