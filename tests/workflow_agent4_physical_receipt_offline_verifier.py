#!/usr/bin/env python3
"""Positive and adversarial contract tests for the A4-20 offline verifier."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent4_physical_receipt_verify_offline.py"
sys.path.insert(0, str(ROOT / "scripts"))

import agent4_physical_receipt_verify_offline as verifier  # noqa: E402

EXPECTED_SHA = "628a45f51d22ce7e9eba7eb623495603f4a694eb"
H0 = "sha256:" + "0" * 64
H1 = "sha256:" + "1" * 64
H2 = "sha256:" + "2" * 64
H3 = "sha256:" + "3" * 64


def canonical_digest(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def mutation(mode: str) -> dict[str, object]:
    if mode == "campaign-record":
        item: dict[str, object] = {
            "schema": verifier.MUTATION_SCHEMA,
            "mode": mode,
            "campaign_count_before": 30,
            "campaign_count_after": 31,
            "evidence_count_before": 30,
            "evidence_count_after": 30,
            "timeline_head_before": H0,
            "timeline_head_after": H0,
            "evidence_head_before": H1,
            "evidence_head_after": H1,
            "external_dispatch": False,
            "background_runtime": False,
            "production_activation": False,
        }
    else:
        item = {
            "schema": verifier.MUTATION_SCHEMA,
            "mode": mode,
            "campaign_count_before": 31,
            "campaign_count_after": 31,
            "evidence_count_before": 30,
            "evidence_count_after": 31,
            "timeline_head_before": H0,
            "timeline_head_after": H2,
            "evidence_head_before": H1,
            "evidence_head_after": H3,
            "external_dispatch": False,
            "background_runtime": False,
            "production_activation": False,
        }
    item["receipt_sha256"] = canonical_digest(item)
    return item


def trial(name: str) -> dict[str, object]:
    entry: dict[str, object] = {
        "status": "pass",
        "observed_at": "2026-08-10T08:00:00+00:00",
        "note": f"Redacted observation for {name}",
        "http_status": verifier.EXPECTED_HTTP_STATUS.get(name),
        "route": (
            "/api/v1/experimental/agent4/operator/campaigns"
            if name in verifier.EXPECTED_HTTP_STATUS
            else None
        ),
        "request_id": "req-redacted",
        "payload_sha256": H0 if name in verifier.PAYLOAD_HASH_TRIALS else None,
        "cursor_sha256": H1 if name in verifier.CURSOR_HASH_TRIALS else None,
        "screenshot": None,
    }
    return entry


def valid_receipt() -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": verifier.RECEIPT_SCHEMA,
        "generated_at": "2026-08-10T08:00:00+00:00",
        "expected_sha": EXPECTED_SHA,
        "observed_head": EXPECTED_SHA,
        "branch": verifier.EXPECTED_BRANCH,
        "backend_version": verifier.EXPECTED_VERSION,
        "worker_version": verifier.EXPECTED_VERSION,
        "fixture": {
            "schema": verifier.FIXTURE_SCHEMA,
            "campaign_count": 30,
            "timeline_count": 30,
            "evidence_count": 30,
            "evidence_verification_count": 30,
            "selected_campaign_id": "a4-18-physical-primary",
            "latest_timeline_hash": H0,
            "evidence_head_hash": H1,
            "first_payload_sha256": H2,
            "last_payload_sha256": H3,
            "external_dispatch": False,
            "background_runtime": False,
            "production_activation": False,
        },
        "mutations": [mutation("campaign-record"), mutation("summary")],
        "pixel": {
            "model": "Pixel 8",
            "android_release": "16",
            "sdk": "36",
            "app_package": verifier.EXPECTED_APP_PACKAGE,
            "version_name_line": f"versionName={verifier.EXPECTED_VERSION}",
            "version_code_line": "versionCode=158151 minSdk=26 targetSdk=35",
        },
        "trials": {name: trial(name) for name in verifier.REQUIRED_TRIALS},
        "artifacts": [
            {
                "path": "validation/agent4-physical-runtime/fixture-manifest.json",
                "size_bytes": 1234,
                "sha256": H0,
            },
            {
                "path": "android/app/build/outputs/apk/debug/app-debug.apk",
                "size_bytes": 5678,
                "sha256": H1,
            },
        ],
        "cleanup": {
            "backend_stopped": True,
            "worker_stopped": True,
            "unknown_process_preserved": False,
            "firewall_removed": True,
            "ports_free": True,
            "admin_key_deleted": True,
            "pairing_store_deleted": True,
            "passed": True,
        },
        "all_required_observations_passed": True,
        "human_decision": "GO",
        "credential_data_included": False,
        "public_network": False,
        "production_activation": False,
        "safety_hardening": {
            "schema": verifier.SAFETY_SCHEMA,
            "physical_pixel": True,
            "artifacts_hashed_after_prestop": True,
            "wildcard_binding": False,
            "public_network": False,
            "production_activation": False,
            "pixel_manufacturer": "Google",
            "pixel_model": "Pixel 8",
            "pixel_serial_sha256": H2,
            "lan_address": "192.168.1.50",
            "network_profile": "Private",
            "backend_bound_address": "192.168.1.50",
            "worker_bound_address": "127.0.0.1",
            "firewall_local_address": "192.168.1.50",
            "firewall_remote_scope": "LocalSubnet",
            "binding_file": {
                "path": "validation/agent4-physical-runtime/safety-binding.json",
                "size_bytes": 500,
                "sha256": H3,
            },
        },
    }
    receipt["receipt_sha256"] = canonical_digest(receipt)
    return receipt


def resign(receipt: dict[str, object]) -> None:
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = canonical_digest(receipt)


class OfflineReceiptVerifierTests(unittest.TestCase):
    def assertRejected(self, receipt: dict[str, object], pattern: str) -> None:
        with self.assertRaisesRegex(verifier.VerificationError, pattern):
            verifier.verify_receipt(receipt, expected_sha=EXPECTED_SHA)

    def test_valid_receipt_passes(self) -> None:
        verifier.verify_receipt(valid_receipt(), expected_sha=EXPECTED_SHA)

    def test_main_digest_tamper_is_rejected_without_resigning(self) -> None:
        receipt = valid_receipt()
        receipt["human_decision"] = "NO-GO"
        self.assertRejected(receipt, "receipt_sha256")

    def test_resigned_no_go_receipt_is_still_rejected_semantically(self) -> None:
        receipt = valid_receipt()
        receipt["human_decision"] = "NO-GO"
        resign(receipt)
        self.assertRejected(receipt, "human_decision")

    def test_wrong_expected_head_is_rejected_even_after_resigning(self) -> None:
        receipt = valid_receipt()
        receipt["expected_sha"] = "a" * 40
        receipt["observed_head"] = "a" * 40
        resign(receipt)
        self.assertRejected(receipt, "verifier authority")

    def test_missing_or_unknown_checkpoint_is_rejected(self) -> None:
        receipt = valid_receipt()
        del receipt["trials"]["not_found_fail_closed"]
        receipt["trials"]["invented_success"] = trial("invented_success")
        resign(receipt)
        self.assertRejected(receipt, "exactly the 21")

    def test_resigned_wrong_http_status_is_rejected(self) -> None:
        receipt = valid_receipt()
        receipt["trials"]["paired_without_grant_403"]["http_status"] = 200
        resign(receipt)
        self.assertRejected(receipt, "unexpected HTTP status")

    def test_invalid_payload_hash_is_rejected(self) -> None:
        receipt = valid_receipt()
        receipt["trials"]["grant_same_token_200"]["payload_sha256"] = "sha256:not-a-hash"
        resign(receipt)
        self.assertRejected(receipt, "sha256")

    def test_raw_screenshot_path_is_rejected(self) -> None:
        receipt = valid_receipt()
        receipt["trials"]["campaign_paging_no_loss"]["screenshot"] = "validation/raw.png"
        resign(receipt)
        self.assertRejected(receipt, "screenshot")

    def test_mutation_edit_with_only_main_resign_is_rejected(self) -> None:
        receipt = valid_receipt()
        receipt["mutations"][0]["campaign_count_after"] = 99
        resign(receipt)
        self.assertRejected(receipt, "mutation campaign-record digest")

    def test_cleanup_failure_is_rejected_after_resigning(self) -> None:
        receipt = valid_receipt()
        receipt["cleanup"]["ports_free"] = False
        resign(receipt)
        self.assertRejected(receipt, "cleanup.ports_free")

    def test_public_network_is_rejected_after_resigning(self) -> None:
        receipt = valid_receipt()
        receipt["public_network"] = True
        resign(receipt)
        self.assertRejected(receipt, "public_network")

    def test_non_pixel_or_emulator_identity_is_rejected(self) -> None:
        receipt = valid_receipt()
        receipt["pixel"]["model"] = "Pixel Emulator"
        receipt["safety_hardening"]["pixel_model"] = "Pixel Emulator"
        resign(receipt)
        self.assertRejected(receipt, "emulator-like")

    def test_credential_key_is_rejected_even_when_main_digest_is_valid(self) -> None:
        receipt = valid_receipt()
        receipt["debug"] = {"token": "secret-device-token"}
        resign(receipt)
        self.assertRejected(receipt, "forbidden credential field")

    def test_credential_like_value_is_rejected(self) -> None:
        receipt = valid_receipt()
        receipt["trials"]["network_recovery"]["note"] = "Authorization: Bearer abcdefghijklmnop"
        resign(receipt)
        self.assertRejected(receipt, "credential-like value")

    def test_bad_artifact_path_is_rejected(self) -> None:
        receipt = valid_receipt()
        receipt["artifacts"][0]["path"] = "../secret.txt"
        resign(receipt)
        self.assertRejected(receipt, "traverse")

    def test_cli_emits_machine_and_human_pass_fail_without_mutating_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            body = json.dumps(valid_receipt(), ensure_ascii=False, indent=2)
            path.write_text(body, encoding="utf-8")
            before = path.read_bytes()
            passed = subprocess.run(
                [sys.executable, str(SCRIPT), "--receipt", str(path), "--expected-sha", EXPECTED_SHA],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            machine = json.loads(passed.stdout.splitlines()[0])
            self.assertEqual(machine["result"], "PASS")
            self.assertFalse(machine["network_used"])
            self.assertFalse(machine["mutation_performed"])
            self.assertIn("PASS", passed.stdout.splitlines()[1])
            self.assertEqual(path.read_bytes(), before)

            receipt = valid_receipt()
            receipt["human_decision"] = "NO-GO"
            resign(receipt)
            path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            failed = subprocess.run(
                [sys.executable, str(SCRIPT), "--receipt", str(path), "--expected-sha", EXPECTED_SHA],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(json.loads(failed.stdout.splitlines()[0])["result"], "FAIL")
            self.assertIn("FAIL", failed.stdout.splitlines()[1])

    def test_verifier_source_has_no_network_process_or_write_authority(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_modules = {
            "socket",
            "subprocess",
            "urllib",
            "http",
            "requests",
            "httpx",
            "ftplib",
            "smtplib",
        }
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint(forbidden_modules), imported & forbidden_modules)

        forbidden_calls = {
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
            "mkdir",
            "touch",
            "remove",
            "rmdir",
            "system",
            "popen",
        }
        attribute_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        called_attrs = {node.func.attr for node in attribute_calls}
        self.assertTrue(called_attrs.isdisjoint(forbidden_calls), called_attrs & forbidden_calls)

        # `.replace()` is ambiguous in AST because both strings and pathlib paths
        # expose that name. The verifier intentionally has exactly one approved
        # string normalization call for ISO-8601 `Z`; any second `.replace()`
        # would regain an unreviewed possible filesystem mutation surface.
        replace_calls = [node for node in attribute_calls if node.func.attr == "replace"]
        self.assertEqual(len(replace_calls), 1)
        replace_call = replace_calls[0]
        self.assertIsInstance(replace_call.func.value, ast.Name)
        self.assertEqual(replace_call.func.value.id, "text")
        self.assertEqual(len(replace_call.args), 2)
        self.assertEqual([ast.literal_eval(arg) for arg in replace_call.args], ["Z", "+00:00"])
        self.assertNotIn("open(", source)


if __name__ == "__main__":
    unittest.main()
