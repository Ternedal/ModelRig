#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "agent3_write_pilot_final_gate.py"
ENTRY_PATH = ROOT / "scripts" / "agent3_write_pilot_final_gate_operator.py"
LAUNCHER = ROOT / "START_AGENT3_WRITE_PILOT.cmd"
RUNBOOK = ROOT / "AGENT3_WRITE_PILOT_FINAL_GATE.md"
WORKFLOW = ROOT / ".github" / "workflows" / "agent3-write-pilot-final-gate.yml"
CORE_SOURCE = code_of(CORE_PATH)
ENTRY_SOURCE = code_of(ENTRY_PATH)
LAUNCHER_SOURCE = code_of(LAUNCHER)
RUNBOOK_SOURCE = code_of(RUNBOOK)
WORKFLOW_SOURCE = code_of(WORKFLOW)

spec = importlib.util.spec_from_file_location("t022_final_gate_test", ENTRY_PATH)
assert spec is not None and spec.loader is not None
entry = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = entry
spec.loader.exec_module(entry)
entry.install_policy()
core = entry.core

NOW = datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc)
IDENTITY = {
    "version": core.VERSION,
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
    "working_tree_clean": True,
    "version_stamps_consistent": True,
    "branch": core.BRANCH,
}

checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def fixture_report(*, iso_positive_times: bool = False) -> dict:
    window_start = NOW - timedelta(hours=1)
    window_finish = NOW - timedelta(minutes=10)
    generated = NOW - timedelta(minutes=5)
    positives = []
    for ordinal in range(1, 21):
        created = window_start + timedelta(seconds=ordinal)
        used = created + timedelta(seconds=1)
        updated = used + timedelta(seconds=1)
        positives.append(
            {
                "run_id": f"run-{ordinal}",
                "step_id": f"step-{ordinal}",
                "device_id": "paired-device-1",
                "plan_revision": 0,
                "marker_sha256": digest(f"positive-marker-{ordinal}"),
                "created_at": iso(created) if iso_positive_times else created.timestamp(),
                "updated_at": iso(updated) if iso_positive_times else updated.timestamp(),
                "approval_used_at": iso(used) if iso_positive_times else used.timestamp(),
                "ordinal": ordinal,
            }
        )
    negative_specs = [
        ("deny", [200], ["neg-deny"]),
        ("timeout", [409], ["neg-timeout"]),
        ("changed_args", [409], ["run-1"]),
        ("stale_revision", [409], ["run-2"]),
        ("replay", [409], ["run-3"]),
        ("concurrent_approval", [409, 200], ["neg-concurrent"]),
        ("stop_retry_replan", [409, 200, 202, 409], ["run-4", "run-5", "run-6"]),
    ]
    negatives = [
        {
            "name": name,
            "run_ids": run_ids,
            "request_statuses": statuses,
            "marker_sha256": digest(f"negative-marker-{name}"),
            "observed_at": iso(NOW - timedelta(minutes=20, seconds=index)),
        }
        for index, (name, statuses, run_ids) in enumerate(negative_specs, start=1)
    ]
    evidence = {
        key: digest(key)
        for key in sorted(core.EXPECTED_EVIDENCE_KEYS)
    }
    return {
        "schema": core.REPORT_SCHEMA,
        "success": True,
        "generated_at": iso(generated),
        "candidate": copy.deepcopy(IDENTITY),
        "pilot_id": "c" * 32,
        "operator": "Anders",
        "evidence": evidence,
        "summary": {
            "positive_runs_expected": 20,
            "positive_runs_proven": 20,
            "negative_cases_expected": 7,
            "negative_cases_present": 7,
            "device_id": "paired-device-1",
            "window_started_at": iso(window_start),
            "window_finished_at": iso(window_finish),
            "production_activation": False,
        },
        "positive_runs": positives,
        "negative_cases": negatives,
        "blockers": [],
        "production_activation": False,
    }


def assess(value: dict, identity: dict | None = None, now: datetime = NOW) -> dict:
    return core.assess_report(
        value,
        current_identity=copy.deepcopy(identity or IDENTITY),
        report_sha256=digest("report"),
        now=now,
        max_age_hours=24.0,
    )


check("final gate core exists", CORE_PATH.is_file())
check("safe final gate entrypoint exists", ENTRY_PATH.is_file())
check("top-level launcher exists", LAUNCHER.is_file())
check("final gate runbook exists", RUNBOOK.is_file())
check("dormant final gate workflow exists", WORKFLOW.is_file())
check(
    "launcher invokes only the safe final gate entrypoint",
    "agent3_write_pilot_final_gate_operator.py" in LAUNCHER_SOURCE
    and "agent3_write_pilot_collect_one_click.py" not in LAUNCHER_SOURCE,
)
check(
    "final gate is pinned to its exact branch and version",
    'BRANCH = "agent/t022-write-pilot-final-gate"' in CORE_SOURCE
    and 'VERSION = "1.58.146"' in CORE_SOURCE,
)
check(
    "final gate adds no write HTTP transport",
    "urllib.request" not in CORE_SOURCE
    and 'method="POST"' not in CORE_SOURCE
    and 'method="PUT"' not in CORE_SOURCE
    and 'method="PATCH"' not in CORE_SOURCE
    and 'method="DELETE"' not in CORE_SOURCE,
)
check(
    "final gate reuses the existing combined collector",
    "collector.main()" in CORE_SOURCE
    and "collector.BRANCH = BRANCH" in CORE_SOURCE
    and "collector.configure_candidate()" in CORE_SOURCE,
)
check(
    "safe entrypoint aligns numeric or ISO timestamps",
    "core._number = timestamp_seconds" in ENTRY_SOURCE
    and "core._parse_time(value)" in ENTRY_SOURCE,
)
check(
    "safe entrypoint preserves the flexible stop sequence contract",
    'name == "stop_retry_replan"' in ENTRY_SOURCE
    and "len(statuses) < 3" in ENTRY_SOURCE
    and "status not in {200, 202, 409}" in ENTRY_SOURCE,
)
check(
    "hosted workflow is manual-only",
    "workflow_dispatch:" in WORKFLOW_SOURCE
    and "pull_request:" not in WORKFLOW_SOURCE
    and "push:" not in WORKFLOW_SOURCE
    and "schedule:" not in WORKFLOW_SOURCE,
)
check(
    "hosted workflow cannot consume rig secrets or claim physical execution",
    "secrets." not in WORKFLOW_SOURCE
    and "does not access the Windows rig" in WORKFLOW_SOURCE
    and "production_activation=false" in WORKFLOW_SOURCE,
)
check(
    "hosted workflow runs only the deterministic final gate contract",
    "python tests/workflow_agent3_write_pilot_final_gate.py" in WORKFLOW_SOURCE,
)
check(
    "runbook states the hosted/local physical boundary",
    "kun manuel `workflow_dispatch`" in RUNBOOK_SOURCE
    and "kan ikke gøre en ikke-fysisk rapport fysisk" in RUNBOOK_SOURCE,
)

valid = assess(fixture_report())
check("complete exact report passes", valid["gate"]["passed"] is True)
check("green gate is explicitly non-activating", valid["gate"]["production_activation"] is False)
check(
    "green gate proves exact 20 plus 7 inventory",
    valid["summary"]["positive_runs_proven"] == 20
    and valid["summary"]["negative_cases_proven"] == 7
    and valid["gate"]["inventory_complete"] is True,
)
serialized_gate = json.dumps(valid, sort_keys=True)
check(
    "sanitized gate omits raw run step and device identifiers",
    "run-1" not in serialized_gate
    and "step-1" not in serialized_gate
    and "paired-device-1" not in serialized_gate,
)

valid_iso = assess(fixture_report(iso_positive_times=True))
check("ISO positive timestamps are accepted", valid_iso["gate"]["passed"] is True)

mutations: list[tuple[str, callable, str]] = [
    (
        "production activation is rejected",
        lambda value: value.__setitem__("production_activation", True),
        "report_production_activation_not_false",
    ),
    (
        "collector blocker is rejected",
        lambda value: value["blockers"].append("physical mismatch"),
        "report_contains_blockers",
    ),
    (
        "nineteen positive runs are rejected",
        lambda value: value["positive_runs"].pop(),
        "positive_runs_count_invalid",
    ),
    (
        "duplicate positive ordinal is rejected",
        lambda value: value["positive_runs"][1].__setitem__("ordinal", 1),
        "positive_ordinal_duplicate",
    ),
    (
        "missing negative case is rejected",
        lambda value: value["negative_cases"].pop(),
        "negative_cases_count_invalid",
    ),
    (
        "wrong replay status is rejected",
        lambda value: next(
            item for item in value["negative_cases"] if item["name"] == "replay"
        ).__setitem__("request_statuses", [200]),
        "negative_replay_statuses_mismatch",
    ),
    (
        "short stop sequence is rejected",
        lambda value: next(
            item for item in value["negative_cases"] if item["name"] == "stop_retry_replan"
        ).__setitem__("request_statuses", [200, 409]),
        "negative_stop_retry_replan_statuses_mismatch",
    ),
    (
        "invalid evidence hash is rejected",
        lambda value: value["evidence"].__setitem__("notes_sha256", "bad"),
        "evidence_notes_sha256_invalid",
    ),
    (
        "report candidate branch drift is rejected",
        lambda value: value["candidate"].__setitem__("branch", "main"),
        "report_candidate_branch_mismatch",
    ),
]
for label, mutate, expected in mutations:
    value = fixture_report()
    mutate(value)
    result = assess(value)
    expected_present = any(
        blocker == expected or blocker.startswith(f"{expected}:")
        for blocker in result["blockers"]
    )
    check(label, result["gate"]["passed"] is False and expected_present)

stale = fixture_report()
stale["generated_at"] = iso(NOW - timedelta(hours=25))
stale_result = assess(stale)
check("stale report is rejected", "report_stale" in stale_result["blockers"])

future = fixture_report()
future["generated_at"] = iso(NOW + timedelta(minutes=6))
future_result = assess(future)
check("future report is rejected", "report_from_future" in future_result["blockers"])

changed_identity = copy.deepcopy(IDENTITY)
changed_identity["git_sha"] = "d" * 40
sha_drift = assess(fixture_report(), identity=changed_identity)
check("current SHA drift is rejected", "candidate_git_sha_mismatch" in sha_drift["blockers"])

dirty_identity = copy.deepcopy(IDENTITY)
dirty_identity["working_tree_clean"] = False
dirty = assess(fixture_report(), identity=dirty_identity)
check("dirty current candidate is rejected", "current_candidate_working_tree_not_clean" in dirty["blockers"])

wide_window = fixture_report()
wide_window["summary"]["window_started_at"] = iso(NOW - timedelta(hours=13))
wide = assess(wide_window)
check("pilot window over twelve hours is rejected", "summary_window_exceeds_12_hours" in wide["blockers"])

with tempfile.TemporaryDirectory(prefix="kaliv-t022-final-gate-") as tmp:
    root = Path(tmp)
    report_path = root / "report.json"
    report_raw = (json.dumps(fixture_report(), sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_raw)
    old_identity = core.candidate_identity
    old_report = core.REPORT
    core.candidate_identity = lambda _root: copy.deepcopy(IDENTITY)
    core.REPORT = report_path
    try:
        from_file = core.assess_report_file(report_path, now=NOW)
    finally:
        core.candidate_identity = old_identity
        core.REPORT = old_report
    check(
        "regular local report file is hashed and assessed",
        from_file["gate"]["passed"] is True
        and from_file["report"]["sha256"] == hashlib.sha256(report_raw).hexdigest(),
    )

with tempfile.TemporaryDirectory(prefix="kaliv-t022-final-archive-") as tmp:
    old_validation = core.VALIDATION
    old_gate = core.GATE_REPORT
    core.VALIDATION = Path(tmp)
    core.GATE_REPORT = Path(tmp) / "gate.json"
    core.GATE_REPORT.write_text('{"gate":{"passed":true}}\n', encoding="utf-8")
    archived = core._archive_previous_gate("a" * 40)
    check(
        "old green final gate is archived before rerun",
        archived is not None and archived.is_file() and not core.GATE_REPORT.exists(),
    )
    core.VALIDATION = old_validation
    core.GATE_REPORT = old_gate

originals = {
    "configure": core.configure_final_candidate,
    "ensure": core.collector.positive.ensure_candidate,
    "archive": core._archive_previous_gate,
    "collector": core.collector.main,
    "assess": core.assess_report_file,
    "atomic": core._atomic_json,
    "heading": core.collector.stage.heading,
    "ok": core.collector.stage.ok,
}
order: list[str] = []
writes: list[tuple[Path, dict]] = []
core.configure_final_candidate = lambda: order.append("configure")
core.collector.positive.ensure_candidate = lambda: order.append("ensure") or IDENTITY["git_sha"]
core._archive_previous_gate = lambda _sha: order.append("archive")
core.collector.main = lambda: order.append("collector") or 0
core.assess_report_file = lambda **_kwargs: order.append("assess") or copy.deepcopy(valid)
core._atomic_json = lambda path, value: writes.append((path, value))
core.collector.stage.heading = lambda _text: None
core.collector.stage.ok = lambda _text: None
try:
    green_exit = core.run_final_gate()
finally:
    core.configure_final_candidate = originals["configure"]
    core.collector.positive.ensure_candidate = originals["ensure"]
    core._archive_previous_gate = originals["archive"]
    core.collector.main = originals["collector"]
    core.assess_report_file = originals["assess"]
    core._atomic_json = originals["atomic"]
    core.collector.stage.heading = originals["heading"]
    core.collector.stage.ok = originals["ok"]
check(
    "green final orchestration is exact and atomic",
    green_exit == 0
    and order == ["configure", "ensure", "archive", "collector", "assess"]
    and len(writes) == 1
    and writes[0][0] == core.GATE_REPORT
    and writes[0][1]["gate"]["production_activation"] is False,
)

order.clear()
writes.clear()
core.configure_final_candidate = lambda: order.append("configure")
core.collector.positive.ensure_candidate = lambda: order.append("ensure") or IDENTITY["git_sha"]
core._archive_previous_gate = lambda _sha: order.append("archive")
core.collector.main = lambda: order.append("collector") or 1
core.assess_report_file = lambda **_kwargs: order.append("assess") or copy.deepcopy(valid)
core._atomic_json = lambda path, value: writes.append((path, value))
core.collector.stage.heading = lambda _text: None
core.collector.stage.ok = lambda _text: None
try:
    red_exit = core.run_final_gate()
finally:
    core.configure_final_candidate = originals["configure"]
    core.collector.positive.ensure_candidate = originals["ensure"]
    core._archive_previous_gate = originals["archive"]
    core.collector.main = originals["collector"]
    core.assess_report_file = originals["assess"]
    core._atomic_json = originals["atomic"]
    core.collector.stage.heading = originals["heading"]
    core.collector.stage.ok = originals["ok"]
check(
    "red collector result cannot leave a green final gate",
    red_exit == 1
    and len(writes) == 1
    and "collector_not_green" in writes[0][1]["blockers"]
    and writes[0][1]["gate"]["passed"] is False,
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 FINAL DORMANT GATE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
