#!/usr/bin/env python3
"""Regression tests for the fail-closed A4-25f physical evidence auditor."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent4_a4_25f_audit as audit  # noqa: E402

EXPECTED_SHA = "a" * 40
SERIAL = "A4-25f-test-pixel"


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _file_ref(path: Path) -> dict[str, str]:
    return {"name": path.name, "sha256": audit._sha256_file(path)}


def _self_digest(value: dict[str, object], field: str) -> None:
    value[field] = "sha256:" + hashlib.sha256(audit._canonical_json(value)).hexdigest()


class A425fAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="modelrig-a4-25f-audit-")
        self.output = Path(self.temp.name).resolve()
        self._build_valid_evidence()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build_valid_evidence(self) -> None:
        _write_json(
            self.output / ".modelrig-a4-25f-output.json",
            {
                "schema": audit.OUTPUT_MARKER_SCHEMA,
                "production_activation": False,
            },
        )

        fixture: dict[str, object] = {
            "schema": audit.FIXTURE_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "root_snapshot_id": "root-1",
            "root_sequence": 1,
            "root_parent_snapshot_id": None,
            "campaign_count": 31,
            "external_dispatch": False,
            "background_runtime": False,
            "api_mounted": False,
            "public_network": False,
            "production_activation": False,
        }
        _self_digest(fixture, "manifest_sha256")
        _write_json(self.output / "fixture-manifest.json", fixture)

        mutation_refs: list[dict[str, str]] = []
        previous_root = "root-1"
        for index, mode in enumerate(audit.EXPECTED_MUTATION_MODES, start=1):
            next_root = f"root-{index + 1}"
            mutation: dict[str, object] = {
                "schema": audit.MUTATION_SCHEMA,
                "repository_sha": EXPECTED_SHA,
                "mode": mode,
                "mutation_id": f"mutation-{index}",
                "root_before": previous_root,
                "root_after": next_root,
                "root_sequence_before": index,
                "root_sequence_after": index + 1,
                "root_after_parent": previous_root,
                "pending_projections_after": 0,
                "external_dispatch": False,
                "background_runtime": False,
                "api_mounted": False,
                "public_network": False,
                "production_activation": False,
            }
            _self_digest(mutation, "receipt_sha256")
            path = self.output / "mutations" / f"{index + 1:04d}-{mode}.json"
            _write_json(path, mutation)
            mutation_refs.append(_file_ref(path))
            previous_root = next_root

        main_refs: list[dict[str, str]] = []
        for stage in sorted(audit.EXPECTED_MAIN_STAGES):
            receipt = {
                "schema": "modelrig-agent4/a4-25f-test-phone/v1",
                "stage": stage,
                "success": True,
                "credential_in_receipt": False,
                "raw_cursor_in_receipt": False,
                "production_activation": False,
            }
            path = self.output / "phone-receipts" / f"main-{stage}.json"
            _write_json(path, receipt)
            main_refs.append(_file_ref(path))

        matrix = {
            "schema": audit.MATRIX_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "package_name": audit.PACKAGE_NAME,
            "baseline_root": "root-1",
            "retained_detail_root": "root-3",
            "final_current_root": "root-6",
            "stage_count": len(audit.EXPECTED_MAIN_STAGES),
            "mutation_count": len(audit.EXPECTED_MUTATION_MODES),
            "mutation_receipts": mutation_refs,
            "phone_receipts": main_refs,
            "worker_restart_tested": True,
            "backend_restart_tested": True,
            "android_process_restart_tested": True,
            "expired_retained_root_tested": True,
            "selected_root_404_tested": True,
            "server_422_tested": True,
            "unavailable_503_tested": True,
            "credential_in_receipt": False,
            "raw_cursor_in_receipt": False,
            "public_network": False,
            "physical_execution": True,
            "production_activation": False,
        }
        matrix_path = self.output / "a4-25f-physical-matrix.json"
        _write_json(matrix_path, matrix)

        cursor_refs: list[dict[str, str]] = []
        for stage in audit.EXPECTED_CURSOR_STAGES:
            receipt = {
                "schema": "modelrig-agent4/a4-25f-cursor-probe/v1",
                "stage": stage,
                "success": True,
                "error_kind": "PROTOCOL",
                "local_rejection": True,
                "credential_in_receipt": False,
                "raw_cursor_in_receipt": False,
                "production_activation": False,
            }
            path = self.output / "phone-receipts" / f"a4-25f-cursor-{stage}.json"
            _write_json(path, receipt)
            cursor_refs.append(_file_ref(path))

        cursor_matrix = {
            "schema": audit.CURSOR_MATRIX_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "package_name": audit.PACKAGE_NAME,
            "adb_serial_sha256": audit._sha256_text(SERIAL),
            "stages": list(audit.EXPECTED_CURSOR_STAGES),
            "receipt_count": len(audit.EXPECTED_CURSOR_STAGES),
            "receipts": cursor_refs,
            "credential_in_receipt": False,
            "raw_cursor_in_receipt": False,
            "public_network": False,
            "physical_execution": True,
            "production_activation": False,
        }
        _write_json(self.output / "a4-25f-cursor-matrix.json", cursor_matrix)

        cleanup = {
            "schema": audit.CLEANUP_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "package_name": audit.PACKAGE_NAME,
            "package_removed": True,
            "firewall_rule_removed": True,
            "reserved_ports_closed": True,
            "backend_device_store_removed": True,
            "backend_process_removed": True,
            "worker_process_removed": True,
            "adb_serial_sha256": audit._sha256_text(SERIAL),
            "credential_in_receipt": False,
            "public_network": False,
            "physical_cleanup": True,
            "production_activation": False,
        }
        _write_json(self.output / "a4-25f-cleanup.json", cleanup)

        state = {
            "schema": audit.STATE_SCHEMA,
            "expected_sha": EXPECTED_SHA,
            "output_root": str(self.output),
            "phase": "stopped",
            "package_name": audit.PACKAGE_NAME,
            "adb_serial": SERIAL,
            "backend_pid": 0,
            "worker_pid": 0,
            "matrix_receipt": str(matrix_path),
            "public_network": False,
            "production_activation": False,
        }
        _write_json(self.output / "a4-25f-operator-state.json", state)

    def _audit(self) -> dict[str, object]:
        with mock.patch.object(audit, "_require_exact_clean_head", return_value=None):
            return audit.audit_evidence(self.output, expected_sha=EXPECTED_SHA)

    def test_valid_evidence_emits_non_activating_audit_receipt(self) -> None:
        receipt = self._audit()
        self.assertTrue(receipt["physical_qualification_evidence_valid"])
        self.assertTrue(receipt["all_referenced_hashes_verified"])
        self.assertTrue(receipt["mutation_chain_verified"])
        self.assertTrue(receipt["cursor_matrix_verified"])
        self.assertTrue(receipt["cleanup_verified"])
        self.assertFalse(receipt["human_go_authorized"])
        self.assertFalse(receipt["production_activation"])
        self.assertRegex(str(receipt["audit_sha256"]), r"^sha256:[0-9a-f]{64}$")

    def test_tampered_phone_receipt_is_rejected_by_matrix_hash(self) -> None:
        path = next((self.output / "phone-receipts").glob("main-*.json"))
        value = json.loads(path.read_text(encoding="utf-8"))
        value["tampered"] = True
        _write_json(path, value)
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            self._audit()

    def test_missing_cursor_matrix_is_fail_closed(self) -> None:
        (self.output / "a4-25f-cursor-matrix.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self._audit()

    def test_cleanup_production_activation_is_rejected(self) -> None:
        path = self.output / "a4-25f-cleanup.json"
        cleanup = json.loads(path.read_text(encoding="utf-8"))
        cleanup["production_activation"] = True
        _write_json(path, cleanup)
        with self.assertRaisesRegex(RuntimeError, "production_activation"):
            self._audit()

    def test_mutation_self_digest_tampering_is_rejected_even_if_matrix_hash_is_rebound(self) -> None:
        mutation_path = sorted((self.output / "mutations").glob("*.json"))[2]
        mutation = json.loads(mutation_path.read_text(encoding="utf-8"))
        mutation["mutation_id"] = "tampered"
        _write_json(mutation_path, mutation)
        matrix_path = self.output / "a4-25f-physical-matrix.json"
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        for reference in matrix["mutation_receipts"]:
            if reference["name"] == mutation_path.name:
                reference["sha256"] = audit._sha256_file(mutation_path)
        _write_json(matrix_path, matrix)
        with self.assertRaisesRegex(RuntimeError, "self-digest mismatch"):
            self._audit()


if __name__ == "__main__":
    unittest.main()
