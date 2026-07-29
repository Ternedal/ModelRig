#!/usr/bin/env python3
"""Final dormant gate for the physical T-022 Agent 3 write pilot.

The gate cannot create physical evidence. The normal entrypoint first runs the
existing combined physical/forensic operator on this exact final-gate branch,
then validates only its sanitized report. A pass proves report structure,
freshness, candidate binding and the 20-positive/7-negative inventory. It never
changes routes, tools, UI, release state or production activation.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VALIDATION = ROOT / "validation"
REPORT = VALIDATION / "agent3-write-pilot-latest.json"
GATE_REPORT = VALIDATION / "agent3-write-pilot-final-gate-latest.json"
BRANCH = "agent/t022-write-pilot-final-gate"
VERSION = "1.58.146"
GATE_SCHEMA = "kaliv-agent3-write-pilot-final-gate/v1"
DEFAULT_MAX_AGE_HOURS = 24.0
MAX_MAX_AGE_HOURS = 168.0
MAX_REPORT_BYTES = 2_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_PILOT_ID = re.compile(r"^[0-9a-f]{32}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
EXPECTED_EVIDENCE_KEYS = {
    "manifest_sha256",
    "negative_sha256",
    "negative_journal_final_sha256",
    "rig_validation_report_sha256",
    "agent_db_sha256",
    "approval_db_sha256",
    "audit_db_sha256",
    "notes_sha256",
}
EXPECTED_NEGATIVE_STATUSES = {
    "deny": [200],
    "timeout": [409],
    "changed_args": [409],
    "stale_revision": [409],
    "replay": [409],
    "concurrent_approval": [200, 409],
    "stop_retry_replan": [200, 202, 409],
}
TOP_LEVEL_KEYS = {
    "schema",
    "success",
    "generated_at",
    "candidate",
    "pilot_id",
    "operator",
    "evidence",
    "summary",
    "positive_runs",
    "negative_cases",
    "blockers",
    "production_activation",
}
SUMMARY_KEYS = {
    "positive_runs_expected",
    "positive_runs_proven",
    "negative_cases_expected",
    "negative_cases_present",
    "device_id",
    "window_started_at",
    "window_finished_at",
    "production_activation",
}
POSITIVE_KEYS = {
    "run_id",
    "step_id",
    "device_id",
    "plan_revision",
    "marker_sha256",
    "created_at",
    "updated_at",
    "approval_used_at",
    "ordinal",
}
NEGATIVE_KEYS = {
    "name",
    "run_ids",
    "request_statuses",
    "marker_sha256",
    "observed_at",
}

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent3_write_pilot_collect_one_click as collector  # noqa: E402
from agent3_write_pilot_common import (  # noqa: E402
    REPORT_SCHEMA,
    RUN_COUNT,
    _NEGATIVE_CASES,
    _atomic_json,
    _iso,
    _parse_time,
    _sha_bytes,
    candidate_identity,
)


class FinalGateError(RuntimeError):
    pass


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str, blockers: list[str]) -> None:
    actual = set(value)
    if actual != expected:
        blockers.append(
            f"{label}_keys_mismatch:missing={sorted(expected - actual)},extra={sorted(actual - expected)}"
        )


def _load_report(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise FinalGateError(f"report_not_regular_file:{path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_REPORT_BYTES:
        raise FinalGateError(f"report_size_invalid:{size}")
    raw = path.read_bytes()
    try:
        import json

        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FinalGateError("report_not_utf8_json") from exc
    if not isinstance(value, dict):
        raise FinalGateError("report_not_object")
    return value, raw


def _valid_identity(report_candidate: Mapping[str, Any], current: Mapping[str, Any], blockers: list[str]) -> bool:
    bound = True
    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        if report_candidate.get(field) != current.get(field):
            blockers.append(f"candidate_{field}_mismatch")
            bound = False
    if report_candidate.get("version") != VERSION:
        blockers.append("candidate_version_not_final_gate_version")
        bound = False
    if not _GIT_SHA.fullmatch(str(report_candidate.get("git_sha") or "")):
        blockers.append("candidate_git_sha_invalid")
        bound = False
    if not _SHA256.fullmatch(str(report_candidate.get("code_sha256") or "")):
        blockers.append("candidate_code_sha256_invalid")
        bound = False
    if report_candidate.get("identity_source") != "git":
        blockers.append("candidate_identity_source_not_git")
        bound = False
    if report_candidate.get("working_tree_clean") is not True:
        blockers.append("report_candidate_working_tree_not_clean")
        bound = False
    if report_candidate.get("version_stamps_consistent") is not True:
        blockers.append("report_candidate_version_stamps_inconsistent")
        bound = False
    if current.get("working_tree_clean") is not True:
        blockers.append("current_candidate_working_tree_not_clean")
        bound = False
    if current.get("version_stamps_consistent") is not True:
        blockers.append("current_candidate_version_stamps_inconsistent")
        bound = False
    branch = report_candidate.get("branch")
    current_branch = current.get("branch")
    if branch is not None and branch != BRANCH:
        blockers.append("report_candidate_branch_mismatch")
        bound = False
    if current_branch is not None and current_branch != BRANCH:
        blockers.append("current_candidate_branch_mismatch")
        bound = False
    return bound


def _validate_positive_runs(
    runs: Any,
    summary_device: Any,
    blockers: list[str],
) -> tuple[int, set[str]]:
    if not isinstance(runs, list):
        blockers.append("positive_runs_not_list")
        return 0, set()
    if len(runs) != RUN_COUNT:
        blockers.append(f"positive_runs_count_invalid:{len(runs)}")
    ordinals: set[int] = set()
    run_ids: set[str] = set()
    step_ids: set[str] = set()
    marker_hashes: set[str] = set()
    devices: set[str] = set()
    proven = 0
    for index, item in enumerate(runs, start=1):
        if not isinstance(item, dict):
            blockers.append(f"positive_{index}_not_object")
            continue
        _exact_keys(item, POSITIVE_KEYS, f"positive_{index}", blockers)
        ordinal = item.get("ordinal")
        run_id = item.get("run_id")
        step_id = item.get("step_id")
        device_id = item.get("device_id")
        revision = item.get("plan_revision")
        marker = item.get("marker_sha256")
        created = _number(item.get("created_at"))
        updated = _number(item.get("updated_at"))
        used = _number(item.get("approval_used_at"))
        valid = True
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not (1 <= ordinal <= RUN_COUNT):
            blockers.append(f"positive_{index}_ordinal_invalid")
            valid = False
        elif ordinal in ordinals:
            blockers.append(f"positive_ordinal_duplicate:{ordinal}")
            valid = False
        else:
            ordinals.add(ordinal)
        for label, value, target in (
            ("run_id", run_id, run_ids),
            ("step_id", step_id, step_ids),
        ):
            if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
                blockers.append(f"positive_{index}_{label}_invalid")
                valid = False
            elif value in target:
                blockers.append(f"positive_{label}_duplicate")
                valid = False
            else:
                target.add(value)
        if not isinstance(device_id, str) or not device_id.strip():
            blockers.append(f"positive_{index}_device_missing")
            valid = False
        else:
            devices.add(device_id)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            blockers.append(f"positive_{index}_revision_invalid")
            valid = False
        if not isinstance(marker, str) or not _SHA256.fullmatch(marker):
            blockers.append(f"positive_{index}_marker_sha256_invalid")
            valid = False
        elif marker in marker_hashes:
            blockers.append("positive_marker_sha256_duplicate")
            valid = False
        else:
            marker_hashes.add(marker)
        if created is None or updated is None or used is None:
            blockers.append(f"positive_{index}_timestamps_invalid")
            valid = False
        elif not (created <= used <= updated + 300):
            blockers.append(f"positive_{index}_timestamp_order_invalid")
            valid = False
        if valid:
            proven += 1
    if ordinals != set(range(1, RUN_COUNT + 1)):
        blockers.append("positive_ordinals_not_exact_1_to_20")
    if len(devices) != 1:
        blockers.append("positive_device_inventory_not_single")
    elif summary_device not in devices:
        blockers.append("summary_device_disagrees_with_positive_runs")
    return proven, run_ids


def _validate_negative_cases(cases: Any, blockers: list[str]) -> int:
    if not isinstance(cases, list):
        blockers.append("negative_cases_not_list")
        return 0
    if len(cases) != len(_NEGATIVE_CASES):
        blockers.append(f"negative_cases_count_invalid:{len(cases)}")
    names: set[str] = set()
    marker_hashes: set[str] = set()
    proven = 0
    for index, item in enumerate(cases, start=1):
        if not isinstance(item, dict):
            blockers.append(f"negative_{index}_not_object")
            continue
        _exact_keys(item, NEGATIVE_KEYS, f"negative_{index}", blockers)
        name = item.get("name")
        marker = item.get("marker_sha256")
        statuses = item.get("request_statuses")
        run_ids = item.get("run_ids")
        observed = _parse_time(item.get("observed_at"))
        valid = True
        if not isinstance(name, str) or name not in EXPECTED_NEGATIVE_STATUSES:
            blockers.append(f"negative_{index}_name_invalid")
            valid = False
        elif name in names:
            blockers.append(f"negative_name_duplicate:{name}")
            valid = False
        else:
            names.add(name)
        if not isinstance(marker, str) or not _SHA256.fullmatch(marker):
            blockers.append(f"negative_{index}_marker_sha256_invalid")
            valid = False
        elif marker in marker_hashes:
            blockers.append("negative_marker_sha256_duplicate")
            valid = False
        else:
            marker_hashes.add(marker)
        if not isinstance(statuses, list) or any(
            isinstance(status, bool) or not isinstance(status, int) for status in statuses
        ):
            blockers.append(f"negative_{index}_statuses_invalid")
            valid = False
        elif isinstance(name, str):
            expected = EXPECTED_NEGATIVE_STATUSES.get(name)
            if name == "concurrent_approval":
                if sorted(statuses) != expected:
                    blockers.append("negative_concurrent_approval_statuses_mismatch")
                    valid = False
            elif statuses != expected:
                blockers.append(f"negative_{name}_statuses_mismatch")
                valid = False
        if not isinstance(run_ids, list) or not run_ids:
            blockers.append(f"negative_{index}_run_ids_missing")
            valid = False
        elif any(not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value) for value in run_ids):
            blockers.append(f"negative_{index}_run_id_invalid")
            valid = False
        elif len(run_ids) != len(set(run_ids)):
            blockers.append(f"negative_{index}_run_ids_duplicate")
            valid = False
        if observed is None:
            blockers.append(f"negative_{index}_observed_at_invalid")
            valid = False
        if valid:
            proven += 1
    if names != set(_NEGATIVE_CASES):
        blockers.append("negative_case_names_not_exact")
    return proven


def assess_report(
    report: Any,
    *,
    current_identity: Mapping[str, Any],
    report_sha256: str,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    blockers: list[str] = []
    if isinstance(max_age_hours, bool) or not isinstance(max_age_hours, (int, float)):
        raise FinalGateError("max_age_hours_invalid")
    max_age = float(max_age_hours)
    if not (0 < max_age <= MAX_MAX_AGE_HOURS):
        raise FinalGateError("max_age_hours_out_of_range")
    if not isinstance(report, dict):
        report = {}
        blockers.append("report_not_object")
    _exact_keys(report, TOP_LEVEL_KEYS, "report", blockers)
    if report.get("schema") != REPORT_SCHEMA:
        blockers.append("report_schema_mismatch")
    if report.get("success") is not True:
        blockers.append("report_not_successful")
    if report.get("production_activation") is not False:
        blockers.append("report_production_activation_not_false")
    if not isinstance(report_sha256, str) or not _SHA256.fullmatch(report_sha256):
        blockers.append("report_sha256_invalid")

    generated = _parse_time(report.get("generated_at"))
    report_age_seconds: float | None = None
    fresh = False
    if generated is None:
        blockers.append("report_generated_at_invalid")
    else:
        report_age_seconds = current.timestamp() - generated.timestamp()
        if report_age_seconds < -300:
            blockers.append("report_from_future")
        elif report_age_seconds > max_age * 3600:
            blockers.append("report_stale")
        else:
            fresh = True

    pilot_id = report.get("pilot_id")
    if not isinstance(pilot_id, str) or not _PILOT_ID.fullmatch(pilot_id):
        blockers.append("pilot_id_invalid")
    operator = report.get("operator")
    if not isinstance(operator, str) or not operator.strip():
        blockers.append("operator_missing")

    evidence = _object(report.get("evidence"))
    _exact_keys(evidence, EXPECTED_EVIDENCE_KEYS, "evidence", blockers)
    for key in EXPECTED_EVIDENCE_KEYS:
        if not _SHA256.fullmatch(str(evidence.get(key) or "")):
            blockers.append(f"evidence_{key}_invalid")

    candidate = _object(report.get("candidate"))
    candidate_bound = _valid_identity(candidate, current_identity, blockers)

    summary = _object(report.get("summary"))
    _exact_keys(summary, SUMMARY_KEYS, "summary", blockers)
    if summary.get("production_activation") is not False:
        blockers.append("summary_production_activation_not_false")
    if summary.get("positive_runs_expected") != RUN_COUNT:
        blockers.append("summary_positive_expected_mismatch")
    if summary.get("positive_runs_proven") != RUN_COUNT:
        blockers.append("summary_positive_proven_mismatch")
    if summary.get("negative_cases_expected") != len(_NEGATIVE_CASES):
        blockers.append("summary_negative_expected_mismatch")
    if summary.get("negative_cases_present") != len(_NEGATIVE_CASES):
        blockers.append("summary_negative_present_mismatch")
    device_id = summary.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        blockers.append("summary_device_id_missing")

    window_start = _parse_time(summary.get("window_started_at"))
    window_finish = _parse_time(summary.get("window_finished_at"))
    window_hours: float | None = None
    if window_start is None or window_finish is None:
        blockers.append("summary_window_invalid")
    else:
        window_hours = (window_finish - window_start).total_seconds() / 3600.0
        if window_hours < 0:
            blockers.append("summary_window_reversed")
        elif window_hours > 12.0:
            blockers.append("summary_window_exceeds_12_hours")
        if generated is not None and generated.timestamp() + 300 < window_finish.timestamp():
            blockers.append("report_generated_before_evidence_finished")

    positive_proven, _positive_ids = _validate_positive_runs(
        report.get("positive_runs"),
        device_id,
        blockers,
    )
    negative_proven = _validate_negative_cases(report.get("negative_cases"), blockers)

    report_blockers = _strings(report.get("blockers"))
    if report.get("blockers") != report_blockers:
        blockers.append("report_blockers_not_string_list")
    if report_blockers:
        blockers.append("report_contains_blockers")

    inventory_complete = (
        positive_proven == RUN_COUNT
        and negative_proven == len(_NEGATIVE_CASES)
        and summary.get("positive_runs_proven") == RUN_COUNT
        and summary.get("negative_cases_present") == len(_NEGATIVE_CASES)
    )
    passed = not blockers
    return {
        "schema": GATE_SCHEMA,
        "generated_at": _iso(current),
        "report": {
            "path": str(REPORT.relative_to(ROOT)),
            "sha256": report_sha256,
            "schema": report.get("schema"),
            "generated_at": report.get("generated_at"),
            "pilot_id": pilot_id,
        },
        "candidate": {
            key: current_identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "summary": {
            "positive_runs_proven": positive_proven,
            "negative_cases_proven": negative_proven,
            "report_age_seconds": report_age_seconds,
            "window_hours": window_hours,
        },
        "blockers": blockers,
        "gate": {
            "passed": passed,
            "report_success": report.get("success") is True,
            "candidate_bound": candidate_bound,
            "fresh": fresh,
            "inventory_complete": inventory_complete,
            "physical_evidence_complete": passed,
            "production_activation": False,
        },
    }


def assess_report_file(
    report_path: Path = REPORT,
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    identity = candidate_identity(ROOT)
    report, raw = _load_report(report_path)
    return assess_report(
        report,
        current_identity=identity,
        report_sha256=_sha_bytes(raw),
        now=now,
        max_age_hours=max_age_hours,
    )


def configure_final_candidate() -> None:
    collector.BRANCH = BRANCH
    collector.VERSION = VERSION
    collector.configure_candidate()


def _archive_previous_gate(candidate_sha: str) -> Path | None:
    if not GATE_REPORT.exists():
        return None
    if GATE_REPORT.is_symlink() or not GATE_REPORT.is_file():
        raise FinalGateError("existing_gate_report_not_regular")
    base = VALIDATION / "archive" / (
        time.strftime("agent3-write-pilot-final-gate-%Y%m%d-%H%M%S-") + candidate_sha[:12]
    )
    archive = base
    counter = 1
    while archive.exists():
        archive = Path(str(base) + f"-{counter}")
        counter += 1
    archive.mkdir(parents=True, exist_ok=False)
    destination = archive / GATE_REPORT.name
    GATE_REPORT.replace(destination)
    collector.stage.note(f"Tidligere T-022 final-gate er bevaret i {archive}")
    return destination


def run_final_gate(*, max_age_hours: float = DEFAULT_MAX_AGE_HOURS) -> int:
    os.chdir(ROOT)
    configure_final_candidate()
    candidate_sha = collector.positive.ensure_candidate()
    _archive_previous_gate(candidate_sha)
    collector_result = collector.main()
    try:
        gate = assess_report_file(max_age_hours=max_age_hours)
    except Exception as exc:
        identity = candidate_identity(ROOT)
        gate = {
            "schema": GATE_SCHEMA,
            "generated_at": _iso(datetime.now(timezone.utc)),
            "report": {
                "path": str(REPORT.relative_to(ROOT)),
                "sha256": None,
                "schema": None,
                "generated_at": None,
                "pilot_id": None,
            },
            "candidate": {
                key: identity.get(key)
                for key in ("version", "git_sha", "code_sha256", "identity_source")
            },
            "summary": {
                "positive_runs_proven": 0,
                "negative_cases_proven": 0,
                "report_age_seconds": None,
                "window_hours": None,
            },
            "blockers": [f"final_gate_assessment_error:{type(exc).__name__}:{str(exc)[:500]}"],
            "gate": {
                "passed": False,
                "report_success": False,
                "candidate_bound": False,
                "fresh": False,
                "inventory_complete": False,
                "physical_evidence_complete": False,
                "production_activation": False,
            },
        }
    if collector_result != 0 and "collector_not_green" not in gate["blockers"]:
        gate["blockers"].append("collector_not_green")
        gate["gate"]["passed"] = False
        gate["gate"]["physical_evidence_complete"] = False
    gate["gate"]["production_activation"] = False
    _atomic_json(GATE_REPORT, gate)
    if gate["gate"]["passed"] is True and collector_result == 0:
        collector.stage.heading("T-022 FINAL GATE: GREEN")
        collector.stage.ok(f"Final gate: {GATE_REPORT}")
        collector.stage.ok("Rapporten er frisk, exact-head-bundet og har 20+7 fysisk evidens.")
        collector.stage.ok("Ingen merge, release eller produktionsaktivering er udført.")
        return 0
    collector.stage.heading(f"T-022 FINAL GATE: RED ({len(gate['blockers'])} blockers)")
    for blocker in gate["blockers"]:
        print(f"  - {blocker}")
    print(f"  Rød final-gate er gemt i {GATE_REPORT}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assess-only",
        action="store_true",
        help="validate an existing local report without running the physical pipeline",
    )
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--gate-report", default=str(GATE_REPORT))
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    global REPORT, GATE_REPORT
    REPORT = Path(args.report)
    GATE_REPORT = Path(args.gate_report)
    if args.assess_only:
        gate = assess_report_file(REPORT, max_age_hours=args.max_age_hours)
        _atomic_json(GATE_REPORT, gate)
        return 0 if gate["gate"]["passed"] is True else 1
    return run_final_gate(max_age_hours=args.max_age_hours)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: ingen gammel grøn final-gate er efterladt.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1600]}",
            file=sys.stderr,
        )
        print("  Fysisk evidens kan ikke fremstilles af final-gaten.", file=sys.stderr)
        raise SystemExit(1)
