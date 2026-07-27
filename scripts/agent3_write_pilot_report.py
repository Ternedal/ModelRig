#!/usr/bin/env python3
"""Prepare and collect candidate-bound evidence for the physical T-022 write pilot.

This tool does not execute Agent 3 and cannot make a pilot physical. It prepares
20 unpredictable append markers before the operator starts, binds the resulting
run ids without changing the markers, and later cross-checks the real notes file,
Agent 3 run/event ledger, approval-use database and ToolGate audit database.

A green report is evidence about one exact frozen candidate. It never activates
routing, tools or production behavior.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agent3_write_pilot_common import (  # noqa: E402
    MANIFEST_SCHEMA, NEGATIVE_SCHEMA, REPORT_SCHEMA, RUN_COUNT,
    PILOT_WINDOW_MAX_HOURS, REPORT_MAX_AGE_HOURS, _NEGATIVE_CASES,
    _OPAQUE_ID, _SHA256, PilotEvidenceError, _atomic_json, _iso, _load_json,
    _parse_time, _sha_bytes, _sha_text, _utc_now, assess_rig_validation,
    bind_run, candidate_identity, prepare_manifest, validate_manifest,
    validate_negative_evidence,
)
from agent3_write_pilot_forensics import (  # noqa: E402
    _action_sha, _marker_from_run, _validate_success_run, load_approval_rows,
    load_audit_rows, load_run_records, snapshot_sqlite,
)

def judge(
    *,
    manifest: dict[str, Any],
    negative: dict[str, Any],
    run_records: list[dict[str, Any]],
    approval_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    notes_text: str,
    identity: dict[str, Any],
    rig_validation_assessment: dict[str, Any],
    rig_validation_sha256: str,
    now: datetime | None = None,
) -> tuple[list[str], dict[str, Any]]:
    errors = validate_manifest(manifest, require_bound=True)
    errors.extend(validate_negative_evidence(negative, manifest))
    current = now or _utc_now()

    target = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        if target.get(field) != identity.get(field):
            errors.append(f"candidate {field} changed after manifest preparation")
    if identity.get("version_stamps_consistent") is not True:
        errors.append("candidate version stamps are inconsistent at collection")
    if identity.get("identity_source") == "git" and identity.get("working_tree_clean") is not True:
        errors.append("candidate working tree is not clean at collection")
    if target.get("rig_validation_report_sha256") != rig_validation_sha256:
        errors.append("rig validation report changed after manifest preparation")
    if rig_validation_assessment.get("eligible_for_write_pilot") is not True:
        errors.append("rig validation is not eligible for the write pilot at collection")

    by_run = {record.get("id"): record for record in run_records if isinstance(record.get("id"), str)}
    evidence: list[dict[str, Any]] = []
    positive_ids = {item.get("run_id") for item in manifest.get("runs", []) if isinstance(item, dict)}
    positive_markers = {item.get("marker") for item in manifest.get("runs", []) if isinstance(item, dict)}
    prefix = str(manifest.get("marker_prefix") or "")

    inventory = {
        record.get("id")
        for record in run_records
        if isinstance(_marker_from_run(record), str) and _marker_from_run(record).startswith(prefix)
    }
    if inventory != positive_ids:
        errors.append(
            "pilot run inventory mismatch: "
            f"missing={sorted(positive_ids - inventory)}, extra={sorted(inventory - positive_ids)}"
        )

    for item in manifest.get("runs", []):
        if not isinstance(item, dict):
            continue
        ordinal = item.get("ordinal")
        run_id = item.get("run_id")
        marker = item.get("marker")
        record = by_run.get(run_id)
        if record is None:
            errors.append(f"positive run {ordinal}: run id not found in Agent 3 DB")
            continue
        result = _validate_success_run(
            record=record,
            marker=marker,
            approval_rows=approval_rows,
            audit_rows=audit_rows,
            errors=errors,
            label=f"positive run {ordinal}",
        )
        if result:
            result["ordinal"] = ordinal
            evidence.append(result)
        count = notes_text.splitlines().count(marker)
        if count != 1:
            errors.append(f"positive run {ordinal}: marker occurs {count} times in notes.md")

    note_prefixed = [line for line in notes_text.splitlines() if line.startswith(prefix)]
    if set(note_prefixed) != positive_markers or len(note_prefixed) != RUN_COUNT:
        errors.append("notes.md contains missing, duplicated or unlisted positive pilot markers")

    positive_approval_rows = [row for row in approval_rows if row.get("run_id") in positive_ids]
    if len(positive_approval_rows) != RUN_COUNT:
        errors.append("approval-use inventory does not contain exactly 20 positive rows")
    for field in ("nonce_sha256", "action_sha256", "token_sha256"):
        values = [row.get(field) for row in positive_approval_rows]
        if len(values) != len(set(values)):
            errors.append(f"positive approvals contain duplicate {field}")
    devices = {row.get("device_id") for row in positive_approval_rows}
    if len(devices) != 1 or None in devices or "" in devices:
        errors.append("the 20 positive approvals are not attributed to one device")

    # Negative ledger checks that can be proven directly rather than trusted from
    # the HTTP observation file. Every referenced run must exist; otherwise a
    # green HTTP transcript could name fictional work.
    cases = {
        case.get("name"): case
        for case in negative.get("cases", [])
        if isinstance(case, dict) and isinstance(case.get("name"), str)
    }
    for name, case in cases.items():
        for run_id in case.get("run_ids") or []:
            if run_id not in by_run:
                errors.append(f"negative case {name}: referenced run {run_id} does not exist")
    for name, required_event in (("deny", "confirmation_denied"), ("timeout", "confirmation_expired")):
        case = cases.get(name)
        if not case:
            continue
        run_id = (case.get("run_ids") or [None])[0]
        record = by_run.get(run_id)
        if record is None:
            errors.append(f"negative case {name}: run not found")
            continue
        kinds = [event.get("kind") for event in record.get("events", [])]
        if kinds.count(required_event) != 1:
            errors.append(f"negative case {name}: {required_event} is not proven in ledger")
        if any(kind in kinds for kind in ("approval_consumed", "step_started", "step_succeeded")):
            errors.append(f"negative case {name}: side-effect event is present")
        if any(row.get("run_id") == run_id for row in approval_rows):
            errors.append(f"negative case {name}: approval use was consumed")
        marker = case.get("marker")
        if isinstance(marker, str) and notes_text.splitlines().count(marker) != 0:
            errors.append(f"negative case {name}: marker reached notes.md")

    concurrent = cases.get("concurrent_approval")
    if concurrent:
        marker = concurrent.get("marker")
        run_ids = concurrent.get("run_ids") or []
        if isinstance(marker, str):
            if notes_text.splitlines().count(marker) != 1:
                errors.append("concurrent approval marker must occur exactly once in notes.md")
            matching = [record for record in run_records if record.get("id") in run_ids and _marker_from_run(record) == marker]
            if len(matching) != 1:
                errors.append("concurrent approval must identify one exact successful run")
            else:
                _validate_success_run(
                    record=matching[0],
                    marker=marker,
                    approval_rows=approval_rows,
                    audit_rows=audit_rows,
                    errors=errors,
                    label="negative case concurrent_approval",
                )

    times: list[float] = []
    created = _parse_time(manifest.get("created_at"))
    if created:
        times.append(created.timestamp())
    for item in evidence:
        for field in ("created_at", "updated_at", "approval_used_at"):
            value = item.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                times.append(float(value))
    for case in negative.get("cases", []):
        if isinstance(case, dict):
            parsed = _parse_time(case.get("observed_at"))
            if parsed:
                times.append(parsed.timestamp())
    if times:
        window = max(times) - min(times)
        if window > PILOT_WINDOW_MAX_HOURS * 3600:
            errors.append("pilot evidence spans more than 12 hours")
        age = current.timestamp() - max(times)
        if age < -900:
            errors.append("pilot evidence is from the future")
        elif age > REPORT_MAX_AGE_HOURS * 3600:
            errors.append("pilot evidence is older than 24 hours")
    else:
        errors.append("pilot evidence has no timestamps")

    summary = {
        "positive_runs_expected": RUN_COUNT,
        "positive_runs_proven": len(evidence),
        "negative_cases_expected": len(_NEGATIVE_CASES),
        "negative_cases_present": len(cases),
        "device_id": next(iter(devices)) if len(devices) == 1 else None,
        "window_started_at": _iso(datetime.fromtimestamp(min(times), timezone.utc)) if times else None,
        "window_finished_at": _iso(datetime.fromtimestamp(max(times), timezone.utc)) if times else None,
        "production_activation": False,
    }
    details = {
        "summary": summary,
        "positive_runs": sorted(evidence, key=lambda item: int(item.get("ordinal") or 0)),
        "negative_cases": [
            {
                "name": name,
                "run_ids": case.get("run_ids"),
                "request_statuses": case.get("request_statuses"),
                "marker_sha256": _sha_text(str(case.get("marker") or "")),
                "observed_at": case.get("observed_at"),
            }
            for name, case in sorted(cases.items())
        ],
    }
    return errors, details


def collect_report(
    *,
    manifest_path: Path,
    negative_path: Path,
    rig_validation_path: Path,
    agent_db: Path,
    approval_db: Path,
    audit_db: Path,
    notes_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    manifest, manifest_raw = _load_json(manifest_path)
    negative, negative_raw = _load_json(negative_path)
    identity = candidate_identity()
    assessment, rig_sha = assess_rig_validation(
        rig_validation_path, identity, now=(now or _utc_now()).timestamp()
    )
    if notes_path.is_symlink() or not notes_path.is_file():
        raise PilotEvidenceError(f"notes file is not a regular file: {notes_path}")
    notes_raw = notes_path.read_bytes()
    try:
        notes_text = notes_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PilotEvidenceError("notes file is not UTF-8") from exc
    snapshots = [snapshot_sqlite(agent_db), snapshot_sqlite(approval_db), snapshot_sqlite(audit_db)]
    agent_snapshot, approval_snapshot, audit_snapshot = snapshots
    try:
        runs = load_run_records(agent_snapshot)
        approvals = load_approval_rows(approval_snapshot)
        audits = load_audit_rows(audit_snapshot)
        errors, details = judge(
            manifest=manifest,
            negative=negative,
            run_records=runs,
            approval_rows=approvals,
            audit_rows=audits,
            notes_text=notes_text,
            identity=identity,
            rig_validation_assessment=assessment,
            rig_validation_sha256=rig_sha,
            now=now,
        )
        db_hashes = {
            "agent_db_sha256": _sha_bytes(agent_snapshot.read_bytes()),
            "approval_db_sha256": _sha_bytes(approval_snapshot.read_bytes()),
            "audit_db_sha256": _sha_bytes(audit_snapshot.read_bytes()),
        }
    finally:
        for snapshot in snapshots:
            snapshot.unlink(missing_ok=True)
    return {
        "schema": REPORT_SCHEMA,
        "success": not errors,
        "generated_at": _iso(now or _utc_now()),
        "candidate": identity,
        "pilot_id": manifest.get("pilot_id"),
        "operator": manifest.get("operator"),
        "evidence": {
            "manifest_sha256": _sha_bytes(manifest_raw),
            "negative_sha256": _sha_bytes(negative_raw),
            "rig_validation_report_sha256": rig_sha,
            **db_hashes,
            "notes_sha256": _sha_bytes(notes_raw),
        },
        **details,
        "blockers": errors,
        "production_activation": False,
    }


def _cmd_prepare(args: argparse.Namespace) -> int:
    output = Path(args.manifest)
    if output.exists() and not args.force:
        raise PilotEvidenceError(f"manifest already exists: {output}; use --force deliberately")
    manifest = prepare_manifest(
        operator=args.operator,
        rig_validation_path=Path(args.rig_validation),
    )
    _atomic_json(output, manifest)
    print(f"prepared {RUN_COUNT} T-022 markers in {output}")
    return 0


def _cmd_bind(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    manifest, _raw = _load_json(path)
    bind_run(manifest, args.ordinal, args.run_id)
    _atomic_json(path, manifest)
    print(f"bound ordinal {args.ordinal} to run {args.run_id}")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    report = collect_report(
        manifest_path=Path(args.manifest),
        negative_path=Path(args.negative),
        rig_validation_path=Path(args.rig_validation),
        agent_db=Path(args.agent_db),
        approval_db=Path(args.approval_db),
        audit_db=Path(args.audit_db),
        notes_path=Path(args.notes),
    )
    _atomic_json(Path(args.report), report)
    if report["success"]:
        print(f"T-022 evidence is GREEN: {args.report}")
        return 0
    print(f"T-022 evidence is RED ({len(report['blockers'])} blockers):")
    for blocker in report["blockers"]:
        print(f"- {blocker}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="mint the exact candidate-bound 20-run manifest")
    prepare.add_argument("--operator", required=True)
    prepare.add_argument("--rig-validation", required=True)
    prepare.add_argument("--manifest", required=True)
    prepare.add_argument("--force", action="store_true")
    prepare.set_defaults(func=_cmd_prepare)

    bind = sub.add_parser("bind", help="bind one prepared marker to its physical run id")
    bind.add_argument("--manifest", required=True)
    bind.add_argument("--ordinal", type=int, required=True)
    bind.add_argument("--run-id", required=True)
    bind.set_defaults(func=_cmd_bind)

    collect = sub.add_parser("collect", help="cross-check all physical T-022 evidence")
    collect.add_argument("--manifest", required=True)
    collect.add_argument("--negative", required=True)
    collect.add_argument("--rig-validation", required=True)
    collect.add_argument("--agent-db", required=True)
    collect.add_argument("--approval-db", required=True)
    collect.add_argument("--audit-db", required=True)
    collect.add_argument("--notes", required=True)
    collect.add_argument("--report", required=True)
    collect.set_defaults(func=_cmd_collect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PilotEvidenceError as exc:
        print(f"T-022 evidence error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
