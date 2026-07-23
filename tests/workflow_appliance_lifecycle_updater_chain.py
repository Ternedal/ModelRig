#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "appliance_lifecycle_updater_chain.py"


def load_module():
    spec = importlib.util.spec_from_file_location("updater_chain_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = load_module()
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
CANDIDATE = {
    "version": "1.58.145",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "branch": "agent/unified-candidate-1.58.145",
    "working_tree_clean": True,
    "dirty_entries": 0,
    "identity_source": "git",
    "version_stamps_consistent": True,
    "version_check_detail": None,
}

GOOD_LOG = """updater: update available: 1.58.144 -> v1.58.145
updater: downloading modelrig-server-windows-x64.exe
updater: downloading modelrig-supervisor-windows-x64.exe
updater: downloading modelrig-worker-windows-x64.exe
updater: checksums verified for 3 exe(s)
updater: build provenance verified for 3 exe(s)
updater: stopping supervisor + processes so the exes unlock
updater: supervisor heartbeat advanced past the restart -- crash-recovery is running
updater: update OK: backend + worker report 1.58.145 and the supervisor is looping. Backup kept at backups/test
"""

BAD_REJECTION_LOG = """updater: update available: 1.58.145 -> v1.58.146
updater: downloading modelrig-server-windows-x64.exe
updater: downloading modelrig-supervisor-windows-x64.exe
updater: downloading modelrig-worker-windows-x64.exe
updater: FATAL: NO BUILD PROVENANCE for modelrig-server-windows-x64.exe -- refusing to install
"""

BAD_ROLLBACK_LOG = """updater: update available: 1.58.145 -> v1.58.146
updater: downloading modelrig-server-windows-x64.exe
updater: downloading modelrig-supervisor-windows-x64.exe
updater: downloading modelrig-worker-windows-x64.exe
updater: checksums verified for 3 exe(s)
updater: build provenance verified for 3 exe(s)
updater: stopping supervisor + processes so the exes unlock
updater: update did not come up healthy + alive on 1.58.146 -- ROLLING BACK to 1.58.145
updater: rolled back to 1.58.145: backend + worker healthy and the supervisor is looping
"""


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def lifecycle_fixture(base: Path, *, bad_log: str = BAD_REJECTION_LOG) -> tuple[Path, Path, Path]:
    good_path = base / "good_update.log"
    bad_path = base / "bad_update.log"
    good_path.write_text(GOOD_LOG, encoding="utf-8")
    bad_path.write_text(bad_log, encoding="utf-8")
    lifecycle = {
        "schema": module.LIFECYCLE_SCHEMA,
        "candidate": {
            "version": CANDIDATE["version"],
            "git_sha": CANDIDATE["git_sha"],
            "code_sha256": CANDIDATE["code_sha256"],
        },
        "host": {"hostname": "rig", "windows_version": "Windows test"},
        "started_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "trials": {
            "good_update": {
                "performed": True,
                "source_version": "1.58.144",
                "source_git_sha": "c" * 40,
                "target_version": CANDIDATE["version"],
                "target_git_sha": CANDIDATE["git_sha"],
                "target_code_sha256": CANDIDATE["code_sha256"],
                "ready": True,
                "rollback_observed": False,
                "data_preserved": True,
                "schedules_preserved": True,
                "evidence_path": str(good_path.relative_to(ROOT)),
                "evidence_sha256": hashlib.sha256(GOOD_LOG.encode()).hexdigest(),
            },
            "bad_update": {
                "performed": True,
                "attempted_version": "1.58.146",
                "attempted_git_sha": "d" * 40,
                "rejected_or_rolled_back": True,
                "active_version": CANDIDATE["version"],
                "active_git_sha": CANDIDATE["git_sha"],
                "active_code_sha256": CANDIDATE["code_sha256"],
                "ready": True,
                "data_preserved": True,
                "schedules_preserved": True,
                "evidence_path": str(bad_path.relative_to(ROOT)),
                "evidence_sha256": hashlib.sha256(bad_log.encode()).hexdigest(),
            },
        },
    }
    lifecycle_path = base / "lifecycle.json"
    write_json(lifecycle_path, lifecycle)
    return lifecycle_path, good_path, bad_path


artifact_root = ROOT / "validation" / "appliance-lifecycle-evidence"
artifact_root.mkdir(parents=True, exist_ok=True)
temp = Path(tempfile.mkdtemp(prefix="updater-chain-test-", dir=artifact_root))
try:
    lifecycle_path, good_path, bad_path = lifecycle_fixture(temp)
    report, code = module.evaluate(
        ROOT,
        lifecycle_path.relative_to(ROOT),
        candidate=CANDIDATE,
        now=NOW,
    )
    check(code == 0 and report["gate"]["passed"] is True,
          "full updater chain passes")
    check(report["evidence"]["good_update"]["outcome"] == "committed_and_healthy",
          "good update proves committed healthy outcome")
    check(report["evidence"]["bad_update"]["outcome"] == "rejected_before_swap",
          "invalid update proves pre-swap refusal")
    check(report["gate"]["production_activation"] is False,
          "updater chain cannot activate production")

    lifecycle_path, good_path, bad_path = lifecycle_fixture(temp, bad_log=BAD_ROLLBACK_LOG)
    report, code = module.evaluate(
        ROOT,
        lifecycle_path.relative_to(ROOT),
        candidate=CANDIDATE,
        now=NOW,
    )
    check(code == 0 and report["evidence"]["bad_update"]["outcome"] == "rolled_back_and_recovered",
          "completed healthy rollback is accepted")

    lifecycle_path, good_path, bad_path = lifecycle_fixture(temp)
    weakened = GOOD_LOG.replace(
        "updater: supervisor heartbeat advanced past the restart -- crash-recovery is running\n",
        "",
    )
    good_path.write_text(weakened, encoding="utf-8")
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    lifecycle["trials"]["good_update"]["evidence_sha256"] = hashlib.sha256(
        weakened.encode()
    ).hexdigest()
    write_json(lifecycle_path, lifecycle)
    report, code = module.evaluate(
        ROOT,
        lifecycle_path.relative_to(ROOT),
        candidate=CANDIDATE,
        now=NOW,
    )
    check(code == 1 and any("heartbeat" in error for error in report["summary"]["errors"]),
          "a health-only update without heartbeat proof fails")

    lifecycle_path, good_path, bad_path = lifecycle_fixture(temp)
    bypassed = GOOD_LOG + "updater: WARNING: installing WITHOUT provenance verification (-skip-attestation)\n"
    good_path.write_text(bypassed, encoding="utf-8")
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    lifecycle["trials"]["good_update"]["evidence_sha256"] = hashlib.sha256(
        bypassed.encode()
    ).hexdigest()
    write_json(lifecycle_path, lifecycle)
    report, code = module.evaluate(
        ROOT,
        lifecycle_path.relative_to(ROOT),
        candidate=CANDIDATE,
        now=NOW,
    )
    check(code == 1 and any("without provenance" in error for error in report["summary"]["errors"]),
          "provenance bypass fails even when the update otherwise looks green")

    lifecycle_path, good_path, bad_path = lifecycle_fixture(temp)
    after_stop = BAD_REJECTION_LOG + "updater: stopping supervisor + processes so the exes unlock\n"
    bad_path.write_text(after_stop, encoding="utf-8")
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    lifecycle["trials"]["bad_update"]["evidence_sha256"] = hashlib.sha256(
        after_stop.encode()
    ).hexdigest()
    write_json(lifecycle_path, lifecycle)
    report, code = module.evaluate(
        ROOT,
        lifecycle_path.relative_to(ROOT),
        candidate=CANDIDATE,
        now=NOW,
    )
    check(code == 1 and report["evidence"]["bad_update"]["outcome"] == "unproven",
          "a supposed pre-swap refusal after process stop is rejected")

    lifecycle_path, _, _ = lifecycle_fixture(temp)
    journal = ROOT / "update-transaction.json"
    journal.write_text("{}\n", encoding="utf-8")
    try:
        report, code = module.evaluate(
            ROOT,
            lifecycle_path.relative_to(ROOT),
            candidate=CANDIDATE,
            now=NOW,
        )
    finally:
        journal.unlink(missing_ok=True)
    check(code == 1 and any("not terminal" in error for error in report["summary"]["errors"]),
          "a pending updater transaction blocks Stage B")

    lifecycle_path, good_path, _ = lifecycle_fixture(temp)
    good_path.write_text("tampered\n", encoding="utf-8")
    report, code = module.evaluate(
        ROOT,
        lifecycle_path.relative_to(ROOT),
        candidate=CANDIDATE,
        now=NOW,
    )
    check(code == 1 and any("does not match" in error for error in report["summary"]["errors"]),
          "tampered updater log fails its bound hash")
finally:
    shutil.rmtree(temp, ignore_errors=True)

source = SCRIPT.read_text(encoding="utf-8").lower()
for forbidden in (
    "git push",
    "git tag",
    "gh release",
    "merge_pull_request",
    "production_activation=true",
):
    check(forbidden not in source, f"updater-chain gate has no forbidden action: {forbidden}")

print(f"Updater-chain contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
