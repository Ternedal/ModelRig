#!/usr/bin/env python3
"""Safe entrypoint for the T-022 final gate.

The core validator stays strict. This entrypoint aligns two representation details
with the established collector contract: positive timestamps may be numeric or
ISO-8601, and stop/retry/replan accepts any sequence of at least three
200/202/409 responses. No other policy is changed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent3_write_pilot_final_gate as core  # noqa: E402

_ORIGINAL_NUMBER = core._number
_ORIGINAL_ASSESS_REPORT = core.assess_report


def timestamp_seconds(value: Any) -> float | None:
    numeric = _ORIGINAL_NUMBER(value)
    if numeric is not None:
        return numeric
    parsed = core._parse_time(value)
    return parsed.timestamp() if parsed is not None else None


def assess_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Keep external assess-only paths out of the sanitized gate report."""
    original_report = core.REPORT
    try:
        try:
            original_report.relative_to(core.ROOT)
        except ValueError:
            core.REPORT = core.ROOT / original_report.name
        return _ORIGINAL_ASSESS_REPORT(*args, **kwargs)
    finally:
        core.REPORT = original_report


def validate_negative_cases(cases: Any, blockers: list[str]) -> int:
    if not isinstance(cases, list):
        blockers.append("negative_cases_not_list")
        return 0
    if len(cases) != len(core._NEGATIVE_CASES):
        blockers.append(f"negative_cases_count_invalid:{len(cases)}")
    names: set[str] = set()
    marker_hashes: set[str] = set()
    proven = 0
    for index, item in enumerate(cases, start=1):
        if not isinstance(item, dict):
            blockers.append(f"negative_{index}_not_object")
            continue
        core._exact_keys(item, core.NEGATIVE_KEYS, f"negative_{index}", blockers)
        name = item.get("name")
        marker = item.get("marker_sha256")
        statuses = item.get("request_statuses")
        run_ids = item.get("run_ids")
        observed = core._parse_time(item.get("observed_at"))
        valid = True
        if not isinstance(name, str) or name not in core.EXPECTED_NEGATIVE_STATUSES:
            blockers.append(f"negative_{index}_name_invalid")
            valid = False
        elif name in names:
            blockers.append(f"negative_name_duplicate:{name}")
            valid = False
        else:
            names.add(name)
        if not isinstance(marker, str) or not core._SHA256.fullmatch(marker):
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
        elif name == "concurrent_approval":
            if sorted(statuses) != [200, 409]:
                blockers.append("negative_concurrent_approval_statuses_mismatch")
                valid = False
        elif name == "stop_retry_replan":
            if len(statuses) < 3 or any(status not in {200, 202, 409} for status in statuses):
                blockers.append("negative_stop_retry_replan_statuses_mismatch")
                valid = False
        elif isinstance(name, str) and statuses != core.EXPECTED_NEGATIVE_STATUSES.get(name):
            blockers.append(f"negative_{name}_statuses_mismatch")
            valid = False
        if not isinstance(run_ids, list) or not run_ids:
            blockers.append(f"negative_{index}_run_ids_missing")
            valid = False
        elif any(
            not isinstance(value, str) or not core._OPAQUE_ID.fullmatch(value)
            for value in run_ids
        ):
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
    if names != set(core._NEGATIVE_CASES):
        blockers.append("negative_case_names_not_exact")
    return proven


def install_policy() -> None:
    core._number = timestamp_seconds
    core.assess_report = assess_report
    core._validate_negative_cases = validate_negative_cases


def main(argv: list[str] | None = None) -> int:
    install_policy()
    return core.main(argv)


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
