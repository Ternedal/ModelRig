#!/usr/bin/env python3
"""Stage B one-click must measure the lifecycle evidence, never invent it."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / "scripts" / "stage_b_one_click.py"
LAUNCHER = ROOT / "START_STAGE_B_TEST.cmd"
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


check(WIZARD.is_file(), "the Stage B wizard exists")
check(LAUNCHER.is_file(), "the double-click launcher exists")
check(RUNBOOK.is_file(), "the Stage B runbook exists")

source = WIZARD.read_text(encoding="utf-8")
lower = source.lower()
launcher = LAUNCHER.read_text(encoding="utf-8").lower()
runbook = RUNBOOK.read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("stage_b_one_click_contract", WIZARD)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# The five lifecycle trials must all be driven, and the update must come FIRST.
#
# _validate_lifecycle compares reboot.backend_version, reboot.worker_version and
# both supervisor_*.active_version against the CANDIDATE's version. Until the
# good update lands, the rig is still running the previous release, so measuring
# those trials first attests the wrong version and the campaign rejects the
# bundle with "expected <candidate>, got <previous>". This assertion had the
# order backwards and pinned the bug in place; the physical run on 1.58.149
# proved it. Reboot and the supervisor restarts are claims about the candidate,
# so they must be measured while the candidate is what is running.
flow = (
    "trial_good_update(observations, state)",
    "trial_reboot(observations, state)",
    'trial_supervisor(observations, state, "backend", 8080)',
    'trial_supervisor(observations, state, "worker", 8099)',
    "trial_bad_update(observations, state)",
)
check(all(step in source for step in flow), "all five lifecycle trials are driven")
check([source.index(s) for s in flow] == sorted(source.index(s) for s in flow),
      "the good update runs before the trials that must observe the candidate")

# Every field the chain validator reads must be measured, not typed by a human.
for probe, label in (
    ("def candidate_identity", "candidate identity is read from the repo"),
    ("code_fingerprint", "the worker fingerprint comes from build_identity"),
    ("def live_versions", "versions are read from the running appliance"),
    ("def wait_ready", "readiness is timed, not estimated"),
    ("def sha256_file", "log digests are computed from the log bytes"),
    ("def data_snapshot", "data and schedule survival is counted before and after"),
):
    check(probe in source, label)

# The three identity fields the validator rejected when they were left unset.
check("def released_commit" in source
      and 'released_commit(source_version)' in source
      and 'state.get("source_git_sha")' not in source,
      "good_update.source_git_sha is resolved from the source release tag")
check("must differ from the candidate" in source,
      "the source-SHA helper records why it may not be the candidate's own SHA")
check("def remote_release_identity" in source
      and "remote_release_identity(bad_repo)" in source
      and '"attempted_version": attempted_version' in source
      and '"attempted_git_sha": attempted_git_sha' in source,
      "bad_update names the release it actually attempted")

# Both token-backed readings sit behind experimental flags a normal appliance
# does not set, so the bundle must bind the running build to things that are
# always measurable: the installed worker exe and the schedule store on disk.
check("def installed_worker_exe_sha256" in source
      and "def released_worker_exe_sha256" in source
      and '"worker_exe_sha256"' in source
      and '"active_exe_sha256"' in source,
      "the running worker is bound to the installed exe, not an experimental route")
check("KALIV_AGENT3_ENABLED" in source and "KALIV_SCHEDULER_API" in source,
      "preflight records why the token-backed readings are optional")
check("Kunne ikke hente" in source and "worker-binding" in source,
      "preflight stops when the worker binding cannot be established")
check('"schedules_binding": after_data["schedules_binding"]' in source
      and "store_digest" in source,
      "schedules name the binding that produced them")

check("evidence_sha256" in source and "sha256_file(log)" in source,
      "each trial stamps its own log digest")
check('"validation/appliance-lifecycle-evidence/' in source,
      "evidence paths stay under the directory the validator requires")

# Fail-closed behaviour: the wizard must refuse rather than fabricate.
check("update-transaction.json findes stadig" in source,
      "an unfinished updater transaction blocks the run")
check("Riggen kører allerede" in source,
      "a rig already on the candidate version cannot prove an update")
check("beviser hverken en afvisning" in source,
      "a bad_update log proving neither refusal nor rollback is rejected")
check("Working tree er ikke ren" in source,
      "a dirty checkout blocks Stage B")

# Resumability, mirroring Stage A.
check("stage-b-easy-state.json" in source and "def save_state" in source,
      "progress is checkpointed so a safe stop can resume")
check(all(f'state.get("{k}")' in source for k in
          ("reboot_done", "good_update_done", "bad_update_done")),
      "completed trials are skipped on resume")

# The invalid update is operator-gated and repo-driven, never silently run.
check("KALIV_STAGE_B_BAD_REPO" in source, "the negative fixture repo is configurable")
check('answer.upper() != "JA"' in source,
      "the invalid update requires an explicit operator approval")

# Promotion boundary.
for forbidden in ("git push", "git tag", "gh release", "merge_pull_request",
                  "production_activation=true", "insecure-skip-verify",
                  "skip-attestation", "no-heartbeat-check"):
    check(forbidden not in lower, f"wizard has no forbidden action: {forbidden}")
    check(forbidden not in launcher, f"launcher has no forbidden action: {forbidden}")

check(module.LIFECYCLE_SCHEMA == "kaliv-appliance-lifecycle-observations/v1",
      "the wizard writes the schema the chain validator reads")
check(EXAMPLE.is_file() and module.EXAMPLE == EXAMPLE,
      "observations are seeded from the tracked example")

# The runbook must describe the current release and the now-documented method.
check("1.58.148" in runbook and "1.58.145" not in runbook,
      "the runbook names the current release, not a stale one")
check("ModelRig-updater-negative" in runbook,
      "the runbook documents how the invalid update is produced")
check("START_STAGE_B_TEST.cmd" in runbook,
      "the runbook points at the one-click path")

print(f"Stage B one-click contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
