#!/usr/bin/env python3
"""A4-18 physical runbook stays aligned with the fail-closed harness."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "AGENT_4_A4_18_PHYSICAL_READ_PRODUCT.md"


class Agent4PhysicalReadRunbookTests(unittest.TestCase):
    def test_runbook_binds_exact_head_and_all_stable_launchers(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("$ExpectedSha = (git rev-parse HEAD).Trim()", source)
        self.assertIn("git status --porcelain", source)
        for launcher in (
            "START_AGENT4_PHYSICAL_READ_TEST.cmd",
            "ENABLE_AGENT4_PHYSICAL_READ_TEST.cmd",
            "GRANT_AGENT4_PHYSICAL_READ_TEST.cmd",
            "MUTATE_AGENT4_CAMPAIGN_SNAPSHOT.cmd",
            "MUTATE_AGENT4_SUMMARY_SNAPSHOT.cmd",
            "RESTART_AGENT4_PHYSICAL_WORKER.cmd",
            "RESTART_AGENT4_PHYSICAL_BACKEND.cmd",
            "REVOKE_AGENT4_PHYSICAL_READ_TEST.cmd",
            "REGRANT_AGENT4_PHYSICAL_READ_TEST.cmd",
            "STATUS_AGENT4_PHYSICAL_READ_TEST.cmd",
            "FINALIZE_AGENT4_PHYSICAL_READ_TEST.cmd",
            "STOP_AGENT4_PHYSICAL_READ_TEST.cmd",
        ):
            self.assertIn(launcher, source)

    def test_runbook_requires_every_checkpoint_family(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")
        for checkpoint in (
            "default_off_feature_locked",
            "default_off_no_worker_fallback",
            "paired_without_grant_403",
            "paired_without_grant_locked_no_stale",
            "grant_same_token_200",
            "campaign_paging_no_loss",
            "timeline_paging_no_loss",
            "evidence_paging_no_loss",
            "detail_verification_matches",
            "no_write_controls",
            "stale_campaign_record_422",
            "stale_summary_422",
            "worker_restart_recovery",
            "backend_restart_recovery",
            "network_recovery",
            "malformed_schema_fail_closed",
            "not_found_fail_closed",
            "revoke_same_token_403",
            "revoke_clears_data",
            "restart_does_not_restore_grant",
            "regrant_same_token_200",
        ):
            self.assertIn(checkpoint, source)

    def test_runbook_preserves_security_and_receipt_boundary(self) -> None:
        source = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "127.0.0.1:8099",
            "LocalSubnet",
            "GO til NO-GO",
            "credential-fri",
            "public_network=false",
            "production_activation=false",
            "dræber aldrig en proces",
        ):
            self.assertIn(required, source)
        self.assertNotIn("MODELRIG_ADMIN_KEY=", source)
        self.assertNotIn("Authorization: Bearer", source)


if __name__ == "__main__":
    unittest.main()
