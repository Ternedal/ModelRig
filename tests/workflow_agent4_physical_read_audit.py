#!/usr/bin/env python3
"""A4-18 receipt-auditor contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = ROOT / "scripts" / "agent4-physical-read-audit.ps1"
HARDENING = ROOT / "scripts" / "agent4_physical_read_audit_hardening.py"
EXACT_GATE = ROOT / "scripts" / "agent4_physical_read_exact_head_gate.py"
SDK_GATE = ROOT / "scripts" / "agent4_physical_read_sdk_check.py"
LAUNCHER = ROOT / "AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd"
DOC = ROOT / "docs" / "AGENT_4_A4_18_RECEIPT_AUDIT.md"


class Agent4PhysicalReadAuditTests(unittest.TestCase):
    def test_legacy_auditor_remains_fail_closed(self) -> None:
        source = AUDITOR.read_text(encoding="utf-8")
        for required in (
            "modelrig-agent4/physical-read-receipt/v2",
            "218019fd47ea90b046a334253ab5fd84485f772a",
            "503d4a61b7d7742a34282eb35a1373f0ccacf023",
            "receipt_sha256",
            "all_required_observations_passed",
            "credential_data_included",
            "public_network",
            "production_activation",
            "unknown_process_preserved",
            "git.remote_main",
            "git.remote_head",
            "if ($errors.Count -ne 0) { exit 2 }",
        ):
            self.assertIn(required, source)
        self.assertNotIn("Invoke-WebRequest", source)
        self.assertNotIn("Start-Process", source)

    def test_exact_head_gate_rejects_superseded_authority(self) -> None:
        source = EXACT_GATE.read_text(encoding="utf-8")
        for required in (
            "SUPSERSEDED_HEADS",
            "Expected SHA er superseded",
            "Local HEAD matcher ikke den eksplicit forventede SHA",
            "Receiptens expected_sha/observed_head matcher ikke authority",
            "ab7448280135f7be575a2050123ce020639aab61",
            "ce6cbbbd02003f6e35cf2986c7b24b326add5fee",
            "dc8982b2ecae47566da22b9cde180922ef228e10",
        ):
            self.assertIn(required, source)

    def test_numeric_sdk_gate_is_read_only(self) -> None:
        source = SDK_GATE.read_text(encoding="utf-8")
        self.assertIn('pixel.get("sdk")', source)
        self.assertIn("sdk.isdigit()", source)
        self.assertIn("Pixel SDK skal være en numerisk streng", source)
        for forbidden in ("requests", "subprocess", "unlink(", "write_text(", "write_bytes("):
            self.assertNotIn(forbidden, source)

    def test_hardening_requires_exact_known_trial_set(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
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
        self.assertIn("actual == REQUIRED_TRIALS", source)
        self.assertIn("præcis de 21 kendte checkpoints", source)

    def test_hardening_recomputes_nested_mutation_digests(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        self.assertIn("validate_mutations", source)
        self.assertIn('if key != "receipt_sha256"', source)
        self.assertIn("sha256_value(unsigned) == claimed", source)
        self.assertIn("digest matcher ikke indholdet", source)

    def test_hardening_validates_complete_safety_binding(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        for required in (
            "modelrig-agent4/physical-read-safety-evidence/v1",
            "modelrig-agent4/physical-read-safety-binding/v1",
            "artifacts_hashed_after_prestop",
            "wildcard_binding",
            "worker_bound_address",
            "firewall_local_address",
            "firewall_remote_scope",
            "DomainAuthenticated",
            "validation/agent4-physical-runtime/safety-binding.json",
            "binding_data",
            "pixel_android_release",
            "pixel_sdk",
            "require_rfc1918",
        ):
            self.assertIn(required, source)
        self.assertNotIn("requests", source)
        self.assertNotIn("subprocess.Popen", source)

    def test_hardening_scans_runtime_and_rejects_screenshots(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        for required in (
            "scan_runtime_evidence",
            "CREDENTIAL_PATTERNS",
            "authorization",
            "bearer",
            "MODELRIG_ADMIN_KEY",
            "pairing_code",
            "device_token",
            "admin-key.txt",
            "credential-lignende indhold fundet",
            "billedevidence kan ikke credential-verificeres maskinelt",
            "screenshot kan ikke credential-verificeres maskinelt",
            "brug en redigeret tekstobservation",
        ):
            self.assertIn(required, source)
        self.assertIn("scan_runtime_evidence(repo_root)", source)

    def test_launcher_runs_all_python_gates_before_legacy_audit(self) -> None:
        launcher = LAUNCHER.read_text(encoding="utf-8")
        exact = launcher.index("agent4_physical_read_exact_head_gate.py")
        sdk = launcher.index("agent4_physical_read_sdk_check.py")
        hardening = launcher.index("agent4_physical_read_audit_hardening.py")
        legacy = launcher.index("agent4-physical-read-audit.ps1")
        self.assertLess(exact, sdk)
        self.assertLess(sdk, hardening)
        self.assertLess(hardening, legacy)
        self.assertIn("40-tegns-exact-SHA", launcher)
        self.assertIn("--expected-sha", launcher)
        self.assertIn("-RequireRemoteRefs", launcher)
        self.assertIn("Issue #421 maa ikke lukkes", launcher)

    def test_documentation_keeps_pass_fail_boundary(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd", doc)
        self.assertIn("`0`: `PASS`", doc)
        self.assertIn("`2`: `FAIL`", doc)
        self.assertIn("ikke en digital signatur", doc)
        self.assertIn("redigerede tekstobservationer", doc)
        self.assertIn("runtime-evidensfiler", doc)


if __name__ == "__main__":
    unittest.main()
