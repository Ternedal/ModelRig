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
        hardening = HARDENING.read_text(encoding="utf-8")
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
            self.assertIn(f'"{checkpoint}"', hardening)
        self.assertIn("Trials skal indeholde præcis 21 checkpoints", hardening)
        self.assertIn("manglende eller ukendte checkpoints", hardening)

    def test_hardening_recomputes_nested_digests_and_safety_evidence(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        for required in (
            "Assert-MutationDigests",
            'Get-ObjectWithoutProperty -Object $item -ExcludedName "receipt_sha256"',
            "Mutation $mode digest matcher ikke indholdet",
            "Assert-SafetyHardening",
            "modelrig-agent4/physical-read-safety-evidence/v1",
            "artifacts_hashed_after_prestop",
            "wildcard_binding",
            "worker_bound_address",
            "firewall_remote_scope",
            "validation/agent4-physical-runtime/safety-binding.json",
            "Pixel-model i receipt og safety evidence matcher ikke",
        ):
            self.assertIn(required, source)

    def test_hardening_validates_ui_observations_and_screenshot_bytes(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        for required in (
            "Assert-UiEvidence",
            "Assert-ScreenshotReceipt",
            "validation/agent4-physical-runtime/",
            "Get-FileHash -LiteralPath $file -Algorithm SHA256",
            "mangler både redigeret screenshot og menneskelig UI-observation",
        ):
            self.assertIn(required, source)
        self.assertNotIn("Invoke-WebRequest", source)
        self.assertNotIn("Start-Process", source)

    def test_launcher_routes_through_mandatory_hardening(self) -> None:
        launcher = LAUNCHER.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("agent4-physical-read-audit-hardening.ps1", launcher)
        self.assertNotIn('scripts\\agent4-physical-read-audit.ps1"', launcher)
        self.assertIn("-RequireRemoteRefs", launcher)
        self.assertIn("Issue #421 maa ikke lukkes", launcher)
        self.assertIn("`0`: `PASS`", doc)
        self.assertIn("`2`: `FAIL`", doc)
        self.assertIn("ikke en digital signatur", doc)


if __name__ == "__main__":
    unittest.main()
