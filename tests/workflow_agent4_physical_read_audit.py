#!/usr/bin/env python3
"""A4-18 receipt-auditor contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = ROOT / "scripts" / "agent4-physical-read-audit.ps1"
HARDENING = ROOT / "scripts" / "agent4-physical-read-audit-hardening.ps1"
LAUNCHER = ROOT / "AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd"
DOC = ROOT / "docs" / "AGENT_4_A4_18_RECEIPT_AUDIT.md"


class Agent4PhysicalReadAuditTests(unittest.TestCase):
    def test_auditor_is_fail_closed(self) -> None:
        source = AUDITOR.read_text(encoding="utf-8")
        for required in (
            'modelrig-agent4/physical-read-receipt/v2',
            '218019fd47ea90b046a334253ab5fd84485f772a',
            '503d4a61b7d7742a34282eb35a1373f0ccacf023',
            'receipt_sha256',
            'all_required_observations_passed',
            'credential_data_included',
            'public_network',
            'production_activation',
            'unknown_process_preserved',
            'git.remote_main',
            'git.remote_head',
            'if ($errors.Count -ne 0) { exit 2 }',
        ):
            self.assertIn(required, source)
        self.assertIn('ConvertTo-Json -Depth 30 -Compress', source)
        self.assertIn('Get-FileHash -LiteralPath $file -Algorithm SHA256', source)
        self.assertNotIn('Invoke-WebRequest', source)
        self.assertNotIn('Start-Process', source)

    def test_all_21_checkpoints_are_named(self) -> None:
        source = AUDITOR.read_text(encoding="utf-8")
        checkpoints = (
            "default_off_feature_locked", "default_off_no_worker_fallback",
            "paired_without_grant_403", "paired_without_grant_locked_no_stale",
            "grant_same_token_200", "campaign_paging_no_loss",
            "timeline_paging_no_loss", "evidence_paging_no_loss",
            "detail_verification_matches", "no_write_controls",
            "stale_campaign_record_422", "stale_summary_422",
            "revoke_same_token_403", "revoke_clears_data",
            "restart_does_not_restore_grant", "regrant_same_token_200",
            "backend_restart_recovery", "worker_restart_recovery",
            "network_recovery", "malformed_schema_fail_closed",
            "not_found_fail_closed",
        )
        self.assertEqual(len(checkpoints), 21)
        for checkpoint in checkpoints:
            self.assertIn(f'"{checkpoint}"', source)

    def test_hardening_rejects_ambiguous_receipts(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        for required in (
            '$unexpected.Count -ne 0',
            '$trialNames.Count -ne $requiredTrials.Count',
            "Pixel SDK skal være numerisk",
            "Der skal være præcis to mutation receipts",
            'Get-WithoutReceiptDigest -Object $mutation',
            'ConvertTo-Json -Depth 30 -Compress',
            "Mutation receipt digest mismatch",
        ):
            self.assertIn(required, source)
        self.assertNotIn("Invoke-WebRequest", source)
        self.assertNotIn("Start-Process", source)
        self.assertNotIn("Remove-Item", source)

    def test_launcher_chains_main_audit_then_hardening(self) -> None:
        launcher = LAUNCHER.read_text(encoding="utf-8")
        main_index = launcher.index("agent4-physical-read-audit.ps1")
        hardening_index = launcher.index("agent4-physical-read-audit-hardening.ps1")
        self.assertLess(main_index, hardening_index)
        self.assertIn('if "%RC%"=="0"', launcher)
        self.assertIn('set "RC=%ERRORLEVEL%"', launcher)
        self.assertIn("-RequireRemoteRefs", launcher)
        self.assertIn("Issue #421 maa ikke lukkes", launcher)

    def test_launcher_and_doc_require_pass(self) -> None:
        launcher = LAUNCHER.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("agent4-physical-read-audit.ps1", launcher)
        self.assertIn("`0`: `PASS`", doc)
        self.assertIn("`2`: `FAIL`", doc)
        self.assertIn("ikke en digital signatur", doc)


if __name__ == "__main__":
    unittest.main()
