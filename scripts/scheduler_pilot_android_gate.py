#!/usr/bin/env python3
"""Bind the three physical Android observations into a scheduler-pilot report."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

FIELDS = (
    ("android_schedule_list_confirmed", "Android-listen viste begge pilotplaner"),
    ("android_in_flight_confirmed", "Android viste mindst én in-flight/running plan"),
    ("android_terminal_confirmed", "Android viste cancelled/terminal udfaldet"),
)
PREFIX = "Android-observation mangler: "


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"kan ikke læse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} er ikke et JSON-objekt")
    return value


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def apply_gate(report: dict[str, Any], manual: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema") != "kaliv-scheduler-pilot/v4":
        raise RuntimeError("scheduler-pilotrapporten har forkert schema")
    pilot = report.get("pilot")
    if not isinstance(pilot, dict):
        raise RuntimeError("scheduler-pilotrapporten mangler pilot-verdict")
    existing = pilot.get("problems")
    problems = [
        str(problem)
        for problem in (existing if isinstance(existing, list) else [])
        if not str(problem).startswith(PREFIX)
    ]
    physical: dict[str, bool] = {}
    for field, description in FIELDS:
        confirmed = manual.get(field) is True
        physical[field] = confirmed
        if not confirmed:
            problems.append(PREFIX + description)
    report_manual = report.get("manual")
    if not isinstance(report_manual, dict):
        report_manual = {}
        report["manual"] = report_manual
    report_manual.update(physical)
    pilot["android_observations"] = physical
    pilot["problems"] = problems
    pilot["passed"] = not problems
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manual-observations", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = apply_gate(load_object(args.report), load_object(args.manual_observations))
        write_atomic(args.report, report)
    except RuntimeError as exc:
        print(f"  FAIL  {exc}")
        return 1
    if report["pilot"]["passed"]:
        print("  OK    Android-observationerne er bundet til scheduler-pilotens verdict")
        return 0
    print("  FAIL  scheduler-piloten mangler Android-observationer:")
    for problem in report["pilot"]["problems"]:
        print(f"         - {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
