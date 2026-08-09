#!/usr/bin/env python3
"""Adversarial tests for the A4-20 physical receipt verifier."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-agent4-physical-read-receipt.py"
SPEC = importlib.util.spec_from_file_location("agent4_receipt_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SHA = "ce6cbbbd02003f6e35cf2986c7b24b326add5fee"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def file_receipt(path: str) -> dict[str, Any]:
    return {"path": path, "size_bytes": 1, "sha256": HASH_A}


def trial(name: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": "pass",
        "observed_at": "2026-08-09T12:00:00Z",
        "note": "verified",
        "http_status": MODULE.EXPECTED_HTTP.get(name),
        "route": "/api/v1/agent4/campaigns" if name in MODULE.EXPECTED_HTTP else None,
        "request_id": "redacted-request-id",
        "payload_sha256": None,
        "cursor_sha256": None,
        "screenshot": None,
    }
    if name in {
        "campaign_paging_no_loss",
        "timeline_paging_no_loss",
        "evidence_paging_no_loss",
    }:
        value["payload_sha256"] = HASH_A
        value["cursor_sha256"] = HASH_B
    return value


def sign(receipt: dict[str, Any]) -> dict[str, Any]:
    unsigned = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"))
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return receipt


def valid_receipt() -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": MODULE.SCHEMA,
        "generated_at": "2026-08-09T12:00:00Z",
        "expected_sha": SHA,
        "observed_head": SHA,
        "branch": "agent/a4-18-physical-read-product",
        "backend_version": "1.58.151",
        "worker_version": "1.58.151",
        "fixture": {"schema": "modelrig-agent4/physical-fixture/v1"},
        "mutations": [
            {"schema": "modelrig-agent4/mutation/v1", "kind": "campaign"},
            {"schema": "modelrig-agent4/mutation/v1", "kind": "summary"},
        ],
        "pixel": {
            "model": "Pixel 6a",
            "android_release": "17",
            "sdk": "37",
            "app_package": "dk.ternedal.modelrig",
            "version_name_line": "versionName=1.58.151",
            "version_code_line": "versionCode=158151",
        },
        "trials": {name: trial(name) for name in MODULE.REQUIRED_CHECKPOINTS},
        "artifacts": [
            file_receipt("worker/app/entrypoint.py"),
            file_receipt("worker/app/agent4/production_bootstrap.py"),
            file_receipt("worker/app/agent4/operator_api.py"),
            file_receipt("android/app/src/main/java/dk/ternedal/modelrig/net/Agent4OperatorClient.kt"),
        ],
        "cleanup": {
            "backend_stopped": True,
            "worker_stopped": True,
            "unknown_process_preserved": False,
            "firewall_removed": True,
            "ports_free": True,
            "admin_key_deleted": True,
            "passed": True,
        },
        "all_required_observations_passed": True,
        "human_decision": "GO",
        "credential_data_included": False,
        "public_network": False,
        "production_activation": False,
    }
    return sign(receipt)


class Agent4PhysicalReceiptVerifierTests(unittest.TestCase):
    def verify(self, receipt: dict[str, Any], expected_sha: str | None = SHA):
        return MODULE.ReceiptVerifier(receipt, expected_sha).verify()

    def test_valid_receipt_passes(self) -> None:
        result = self.verify(valid_receipt())
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.expected_sha, SHA)
        self.assertEqual(result.pixel_model, "Pixel 6a")

    def test_digest_tampering_fails(self) -> None:
        receipt = valid_receipt()
        receipt["human_decision"] = "NO-GO"
        result = self.verify(receipt)
        self.assertFalse(result.ok)
        self.assertIn("receipt_sha256 does not match canonical receipt content", result.errors)

    def test_missing_and_unknown_checkpoints_fail(self) -> None:
        receipt = valid_receipt()
        receipt["trials"].pop("regrant_same_token_200")
        receipt["trials"]["invented_success"] = trial("invented_success")
        sign(receipt)
        result = self.verify(receipt)
        self.assertFalse(result.ok)
        self.assertTrue(any("missing required checkpoints" in error for error in result.errors))
        self.assertTrue(any("unknown checkpoints present" in error for error in result.errors))

    def test_wrong_http_status_fails(self) -> None:
        receipt = valid_receipt()
        receipt["trials"]["revoke_same_token_403"]["http_status"] = 200
        sign(receipt)
        result = self.verify(receipt)
        self.assertFalse(result.ok)
        self.assertIn("trial revoke_same_token_403 http_status must be 403", result.errors)

    def test_credential_like_key_and_value_fail(self) -> None:
        receipt = valid_receipt()
        receipt["debug"] = {
            "device_token": "should-never-appear",
            "note": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        }
        sign(receipt)
        result = self.verify(receipt)
        self.assertFalse(result.ok)
        self.assertTrue(any("sensitive key is forbidden" in error for error in result.errors))
        self.assertTrue(any("credential-like material is forbidden" in error for error in result.errors))

    def test_emulator_or_non_pixel_fails(self) -> None:
        for model in ("sdk_gphone64_x86_64", "Samsung Galaxy S24"):
            with self.subTest(model=model):
                receipt = valid_receipt()
                receipt["pixel"]["model"] = model
                sign(receipt)
                self.assertFalse(self.verify(receipt).ok)

    def test_cleanup_failure_forces_verification_failure(self) -> None:
        receipt = valid_receipt()
        receipt["cleanup"]["ports_free"] = False
        sign(receipt)
        result = self.verify(receipt)
        self.assertFalse(result.ok)
        self.assertIn("cleanup.ports_free must be true", result.errors)

    def test_expected_sha_mismatch_fails(self) -> None:
        receipt = valid_receipt()
        result = self.verify(receipt, "0" * 40)
        self.assertFalse(result.ok)
        self.assertIn("receipt expected_sha does not match --expected-sha", result.errors)

    def test_absolute_or_parent_artifact_paths_fail(self) -> None:
        for path in ("C:/secret.txt", "../secret.txt"):
            with self.subTest(path=path):
                receipt = valid_receipt()
                receipt["artifacts"][0]["path"] = path
                sign(receipt)
                self.assertFalse(self.verify(receipt).ok)

    def test_cli_json_output_and_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "receipt.json"
            path.write_text(json.dumps(valid_receipt()), encoding="utf-8")
            self.assertEqual(MODULE.main([str(path), "--expected-sha", SHA, "--json"]), 0)

            invalid = valid_receipt()
            invalid["public_network"] = True
            sign(invalid)
            path.write_text(json.dumps(invalid), encoding="utf-8")
            self.assertEqual(MODULE.main([str(path), "--json"]), 1)

    def test_verifier_has_no_network_or_mutation_surface(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "requests.",
            "urllib.request",
            "http.client",
            "subprocess.",
            "socket.",
            "git push",
            "Issue #421",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
