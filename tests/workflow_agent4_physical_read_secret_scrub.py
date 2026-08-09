#!/usr/bin/env python3
"""A4-18 must not persist pairing credentials into acceptance evidence."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINALIZE = ROOT / "scripts" / "agent4-physical-read-finalize.ps1"
HARDENING = ROOT / "scripts" / "agent4_physical_read_audit_hardening.py"


class Agent4PhysicalReadSecretScrubTests(unittest.TestCase):
    def test_finalizer_removes_raw_pairing_code_from_persistent_state(self) -> None:
        source = FINALIZE.read_text(encoding="utf-8")
        self.assertIn('$state.PSObject.Properties["pairing_code"]', source)
        self.assertIn('$state.PSObject.Properties.Remove("pairing_code")', source)
        self.assertLess(
            source.index('$state.PSObject.Properties.Remove("pairing_code")'),
            source.index("Write-OperatorState -State $state"),
        )

    def test_auditor_rejects_raw_pairing_and_device_credentials(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        for required in (
            "pairing_code",
            "device_token",
            "bearer_token",
            "admin_key",
            "authorization",
            "admin-key.txt",
            "scan_runtime_evidence(repo_root)",
        ):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
