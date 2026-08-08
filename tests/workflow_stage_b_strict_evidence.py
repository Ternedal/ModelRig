#!/usr/bin/env python3
"""Strict Stage B evidence must fail closed on every new authority boundary."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_b_strict_evidence.py"
spec = importlib.util.spec_from_file_location("stage_b_strict_contract", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def write_log(root: Path, name: str, text: str) -> tuple[str, str]:
    path = root / "validation" / "appliance-lifecycle-evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()


def fixture() -> tuple[Path, dict, dict]:
    root = Path(tempfile.mkdtemp(prefix="strict-stage-b-"))
    candidate = {
        "version": "1.58.151",
        "git_sha": "a" * 40,
        "code_sha256": "b" * 64,
        "identity_source": "git",
        "working_tree_clean": True,
        "version_stamps_consistent": True,
    }
    updater_hash = "c" * 64
    bootstrap_path, bootstrap_digest = write_log(
        root,
        "updater_binary_check.log",
        "\n".join(
            (
                "release_version=1.58.151",
                "asset_name=modelrig-updater-windows-x64.exe",
                f"expected_sha256={updater_hash}",
                f"actual_sha256={updater_hash}",
                "provenance_verified=true",
            )
        ) + "\n",
    )
    interruption_path, interruption_digest = write_log(
        root,
        "appliance_interruption.log",
        "\n".join(
            (
                "observed_journal_state=swapping",
                "observed_swapped_count=1",
                "updater_process_killed=true",
                "recovery_exit_code=0",
                "recovery_succeeded=true",
                "live_executables_present=true",
                "journal_absent=true",
            )
        ) + "\n",
    )
    lifecycle = {
        "schema": "kaliv-appliance-lifecycle-observations/v1",
        "candidate": {
            "version": candidate["version"],
            "git_sha": candidate["git_sha"],
            "code_sha256": candidate["code_sha256"],
        },
        "trials": {
            "good_update": {
                "source_version": "1.58.150",
                "target_version": "1.58.151",
            },
            "updater_bootstrap": {
                "performed": True,
                "release_version": "1.58.151",
                "release_git_sha": candidate["git_sha"],
                "asset_name": "modelrig-updater-windows-x64.exe",
                "expected_sha256": updater_hash,
                "actual_sha256": updater_hash,
                "provenance_verified": True,
                "evidence_path": bootstrap_path,
                "evidence_sha256": bootstrap_digest,
            },
            "appliance_interruption": {
                "performed": True,
                "source_version": "1.58.150",
                "observed_journal_state": "swapping",
                "observed_swapped_count": 1,
                "updater_process_killed": True,
                "recovery_exit_code": 0,
                "recovery_succeeded": True,
                "live_executables_present": True,
                "journal_absent": True,
                "ready": True,
                "backend_version": "1.58.150",
                "worker_version": "1.58.150",
                "evidence_path": interruption_path,
                "evidence_sha256": interruption_digest,
            },
        },
    }
    path = root / "validation" / "appliance-lifecycle-observations.json"
    path.write_text(json.dumps(lifecycle), encoding="utf-8")
    return root, candidate, lifecycle


def evaluate(root: Path, candidate: dict) -> tuple[dict, int]:
    return module.evaluate(
        root,
        Path("validation/appliance-lifecycle-observations.json"),
        candidate=candidate,
        now=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )

root, candidate, lifecycle = fixture()
report, code = evaluate(root, candidate)
check(code == 0 and report["gate"]["strict_evidence_complete"] is True, "valid strict bundle passes")
check(report["gate"]["production_activation"] is False, "strict gate cannot activate production")

mutations = (
    ("source version drift", lambda value: value["trials"]["good_update"].update(source_version="1.58.149")),
    ("bootstrap provenance absent", lambda value: value["trials"]["updater_bootstrap"].update(provenance_verified=False)),
    ("bootstrap hash mismatch", lambda value: value["trials"]["updater_bootstrap"].update(actual_sha256="d" * 64)),
    ("interruption before any swap", lambda value: value["trials"]["appliance_interruption"].update(observed_swapped_count=0)),
    ("interruption recovery failed", lambda value: value["trials"]["appliance_interruption"].update(recovery_succeeded=False)),
    ("journal left active", lambda value: value["trials"]["appliance_interruption"].update(journal_absent=False)),
)
for label, mutate in mutations:
    changed = copy.deepcopy(lifecycle)
    mutate(changed)
    (root / "validation" / "appliance-lifecycle-observations.json").write_text(
        json.dumps(changed), encoding="utf-8"
    )
    blocked, blocked_code = evaluate(root, candidate)
    check(blocked_code != 0 and blocked["gate"]["passed"] is False, label + " blocks")

print(f"strict Stage B contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
