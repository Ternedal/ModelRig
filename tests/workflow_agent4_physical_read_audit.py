#!/usr/bin/env python3
"""A4-18 receipt-auditor contracts."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = ROOT / "scripts" / "agent4-physical-read-audit.ps1"
HARDENING = ROOT / "scripts" / "agent4_physical_read_audit_hardening.py"
CREDENTIAL_GUARD = ROOT / "scripts" / "agent4_physical_read_credential_guard.py"
EXACT_GATE = ROOT / "scripts" / "agent4_physical_read_exact_head_gate.py"
SDK_GATE = ROOT / "scripts" / "agent4_physical_read_sdk_check.py"
LAUNCHER = ROOT / "AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd"
DOC = ROOT / "docs" / "AGENT_4_A4_18_RECEIPT_AUDIT.md"

spec = importlib.util.spec_from_file_location("agent4_physical_read_credential_guard", CREDENTIAL_GUARD)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load Agent 4 physical credential guard")
credential_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credential_guard)


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

    def test_hardening_binds_mutations_to_hashed_artifacts(self) -> None:
        source = HARDENING.read_text(encoding="utf-8")
        for required in (
            "validate_mutations(repo_root, receipt)",
            'if key != "receipt_sha256"',
            "sha256_value(unsigned) == claimed",
            'prefix = f"mutation-{mode}-"',
            "len(candidates) == 1",
            "validate_file_receipt(",
            "artifact_data == mutation",
            "matcher ikke den hash-listede artifact-fil",
        ):
            self.assertIn(required, source)

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

    def test_a4_25_guard_rejects_raw_device_token_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential-lignende"):
            credential_guard.scan_value_credentials({"note": "a" * 64})

    def test_a4_25_guard_rejects_unlabelled_pairing_code_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential-lignende"):
            credential_guard.scan_value_credentials({"note": "ABCD" + "-" + "EFGH"})

    def test_a4_25_guard_rejects_normalized_alias_keys(self) -> None:
        for key in ("deviceToken", "pairing-code", "AuthorizationHeader", "clientSecretValue"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "forbudt credential-felt"):
                    credential_guard.scan_value_credentials({"debug": {key: "redacted-value"}})

    def test_a4_26_guard_rejects_sha256_prefixed_raw_token_in_free_text(self) -> None:
        disguised = "sha256:" + "a" * 64
        with self.assertRaisesRegex(ValueError, "credential-lignende"):
            credential_guard.scan_value_credentials({"note": disguised})
        with self.assertRaisesRegex(ValueError, "credential-lignende"):
            credential_guard.scan_text_credentials(disguised, label="runtime log")

    def test_a4_26_guard_rejects_attacker_named_sha256_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential-lignende"):
            credential_guard.scan_value_credentials(
                {"debug": {"sha256": "sha256:" + "a" * 64}}
            )

    def test_a4_26_guard_preserves_only_canonical_hash_slots(self) -> None:
        digest = "sha256:" + "0" * 64
        credential_guard.scan_value_credentials(
            {
                "schema": credential_guard.RECEIPT_SCHEMA,
                "receipt_sha256": digest,
                "fixture": {
                    "schema": credential_guard.FIXTURE_SCHEMA,
                    "latest_timeline_hash": digest,
                    "evidence_head_hash": digest,
                    "first_payload_sha256": digest,
                    "last_payload_sha256": digest,
                },
                "artifacts": [
                    {"path": "validation/example.json", "size_bytes": 12, "sha256": digest}
                ],
                "cleanup": {"admin_key_deleted": True},
                "trials": {
                    "grant_same_token_200": {
                        "status": "pass",
                        "payload_sha256": digest,
                        "cursor_sha256": digest,
                        "screenshot": digest,
                    }
                },
                "safety_hardening": {
                    "schema": credential_guard.SAFETY_EVIDENCE_SCHEMA,
                    "pixel_serial_sha256": digest,
                    "binding_file": {
                        "path": "validation/agent4-physical-runtime/safety-binding.json",
                        "size_bytes": 12,
                        "sha256": digest,
                    },
                },
            }
        )

    def test_a4_26_guard_preserves_canonical_runtime_hash_slots(self) -> None:
        digest = "sha256:" + "1" * 64
        credential_guard.scan_value_credentials(
            {
                "schema": credential_guard.TIMELINE_ENTRY_SCHEMA,
                "previous_hash": digest,
                "entry_hash": digest,
                "evidence": [
                    {
                        "evidence_id": "e-1",
                        "media_type": "application/json",
                        "location": "physical-artifacts/e-1.json",
                        "sha256": digest,
                        "size_bytes": 10,
                        "metadata": {},
                    }
                ],
            },
            path="runtime.validation/agent4-physical-runtime/data/a.timeline.json",
        )
        credential_guard.scan_value_credentials(
            {
                "schema": credential_guard.EVIDENCE_RECORD_SCHEMA,
                "timeline_head_hash": digest,
                "previous_hash": digest,
                "record_hash": digest,
                "evidence": {
                    "evidence_id": "e-1",
                    "media_type": "application/json",
                    "location": "physical-artifacts/e-1.json",
                    "sha256": digest,
                    "size_bytes": 10,
                    "metadata": {},
                },
            },
            path="runtime.validation/agent4-physical-runtime/data/a.evidence.json",
        )

    def test_a4_26_guard_is_path_aware_and_json_structured(self) -> None:
        source = CREDENTIAL_GUARD.read_text(encoding="utf-8")
        for required in (
            "SCHEMA_HASH_FIELDS",
            "_canonical_hash_slot",
            "SHA256_VALUE_RE",
            "RAW_DEVICE_TOKEN_RE = re.compile(r\"\\b[0-9a-f]{64}\\b\")",
            "if path.suffix.lower() == \".json\"",
            "scan_value_credentials(value, path=f\"runtime.{relative}\")",
            "scan_text_credentials(text, label=f\"runtime evidence {relative}\")",
        ):
            self.assertIn(required, source)
        self.assertNotIn("(?<!sha256:)", source)

    def test_a4_25_guard_is_read_only_and_covers_runtime_text(self) -> None:
        source = CREDENTIAL_GUARD.read_text(encoding="utf-8")
        for required in (
            "RAW_DEVICE_TOKEN_RE",
            "RAW_PAIRING_CODE_RE",
            "FORBIDDEN_CREDENTIAL_KEY_TERMS",
            "scan_value_credentials",
            "scan_runtime_evidence",
            "object_pairs_hook=reject_duplicate_object_pairs",
        ):
            self.assertIn(required, source)
        for forbidden in ("requests", "socket", "subprocess", "unlink(", "write_text(", "write_bytes("):
            self.assertNotIn(forbidden, source)

    def test_launcher_runs_all_python_gates_before_legacy_audit(self) -> None:
        launcher = LAUNCHER.read_text(encoding="utf-8")
        exact = launcher.index("agent4_physical_read_exact_head_gate.py")
        sdk = launcher.index("agent4_physical_read_sdk_check.py")
        credential = launcher.index("agent4_physical_read_credential_guard.py")
        hardening = launcher.index("agent4_physical_read_audit_hardening.py")
        legacy = launcher.index("agent4-physical-read-audit.ps1")
        self.assertLess(exact, sdk)
        self.assertLess(sdk, credential)
        self.assertLess(credential, hardening)
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