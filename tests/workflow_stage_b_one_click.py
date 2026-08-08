#!/usr/bin/env python3
"""Stage B one-click must measure lifecycle evidence, never invent it."""
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
WIZARD = ROOT / "scripts" / "stage_b_one_click.py"
STRICT_WIZARD = ROOT / "scripts" / "stage_b_one_click_v2.py"
STRICT_GATE = ROOT / "scripts" / "stage_b_strict_evidence.py"
STRICT_FINAL = ROOT / "scripts" / "stage_b_physical_gate_v2.py"
LAUNCHER = ROOT / "START_STAGE_B_TEST.cmd"
VERIFY_LAUNCHER = ROOT / "VERIFY_STAGE_B_EVIDENCE.cmd"
RUNBOOK = ROOT / "STAGE_B_UPDATER_EVIDENCE.md"
EXAMPLE = ROOT / "eval" / "appliance_lifecycle_observations.example.json"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(WIZARD.is_file(), "the Stage B lifecycle wizard exists")
check(STRICT_WIZARD.is_file(), "the strict Stage B wrapper exists")
check(STRICT_GATE.is_file(), "the strict semantic gate exists")
check(STRICT_FINAL.is_file(), "the strict final wrapper exists")
check(LAUNCHER.is_file(), "the double-click launcher exists")
check(VERIFY_LAUNCHER.is_file(), "the final verifier launcher exists")
check(RUNBOOK.is_file(), "the Stage B runbook exists")

source = WIZARD.read_text(encoding="utf-8")
lower = source.lower()
strict_source = STRICT_WIZARD.read_text(encoding="utf-8")
strict_gate_source = STRICT_GATE.read_text(encoding="utf-8")
strict_final_source = STRICT_FINAL.read_text(encoding="utf-8")
launcher = LAUNCHER.read_text(encoding="utf-8").lower()
verify_launcher = VERIFY_LAUNCHER.read_text(encoding="utf-8").lower()
runbook = RUNBOOK.read_text(encoding="utf-8")
example_text = EXAMPLE.read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("stage_b_one_click_contract", WIZARD)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Trials that claim the target identity must run after the good update.
flow = (
    "trial_good_update(observations, state)",
    "trial_reboot(observations, state)",
    'trial_supervisor(observations, state, "backend", 8080)',
    'trial_supervisor(observations, state, "worker", 8099)',
    "trial_bad_update(observations, state)",
)
check(all(step in source for step in flow), "all five lifecycle trials are driven")
check(
    [source.index(s) for s in flow] == sorted(source.index(s) for s in flow),
    "the good update runs before the trials that must observe the candidate",
)

for probe, label in (
    ("def candidate_identity", "candidate identity is read from the repo"),
    ("code_fingerprint", "the worker fingerprint comes from build_identity"),
    ("def live_versions", "versions are read from the running appliance"),
    ("def wait_ready", "readiness is timed, not estimated"),
    ("def sha256_file", "log digests are computed from the log bytes"),
    ("def data_snapshot", "data and schedule survival is counted before and after"),
):
    check(probe in source, label)

check(
    "def released_commit" in source
    and "released_commit(source_version)" in source
    and 'state.get("source_git_sha")' not in source,
    "good_update.source_git_sha is resolved from the source release tag",
)
check(
    "must differ from the candidate" in source,
    "the source-SHA helper records why it may not be the candidate's own SHA",
)
check(
    "def remote_release_identity" in source
    and "remote_release_identity(bad_repo)" in source
    and '"attempted_version": attempted_version' in source
    and '"attempted_git_sha": attempted_git_sha' in source,
    "bad_update names the release it actually attempted",
)

_probe = Path(tempfile.mkdtemp(prefix="stage-b-root-"))
(_probe / "VERSION").write_text("9.9.9\n", encoding="utf-8")
_original_root = module.ROOT
try:
    module.use_root(_probe)
    check(module.ROOT == _probe.resolve(), "use_root repoints the wizard at the given checkout")
    _seen = module.capture(
        [sys.executable, "-c", "import os,sys; sys.stdout.write(os.getcwd())"]
    )
    check(
        Path(_seen).resolve() == _probe.resolve(),
        "capture runs in the checkout use_root selected, not the wizard's own",
    )
finally:
    module.use_root(_original_root)

check(
    "def installed_worker_exe_sha256" in source
    and "def released_worker_exe_sha256" in source
    and '"worker_exe_sha256"' in source
    and '"active_exe_sha256"' in source,
    "the running worker is bound to the installed exe, not an experimental route",
)
check(
    "KALIV_AGENT3_ENABLED" in source and "KALIV_SCHEDULER_API" in source,
    "preflight records why the token-backed readings are optional",
)
check(
    "Kunne ikke hente" in source and "worker-binding" in source,
    "preflight stops when the worker binding cannot be established",
)
check(
    '"schedules_binding": after_data["schedules_binding"]' in source
    and "store_digest" in source,
    "schedules name the binding that produced them",
)
check(
    "evidence_sha256" in source and "sha256_file(log)" in source,
    "each lifecycle trial stamps its own log digest",
)
check(
    '"validation/appliance-lifecycle-evidence/' in source,
    "evidence paths stay under the directory the validator requires",
)
check(
    "update-transaction.json findes stadig" in source,
    "an unfinished updater transaction blocks the lifecycle run",
)
check(
    "Riggen kører allerede" in source,
    "a rig already on the candidate version cannot prove an update",
)
check(
    "beviser hverken en afvisning" in source,
    "a bad_update log proving neither refusal nor rollback is rejected",
)
check("Working tree er ikke ren" in source, "a dirty checkout blocks Stage B")
check(
    "stage-b-easy-state.json" in source and "def save_state" in source,
    "progress is checkpointed so a safe stop can resume",
)
check(
    all(
        f'state.get("{k}")' in source
        for k in ("reboot_done", "good_update_done", "bad_update_done")
    ),
    "completed lifecycle trials are skipped on resume",
)
check("KALIV_STAGE_B_BAD_REPO" in source, "the negative fixture repo is configurable")
check(
    'answer.upper() != "JA"' in source,
    "the invalid update requires an explicit operator approval",
)

# The advertised entrypoints must wrap the legacy lifecycle engine in the strict layer.
check("stage_b_one_click_v2.py" in launcher, "double-click path uses the strict wizard")
check("stage_b_physical_gate_v2.py" in verify_launcher, "final verifier uses the strict final gate")
check('EXPECTED_SOURCE_VERSION = "1.58.150"' in strict_source, "strict wizard pins the source release")
check('EXPECTED_TARGET_VERSION = "1.58.151"' in strict_source, "strict wizard pins the target release")
check('"gh", "attestation", "verify"' in strict_source, "strict wizard verifies GitHub build provenance")
check("expected_sha256" in strict_source and "actual_sha256" in strict_source, "strict wizard measures bootstrap checksum identity")
check('observed_state == "swapping" and observed_swapped' in strict_source, "strict wizard kills only after a recorded live swap")
check('[str(updater), "-recover"]' in strict_source, "strict wizard performs offline whole-set recovery")
check("_all_live_executables_present" in strict_source, "strict wizard proves every live executable remains present")
check("stage_b_strict_evidence.py" in strict_final_source, "final wrapper executes the strict semantic gate")
check("strict_stage_b" in strict_final_source and "strict_evidence_complete" in strict_final_source, "final receipt hash-binds strict evidence")
check("good_update.source_version must be" in strict_gate_source, "strict gate rejects a non-1.58.150 source")
check("updater_bootstrap provenance was not verified" in strict_gate_source, "strict gate requires measured provenance")
check("did not observe a completed live swap" in strict_gate_source, "strict gate requires a real interrupted swap")
check('"updater_bootstrap"' in example_text, "observation template carries bootstrap evidence")
check('"appliance_interruption"' in example_text, "observation template carries interruption evidence")

for text, label in (
    (lower, "lifecycle wizard"),
    (launcher, "start launcher"),
    (verify_launcher, "verify launcher"),
    (strict_source.lower(), "strict wizard"),
    (strict_final_source.lower(), "strict final gate"),
):
    for forbidden in (
        "git push",
        "git tag",
        "gh release create",
        "merge_pull_request",
        "production_activation=true",
        "insecure-skip-verify",
        "skip-attestation",
        "no-heartbeat-check",
    ):
        check(forbidden not in text, f"{label} has no forbidden authority: {forbidden}")

check(
    module.LIFECYCLE_SCHEMA == "kaliv-appliance-lifecycle-observations/v1",
    "the lifecycle wizard writes the schema the chain validator reads",
)
check(
    EXAMPLE.is_file() and module.EXAMPLE == EXAMPLE,
    "observations are seeded from the tracked example",
)

# Mutation-test the strict gate directly.
strict_spec = importlib.util.spec_from_file_location("stage_b_strict_contract", STRICT_GATE)
assert strict_spec is not None and strict_spec.loader is not None
strict_module = importlib.util.module_from_spec(strict_spec)
strict_spec.loader.exec_module(strict_module)


def write_log(root: Path, name: str, text: str) -> tuple[str, str]:
    path = root / "validation" / "appliance-lifecycle-evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()


strict_root = Path(tempfile.mkdtemp(prefix="strict-stage-b-"))
strict_candidate = {
    "version": "1.58.151",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
    "working_tree_clean": True,
    "version_stamps_consistent": True,
}
updater_hash = "c" * 64
bootstrap_path, bootstrap_digest = write_log(
    strict_root,
    "updater_binary_check.log",
    "\n".join((
        "release_version=1.58.151",
        "asset_name=modelrig-updater-windows-x64.exe",
        f"expected_sha256={updater_hash}",
        f"actual_sha256={updater_hash}",
        "provenance_verified=true",
    )) + "\n",
)
interruption_path, interruption_digest = write_log(
    strict_root,
    "appliance_interruption.log",
    "\n".join((
        "observed_journal_state=swapping",
        "observed_swapped_count=1",
        "updater_process_killed=true",
        "recovery_exit_code=0",
        "recovery_succeeded=true",
        "live_executables_present=true",
        "journal_absent=true",
    )) + "\n",
)
strict_lifecycle = {
    "schema": "kaliv-appliance-lifecycle-observations/v1",
    "candidate": {
        "version": strict_candidate["version"],
        "git_sha": strict_candidate["git_sha"],
        "code_sha256": strict_candidate["code_sha256"],
    },
    "trials": {
        "good_update": {"source_version": "1.58.150", "target_version": "1.58.151"},
        "updater_bootstrap": {
            "performed": True,
            "release_version": "1.58.151",
            "release_git_sha": strict_candidate["git_sha"],
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
strict_path = strict_root / "validation" / "appliance-lifecycle-observations.json"
strict_path.write_text(json.dumps(strict_lifecycle), encoding="utf-8")


def evaluate_strict(value: dict) -> tuple[dict, int]:
    strict_path.write_text(json.dumps(value), encoding="utf-8")
    return strict_module.evaluate(
        strict_root,
        Path("validation/appliance-lifecycle-observations.json"),
        candidate=strict_candidate,
        now=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )


strict_report, strict_code = evaluate_strict(strict_lifecycle)
check(strict_code == 0 and strict_report["gate"]["strict_evidence_complete"] is True, "valid strict bundle passes")
check(strict_report["gate"]["production_activation"] is False, "strict gate cannot activate production")
for label, mutate in (
    ("source version drift", lambda value: value["trials"]["good_update"].update(source_version="1.58.149")),
    ("bootstrap provenance absent", lambda value: value["trials"]["updater_bootstrap"].update(provenance_verified=False)),
    ("bootstrap hash mismatch", lambda value: value["trials"]["updater_bootstrap"].update(actual_sha256="d" * 64)),
    ("interruption before any swap", lambda value: value["trials"]["appliance_interruption"].update(observed_swapped_count=0)),
    ("interruption recovery failed", lambda value: value["trials"]["appliance_interruption"].update(recovery_succeeded=False)),
    ("journal left active", lambda value: value["trials"]["appliance_interruption"].update(journal_absent=False)),
):
    changed = copy.deepcopy(strict_lifecycle)
    mutate(changed)
    blocked, blocked_code = evaluate_strict(changed)
    check(blocked_code != 0 and blocked["gate"]["passed"] is False, label + " blocks")

# The operator runbook must name the live campaign and strict boundary.
check(
    "1.58.151" in runbook
    and "1.58.150" in runbook
    and "1.58.148" not in runbook
    and "1.58.147" not in runbook,
    "the runbook names the current source and target releases only",
)
check(
    "bootstrap" in runbook.lower()
    and "#401" in runbook
    and "blokerer ikke promotion" in runbook,
    "the runbook separates the one-time bootstrap from deferred signed-to-signed proof",
)
check("state=swapping" in runbook and "swapped_count>=1" in runbook, "the runbook requires a recorded mid-swap interruption")
check("ModelRig-updater-negative" in runbook, "the runbook documents how the invalid update is produced")
check("START_STAGE_B_TEST.cmd" in runbook, "the runbook points at the strict one-click path")
check("VERIFY_STAGE_B_EVIDENCE.cmd" in runbook, "the runbook points at the strict final verifier")
check("strict_evidence_complete=true" in runbook, "the runbook requires strict evidence in the final receipt")

print(f"Stage B one-click contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
