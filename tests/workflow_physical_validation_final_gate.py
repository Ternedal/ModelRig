#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "physical_validation_final_gate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("physical_final_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def fixtures(root: Path, now: datetime) -> tuple[dict, Path, Path]:
    generated = now.isoformat().replace("+00:00", "Z")
    candidate = {
        "version": "1.58.125",
        "git_sha": "b" * 40,
        "code_sha256": "c" * 64,
        "branch": "agent/t032",
        "working_tree_clean": True,
        "dirty_entries": 0,
        "version_stamps_consistent": True,
        "version_check_detail": None,
    }
    campaign = {
        "schema": "kaliv-physical-validation-campaign/v1",
        "generated_at": generated,
        "mode": "verify",
        "candidate": candidate,
        "summary": {
            "total": 7,
            "passed": [
                "preflight",
                "agent3",
                "model_eval",
                "voice",
                "rag",
                "lifecycle",
                "scheduler_pilot",
            ],
            "failed": [],
            "missing": [],
            "candidate_errors": [],
        },
        "gate": {
            "passed": True,
            "physical_campaign_complete": True,
            "production_activation": False,
        },
    }
    digest = "a" * 64
    receipt = {
        "schema": "kaliv-browser-peer-public-validation/v1",
        "generated_at": generated,
        "passed": True,
        "candidate": candidate,
        "target": {"host": "example.com", "port": 443, "url_sha256": "d" * 64},
        "dns": {
            "addresses": ["8.8.8.8"],
            "answer_count": 1,
            "dns_sha256": "e" * 64,
            "selected_address": "8.8.8.8",
        },
        "transport": {
            "connected_address": "8.8.8.8",
            "connected_port": 443,
            "bytes_sent": 202,
            "response_status": 200,
            "response_body_bytes": 559,
            "response_body_sha256": digest,
        },
        "citation": {
            "adapter": "deterministic-web-fetch",
            "content_sha256": digest,
            "bytes_read": 559,
            "media_type": "text/html",
        },
        "evidence": {
            "schema": "kaliv-browser-peer-runtime/v1",
            "selected_address": "8.8.8.8",
            "connected_port": 443,
            "bytes_sent": 202,
            "status": 200,
            "response_body_bytes": 559,
            "response_body_sha256": digest,
            "url_sha256": "d" * 64,
            "production_activation": False,
        },
        "limits": {
            "method": "GET",
            "max_outbound_bytes": 4096,
            "max_response_bytes": 262144,
            "timeout_seconds": 15.0,
            "redirects_followed": False,
        },
        "plan": {
            "plan_id": "bpv_" + "f" * 32,
            "consumed_path": "validation/browser-peer-public-validation-plan.consumed-bpv_x.json",
            "consumed_sha256": "1" * 64,
        },
        "public_network_contacted": True,
        "redirects_followed": False,
        "validation_only": True,
        "production_activation": False,
        "error": None,
    }
    campaign_path = root / "validation" / "physical-validation-campaign-latest.json"
    receipt_path = root / "validation" / "browser-peer-public-validation-latest.json"
    attestation_path = root / "validation" / "browser-peer-public-validation-physical-latest.json"
    write_json(campaign_path, campaign)
    receipt_raw = write_json(receipt_path, receipt)
    attestation = {
        "schema": "kaliv-browser-peer-public-validation-physical/v1",
        "generated_at": generated,
        "candidate": candidate,
        "host": {
            "hostname": "MODELRIG",
            "system": "Windows",
            "release": "11",
            "version": "test",
            "machine": "AMD64",
            "platform": "Windows-11",
            "python": "3.12.0",
        },
        "operator": {
            "interactive_terminal": True,
            "typed_confirmation": True,
            "github_actions": False,
            "ci": False,
        },
        "receipt": {
            "path": "validation/browser-peer-public-validation-latest.json",
            "sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "schema": receipt["schema"],
            "generated_at": receipt["generated_at"],
            "target": receipt["target"],
            "dns": {
                "answer_count": 1,
                "dns_sha256": "e" * 64,
                "selected_address": "8.8.8.8",
            },
            "transport": receipt["transport"],
            "citation": receipt["citation"],
            "plan": receipt["plan"],
        },
        "gate": {
            "passed": True,
            "windows_host": True,
            "interactive_operator": True,
            "candidate_bound": True,
            "receipt_integrity": True,
            "public_network_contacted": True,
            "production_activation": False,
        },
    }
    write_json(attestation_path, attestation)
    return candidate, campaign_path.relative_to(root), attestation_path.relative_to(root)


def evaluate(module, root: Path, candidate: dict, campaign: Path, attestation: Path, now: datetime):
    return module.evaluate_final_gate(
        root,
        campaign,
        attestation,
        candidate=candidate,
        now=now,
        max_age_hours=168.0,
    )


def main() -> None:
    module = load_module()
    doc = " ".join((module.__doc__ or "").split())
    assert "seven-proof physical campaign" in doc
    assert "eighth-proof final receipt" in doc
    now = datetime(2026, 7, 20, 18, 30, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 0
        assert report["gate"]["all_physical_evidence_complete"] is True
        assert report["summary"]["total"] == 8
        assert "scheduler_pilot" in report["summary"]["passed"]
        assert report["summary"]["passed"][-1] == "browser_peer_physical"
        assert report["gate"]["production_activation"] is False

        attestation_file = root / attestation
        value = json.loads(attestation_file.read_text(encoding="utf-8"))
        value["host"]["system"] = "Linux"
        write_json(attestation_file, value)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 1 and report["gate"]["passed"] is False

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        attestation_file = root / attestation
        value = json.loads(attestation_file.read_text(encoding="utf-8"))
        value["operator"]["github_actions"] = True
        write_json(attestation_file, value)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 1

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        receipt_file = root / "validation" / "browser-peer-public-validation-latest.json"
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        receipt["transport"]["connected_address"] = "1.1.1.1"
        write_json(receipt_file, receipt)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 1
        assert any("hash" in error or "peer" in error for error in report["summary"]["errors"])

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        hosted_candidate = copy.deepcopy(candidate)
        hosted_candidate["git_sha"] = "9" * 40
        report, code = evaluate(module, root, hosted_candidate, campaign, attestation, now)
        assert code == 1
        assert any("candidate.git_sha" in error for error in report["summary"]["errors"])

    print("physical validation final eight-proof gate: PASS")


if __name__ == "__main__":
    main()
