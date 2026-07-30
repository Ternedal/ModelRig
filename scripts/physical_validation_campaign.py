#!/usr/bin/env python3
"""Aggregate every physical ModelRig proof, including T-021 task UI evidence.

The current-main campaign implementation is preserved byte-for-byte in
``physical_validation_campaign_core.py``. This wrapper re-exports that API and
adds one independently validated evidence domain without rewriting the existing
seven validators.
"""
from __future__ import annotations

import argparse
import importlib.util
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_sibling(module_name: str, filename: str) -> ModuleType:
    """Load a sibling module without relying on the caller's ``sys.path``."""
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load campaign sibling: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_core = _load_sibling("physical_validation_campaign_core", "physical_validation_campaign_core.py")
_task_ui = _load_sibling("physical_validation_task_ui", "physical_validation_task_ui.py")

# Preserve the complete historical module API, including private helpers used by
# the repository's contract tests. Explicit wrapper functions below intentionally
# override only campaign orchestration and CLI parsing.
for _name in dir(_core):
    if _name not in globals():
        globals()[_name] = getattr(_core, _name)

SCHEMA = _core.SCHEMA
DEFAULT_REPORT = _core.DEFAULT_REPORT
TASK_UI_SCHEMA = _task_ui.TASK_UI_SCHEMA
validate_task_ui = _task_ui.validate_task_ui

DEFAULT_PATHS = dict(_core.DEFAULT_PATHS)
DEFAULT_PATHS["task_ui"] = Path("validation/agent3-task-ui-validation-latest.json")

COMMANDS = dict(_core.COMMANDS)
COMMANDS["task_ui"] = (
    "python scripts\\agent3_task_ui_validation.py "
    "--base-url http://127.0.0.1:8080 "
    "--manual-observations validation\\agent3-task-ui-observations.json "
    "--report validation\\agent3-task-ui-validation-latest.json"
)

# Keep the public legacy table unchanged so the existing regression suite proves
# exactly the historical seven-domain contract. Extended orchestration swaps in
# the additive table only for the duration of a T-021-aware call.
LEGACY_VALIDATORS = dict(_core.VALIDATORS)
VALIDATORS = LEGACY_VALIDATORS
EXTENDED_VALIDATORS = dict(LEGACY_VALIDATORS)
EXTENDED_VALIDATORS["task_ui"] = (validate_task_ui, (("generated_at",),))

candidate_identity = _core.candidate_identity
_load_agent3_assessor = _core._load_agent3_assessor
validate_evidence = _core.validate_evidence
_write_json_atomic = _core._write_json_atomic
_safe_error = _core._safe_error


def _legacy_campaign_report(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    # Historical tests monkey-patch these names on this wrapper. Mirror the
    # current bindings into the untouched core before delegating.
    _core.candidate_identity = candidate_identity
    _core._load_agent3_assessor = _load_agent3_assessor
    _core.VALIDATORS = LEGACY_VALIDATORS
    return _core.campaign_report(args)


def campaign_report(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if not hasattr(args, "task_ui_report"):
        return _legacy_campaign_report(args)

    root = Path(__file__).resolve().parents[1]
    now = datetime.now(timezone.utc)
    candidate = candidate_identity(root)
    assessor = _load_agent3_assessor(root)
    thresholds: dict[str, Any] = {
        "min_model_exact": args.min_model_exact,
        "agent3_assessor": assessor,
        "root": root,
    }
    paths = {
        "preflight": args.preflight_report,
        "agent3": args.agent3_report,
        "model_eval": args.model_eval_report,
        "voice": args.voice_report,
        "rag": args.rag_report,
        "lifecycle": args.lifecycle_report,
        "scheduler_pilot": args.scheduler_pilot_report,
        "task_ui": args.task_ui_report,
    }
    _core.VALIDATORS = EXTENDED_VALIDATORS
    try:
        evidence = {
            name: validate_evidence(
                root,
                name,
                path,
                candidate=candidate,
                thresholds=thresholds,
                now=now,
                max_age_hours=args.max_age_hours,
            )
            for name, path in paths.items()
        }
    finally:
        _core.VALIDATORS = LEGACY_VALIDATORS

    candidate_errors: list[str] = []
    if candidate["working_tree_clean"] is False:
        candidate_errors.append(
            f"working tree has {candidate['dirty_entries']} uncommitted change(s)"
        )
    if not candidate["version_stamps_consistent"]:
        candidate_errors.append("version stamps are inconsistent")

    failed = [name for name, item in evidence.items() if item["status"] == "fail"]
    missing = [name for name, item in evidence.items() if item["status"] == "missing"]
    passed = [name for name, item in evidence.items() if item["status"] == "pass"]
    all_evidence_passed = len(passed) == len(evidence)
    if args.mode == "prepare":
        gate_passed = not candidate_errors and not failed
        exit_code = 0 if gate_passed else 1
    else:
        gate_passed = not candidate_errors and all_evidence_passed
        exit_code = 0 if gate_passed else 1

    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "mode": args.mode,
        "candidate": candidate,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "configuration": {
            "max_age_hours": args.max_age_hours,
            "min_model_exact": args.min_model_exact,
        },
        "commands": COMMANDS,
        "evidence": evidence,
        "summary": {
            "total": len(evidence),
            "passed": passed,
            "failed": failed,
            "missing": missing,
            "candidate_errors": candidate_errors,
        },
        "gate": {
            "passed": gate_passed,
            "physical_campaign_complete": all_evidence_passed,
            "production_activation": False,
        },
    }
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "verify"), default="verify")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--preflight-report", type=Path, default=DEFAULT_PATHS["preflight"])
    parser.add_argument("--agent3-report", type=Path, default=DEFAULT_PATHS["agent3"])
    parser.add_argument("--model-eval-report", type=Path, default=DEFAULT_PATHS["model_eval"])
    parser.add_argument("--voice-report", type=Path, default=DEFAULT_PATHS["voice"])
    parser.add_argument("--rag-report", type=Path, default=DEFAULT_PATHS["rag"])
    parser.add_argument("--lifecycle-report", type=Path, default=DEFAULT_PATHS["lifecycle"])
    parser.add_argument(
        "--scheduler-pilot-report",
        type=Path,
        default=DEFAULT_PATHS["scheduler_pilot"],
    )
    parser.add_argument("--task-ui-report", type=Path, default=DEFAULT_PATHS["task_ui"])
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    parser.add_argument("--min-model-exact", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.max_age_hours > 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    if not 0 <= args.min_model_exact <= 1:
        parser.error("--min-model-exact must be between 0 and 1")

    try:
        report, exit_code = campaign_report(args)
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": args.mode,
            "error": _safe_error(exc),
            "summary": {
                "total": 0,
                "passed": [],
                "failed": ["campaign"],
                "missing": [],
                "candidate_errors": [],
            },
            "gate": {
                "passed": False,
                "physical_campaign_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2
    _write_json_atomic(args.report, report)
    print(f"report: {args.report}")
    print(
        "gate: "
        + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED")
        + f" (mode={args.mode})"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
