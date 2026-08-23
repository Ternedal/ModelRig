#!/usr/bin/env python3
"""Fail-closed tests for the A4-18R physical evidence auditor."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent4_a4_18r_audit as audit  # noqa: E402
import agent4_a4_18r_receipt_verify_offline as offline  # noqa: E402

EXPECTED_SHA = "a" * 40
DIGEST_A = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def file_ref(scope: str, path: str, actual: Path) -> dict[str, object]:
    return {
        "schema": audit.FILE_SCHEMA,
        "scope": scope,
        "path": path,
        "size_bytes": actual.stat().st_size,
        "sha256": audit.sha256_file(actual),
    }


def self_digest(value: dict[str, object]) -> None:
    value["receipt_sha256"] = "sha256:" + hashlib.sha256(audit.canonical_json(value)).hexdigest()


class A418rAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="modelrig-a4-18r-audit-")
        base = Path(self.temp.name).resolve()
        self.output = base / "output"
        self.repo = base / "repo"
        self.output.mkdir()
        self.repo.mkdir()
        self._build_valid_evidence()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build_valid_evidence(self) -> None:
        marker = {
            "schema": audit.MARKER_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "public_network": False,
            "production_activation": False,
        }
        write_json(self.output / ".modelrig-a4-18r-output.json", marker)

        repository_artifacts = []
        for rel in sorted(audit.CRITICAL_REPOSITORY_ARTIFACTS):
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture repository artifact: {rel}\n", encoding="utf-8")
            repository_artifacts.append(file_ref("repository", rel, path))

        output_artifacts = []
        for rel in (
            "bin/modelrig-a4-18r-backend.exe",
            "bin/modelrig-a4-18r-grants.exe",
            "bin/modelrig-a4-18r.apk",
        ):
            path = self.output / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("artifact:" + rel).encode("utf-8"))
            output_artifacts.append(file_ref("output", rel, path))

        fixture = {
            "schema": audit.FIXTURE_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "selected_campaign_id": "a4-18r-physical-primary",
            "campaign_count": 31,
            "timeline_count": 32,
            "evidence_count": 31,
            "evidence_verification_count": 31,
            "latest_timeline_hash": DIGEST_A,
            "evidence_head_hash": DIGEST_B,
            "first_payload_sha256": DIGEST_A,
            "last_payload_sha256": DIGEST_B,
            "persisted_files": [
                {
                    "path": "agent4/campaigns/a4-18r-physical-primary.json",
                    "size_bytes": 123,
                    "sha256": DIGEST_A,
                }
            ],
            "external_dispatch": False,
            "background_runtime": False,
            "public_network": False,
            "production_activation": False,
        }
        write_json(self.output / "fixture-manifest.json", fixture)
        output_artifacts.append(
            file_ref("output", "fixture-manifest.json", self.output / "fixture-manifest.json")
        )

        campaign = {
            "schema": audit.MUTATION_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "mode": "campaign-record",
            "mutation_id": "campaign-mutation",
            "campaign_count_before": 31,
            "campaign_count_after": 32,
            "evidence_count_before": 31,
            "evidence_count_after": 31,
            "timeline_head_before": DIGEST_A,
            "timeline_head_after": DIGEST_A,
            "evidence_head_before": DIGEST_B,
            "evidence_head_after": DIGEST_B,
            "external_dispatch": False,
            "background_runtime": False,
            "public_network": False,
            "production_activation": False,
        }
        self_digest(campaign)
        summary = {
            "schema": audit.MUTATION_SCHEMA,
            "repository_sha": EXPECTED_SHA,
            "mode": "summary",
            "mutation_id": "summary-mutation",
            "campaign_count_before": 32,
            "campaign_count_after": 32,
            "evidence_count_before": 31,
            "evidence_count_after": 32,
            "timeline_head_before": DIGEST_A,
            "timeline_head_after": DIGEST_B,
            "evidence_head_before": DIGEST_A,
            "evidence_head_after": DIGEST_B,
            "external_dispatch": False,
            "background_runtime": False,
            "public_network": False,
            "production_activation": False,
        }
        self_digest(summary)
        for name, value in (("mutation-campaign.json", campaign), ("mutation-summary.json", summary)):
            path = self.output / name
            write_json(path, value)
            output_artifacts.append(file_ref("output", name, path))

        trials: dict[str, dict[str, object]] = {}
        for name in audit.REQUIRED_TRIALS:
            entry: dict[str, object] = {
                "status": "pass",
                "observed_at": "2026-08-23T06:00:00Z",
                "note": None,
                "http_status": None,
                "route": None,
                "request_id": None,
                "payload_sha256": None,
                "cursor_sha256": None,
            }
            if name in audit.EXPECTED_HTTP:
                entry["http_status"] = audit.EXPECTED_HTTP[name]
                entry["route"] = "/api/v1/experimental/agent4/operator/campaigns"
            if name in audit.PAYLOAD_REQUIRED:
                entry["payload_sha256"] = DIGEST_A
            if name in audit.CURSOR_REQUIRED:
                entry["cursor_sha256"] = DIGEST_B
            trials[name] = entry

        receipt: dict[str, object] = {
            "schema": audit.RECEIPT_SCHEMA,
            "generated_at": "2026-08-23T06:30:00Z",
            "expected_sha": EXPECTED_SHA,
            "observed_head": EXPECTED_SHA,
            "fixture": fixture,
            "mutations": [campaign, summary],
            "pixel": {
                "schema": audit.PIXEL_SCHEMA,
                "serial_sha256": DIGEST_A,
                "manufacturer": "Google",
                "model": "Pixel 8",
                "android_release": "16",
                "sdk": "36",
                "package_name": "dk.ternedal.modelrig.a425f",
                "version_name_line": "versionName=2.0.11-a425f",
                "version_code_line": "versionCode=292",
            },
            "trials": trials,
            "artifacts": repository_artifacts + output_artifacts,
            "cleanup": {
                "backend_stopped": True,
                "worker_stopped": True,
                "firewall_removed": True,
                "ports_free": True,
                "credential_file_deleted": True,
                "pairing_store_deleted": True,
                "test_package_uninstalled": True,
                "unknown_process_preserved": False,
            },
            "all_required_observations_passed": True,
            "human_decision": "GO",
            "credential_data_included": False,
            "public_network": False,
            "production_activation": False,
        }
        self_digest(receipt)
        write_json(self.output / "a4-18r-physical-read-receipt.json", receipt)

    def _audit(self) -> dict[str, object]:
        return audit.audit_evidence(self.output, expected_sha=EXPECTED_SHA, repo_root=self.repo)

    def _receipt(self) -> dict[str, object]:
        return json.loads(
            (self.output / "a4-18r-physical-read-receipt.json").read_text(encoding="utf-8")
        )

    def _offline(self) -> dict[str, object]:
        return offline.verify_receipt(self._receipt(), expected_sha=EXPECTED_SHA)

    def _rewrite_receipt(self, mutator) -> None:
        path = self.output / "a4-18r-physical-read-receipt.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutator(value)
        value.pop("receipt_sha256", None)
        self_digest(value)
        write_json(path, value)

    def test_valid_evidence_passes_without_production_authority(self) -> None:
        result = self._audit()
        self.assertTrue(result["physical_qualification_evidence_valid"])
        self.assertTrue(result["credential_hygiene_verified"])
        self.assertTrue(result["artifact_hashes_verified"])
        self.assertFalse(result["public_network"])
        self.assertFalse(result["production_activation"])

    def test_raw_device_token_in_note_is_rejected_even_if_receipt_digest_is_rebound(self) -> None:
        self._rewrite_receipt(
            lambda value: value["trials"]["no_write_controls"].__setitem__("note", "a" * 64)
        )
        with self.assertRaisesRegex(ValueError, "credential-like"):
            self._audit()

    def test_free_text_sha256_prefix_does_not_launder_raw_token(self) -> None:
        self._rewrite_receipt(
            lambda value: value["trials"]["no_write_controls"].__setitem__(
                "note", "sha256:" + "a" * 64
            )
        )
        with self.assertRaisesRegex(ValueError, "credential-like"):
            self._audit()

    def test_artifact_tampering_is_rejected(self) -> None:
        target = self.output / "bin/modelrig-a4-18r.apk"
        target.write_bytes(target.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ValueError, "artifact (size|digest) mismatch"):
            self._audit()

    def test_cleanup_secret_or_pairing_store_left_behind_is_rejected(self) -> None:
        (self.output / "admin-key.txt").write_text("not-a-real-key", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "admin key still exists"):
            self._audit()
        (self.output / "admin-key.txt").unlink()
        (self.output / "modelrig-data.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "pairing/device store still exists"):
            self._audit()

    def test_wrong_exact_sha_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "output marker exact SHA mismatch"):
            audit.audit_evidence(self.output, expected_sha="b" * 40, repo_root=self.repo)

    def test_symlink_in_evidence_tree_is_rejected_when_supported(self) -> None:
        target = self.output / "safe.txt"
        target.write_text("safe\n", encoding="utf-8")
        link = self.output / "unsafe-link.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self._audit()

    def test_offline_receipt_verifier_accepts_valid_self_contained_receipt(self) -> None:
        result = self._offline()
        self.assertEqual(result["result"], "PASS")
        self.assertTrue(result["receipt_only"])
        self.assertTrue(result["canonical_runtime_audit_still_required"])
        self.assertFalse(result["artifact_bytes_verified"])
        self.assertFalse(result["network_used"])
        self.assertFalse(result["repository_lookup_used"])
        self.assertFalse(result["subprocess_used"])
        self.assertFalse(result["mutation_performed"])

    def test_offline_verifier_rejects_wrong_external_sha(self) -> None:
        with self.assertRaisesRegex(ValueError, "receipt exact SHA mismatch"):
            offline.verify_receipt(self._receipt(), expected_sha="b" * 40)

    def test_offline_verifier_rejects_rebound_raw_token_and_sha_prefix_laundering(self) -> None:
        for note in ("a" * 64, "sha256:" + "a" * 64):
            with self.subTest(note_prefix=note[:8]):
                self._rewrite_receipt(
                    lambda value, note=note: value["trials"]["no_write_controls"].__setitem__(
                        "note", note
                    )
                )
                with self.assertRaisesRegex(ValueError, "credential-like"):
                    self._offline()
                self._build_valid_evidence()

    def test_offline_verifier_rejects_missing_critical_artifact_receipt(self) -> None:
        self._rewrite_receipt(
            lambda value: value.__setitem__(
                "artifacts",
                [
                    entry
                    for entry in value["artifacts"]
                    if entry["path"] != "bin/modelrig-a4-18r.apk"
                ],
            )
        )
        with self.assertRaisesRegex(ValueError, "critical output artifact receipts are missing"):
            self._offline()

    def test_offline_verifier_rejects_duplicate_json_keys_before_semantic_verification(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            json.loads(
                '{"schema":"one","schema":"two"}',
                object_pairs_hook=offline.reject_duplicate_object_pairs,
            )

    def test_offline_verifier_has_read_only_authority_surface(self) -> None:
        source_path = ROOT / "scripts" / "agent4_a4_18r_receipt_verify_offline.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
        self.assertFalse(imported & {"socket", "subprocess", "urllib", "http", "requests", "os"})
        self.assertFalse(calls & {"write_text", "write_bytes", "unlink", "rename", "replace", "mkdir", "rmdir"})
        self.assertNotIn("agent4_a4_18r_audit", imported)


if __name__ == "__main__":
    unittest.main()
