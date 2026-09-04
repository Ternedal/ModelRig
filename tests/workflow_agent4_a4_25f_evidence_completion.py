#!/usr/bin/env python3
"""Regression tests for A4-25f evidence completion and human decision binding."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import agent4_a4_25f_audit as audit  # noqa: E402
import agent4_a4_25f_finalize_evidence as finalizer  # noqa: E402
import agent4_a4_25f_record_decision as decision  # noqa: E402
import workflow_agent4_a4_25f_audit as audit_tests  # noqa: E402

EXPECTED_SHA = audit_tests.EXPECTED_SHA


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class A425fEvidenceCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = audit_tests.A425fAuditTests(
            methodName="test_valid_evidence_emits_non_activating_audit_receipt"
        )
        self.base.setUp()
        self.output = self.base.output
        self.rig_environment = {
            "os": "Windows",
            "windows_release": "11",
            "windows_version": "10.0.26100",
            "windows_service_pack": "",
            "windows_product_type": "Multiprocessor Free",
            "architecture": "AMD64",
            "python_version": "3.12.10",
            "python_implementation": "CPython",
            "python_executable_sha256": "sha256:" + "1" * 64,
            "go_version": "go version go1.23.12 windows/amd64",
        }
        self._add_device_info()
        self._add_http_trace()

    def tearDown(self) -> None:
        self.base.tearDown()

    def _add_device_info(self) -> None:
        path = self.output / "phone-receipts" / "a4-25f-device-info.json"
        receipt = {
            "schema": finalizer.DEVICE_INFO_SCHEMA,
            "recorded_at": "2026-08-10T00:00:00Z",
            "stage": "device-info",
            "success": True,
            "route_kind": "device-status",
            "expected_http_status": 200,
            "actual_http_status": 200,
            "device_id": "device-test",
            "device_name": "A425f physical test",
            "android_manufacturer": "Google",
            "android_model": "Pixel Test",
            "android_version_release": "16",
            "android_sdk_int": 36,
            "app_package_name": audit.PACKAGE_NAME,
            "app_version_name": "1.58.151",
            "app_version_code": 158151,
            "app_debuggable": True,
            "backend_url_sha256": "sha256:" + "2" * 64,
            "credential_in_receipt": False,
            "production_activation": False,
        }
        _write_json(path, receipt)
        matrix_path = self.output / "a4-25f-physical-matrix.json"
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        matrix["apk_sha256"] = "sha256:" + "3" * 64
        matrix["phone_receipts"].append({"name": path.name, "sha256": audit._sha256_file(path)})
        _write_json(matrix_path, matrix)

    def _add_http_trace(self) -> None:
        path = self.output / "backend-device-store.json.agent4-evidence.jsonl"
        lines = []
        for _, route_kind, status in finalizer.EXPECTED_TRIALS:
            lines.append(
                json.dumps(
                    {
                        "schema": finalizer.HTTP_TRACE_SCHEMA,
                        "recorded_at": "2026-08-10T00:00:00Z",
                        "method": "GET",
                        "route_kind": route_kind,
                        "query_keys": ["snapshot_id"],
                        "raw_query_sha256": "sha256:" + "4" * 64,
                        "http_status": status,
                        "response_media_type": finalizer.MEDIA_TYPE,
                        "response_body_sha256": "sha256:" + "5" * 64,
                        "response_body_size": 123,
                        "credential_in_receipt": False,
                        "raw_cursor_in_receipt": False,
                        "public_network": False,
                        "production_activation": False,
                    },
                    sort_keys=True,
                )
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _finalize(self) -> dict[str, object]:
        with mock.patch.object(audit, "_require_exact_clean_head", return_value=None):
            return finalizer.finalize_evidence(
                self.output,
                expected_sha=EXPECTED_SHA,
                rig_environment=self.rig_environment,
            )

    def test_complete_evidence_binds_platform_http_trials_and_never_goes_live(self) -> None:
        receipt = self._finalize()
        self.assertTrue(receipt["physical_qualification_evidence_complete"])
        self.assertTrue(receipt["all_expected_http_trials_verified"])
        self.assertTrue(receipt["android_build_identity_verified"])
        self.assertTrue(receipt["rig_platform_identity_recorded"])
        self.assertEqual(receipt["http_trial_count"], 14)
        self.assertEqual(receipt["android_environment"]["model"], "Pixel Test")
        self.assertEqual(receipt["rig_environment"]["go_version"], "go version go1.23.12 windows/amd64")
        self.assertFalse(receipt["human_go_recorded"])
        self.assertFalse(receipt["human_go_authorized"])
        self.assertFalse(receipt["production_activation"])
        self.assertRegex(str(receipt["qualification_evidence_sha256"]), r"^sha256:[0-9a-f]{64}$")

    def test_wrong_actual_http_status_is_fail_closed(self) -> None:
        path = self.output / "backend-device-store.json.agent4-evidence.jsonl"
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        entries[8]["http_status"] = 200
        path.write_text("\n".join(json.dumps(entry, sort_keys=True) for entry in entries) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "selected-root-404 status mismatch"):
            self._finalize()

    def test_missing_pixel_model_is_fail_closed(self) -> None:
        path = self.output / "phone-receipts" / "a4-25f-device-info.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["android_model"] = ""
        _write_json(path, receipt)
        matrix_path = self.output / "a4-25f-physical-matrix.json"
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        for reference in matrix["phone_receipts"]:
            if reference["name"] == path.name:
                reference["sha256"] = audit._sha256_file(path)
        _write_json(matrix_path, matrix)
        with self.assertRaisesRegex(RuntimeError, "android_model"):
            self._finalize()

    def test_human_go_is_separate_immutable_and_never_authorizes_production(self) -> None:
        evidence = self._finalize()
        with mock.patch.object(audit, "_require_exact_clean_head", return_value=None):
            receipt = decision.record_decision(
                self.output,
                expected_sha=EXPECTED_SHA,
                decision="GO",
                reviewer="A4-25f human reviewer",
                reason="Physical evidence reviewed and accepted for A4-25f only.",
            )
        self.assertEqual(receipt["decision"], "GO")
        self.assertTrue(receipt["human_decision_recorded"])
        self.assertTrue(receipt["physical_qualification_human_go"])
        self.assertFalse(receipt["production_activation_authorized"])
        self.assertFalse(receipt["production_activation"])
        self.assertEqual(receipt["qualification_evidence_sha256"], evidence["qualification_evidence_sha256"])
        with mock.patch.object(audit, "_require_exact_clean_head", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "immutable"):
                decision.record_decision(
                    self.output,
                    expected_sha=EXPECTED_SHA,
                    decision="NO-GO",
                    reviewer="other reviewer",
                    reason="must not overwrite",
                )

    def test_human_decision_rejects_tampered_qualification_evidence(self) -> None:
        self._finalize()
        path = self.output / "a4-25f-qualification-evidence.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        evidence["http_trial_count"] = 13
        _write_json(path, evidence)
        with mock.patch.object(audit, "_require_exact_clean_head", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "self-digest mismatch"):
                decision.record_decision(
                    self.output,
                    expected_sha=EXPECTED_SHA,
                    decision="GO",
                    reviewer="reviewer",
                    reason="tampered evidence must not pass",
                )


if __name__ == "__main__":
    unittest.main()
