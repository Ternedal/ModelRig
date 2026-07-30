#!/usr/bin/env python3
"""Read-only preflight for the physical T-022 append-only write pilot.

Run after preparing the exact 20-run manifest and before the first preview.
The preflight never sends a write request. It binds live read-only status,
candidate identity, the eligible rig-validation report and uncontaminated
local evidence stores into one explicit go/no-go report.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agent3_write_pilot_common import (  # noqa: E402
    MANIFEST_SCHEMA,
    PILOT_WINDOW_MAX_HOURS,
    PilotEvidenceError,
    _atomic_json,
    _canonical_json,
    _iso,
    _load_json,
    _parse_time,
    _sha_bytes,
    _utc_now,
    assess_rig_validation,
    candidate_identity,
    validate_manifest,
)
from agent3_write_pilot_forensics import (  # noqa: E402
    load_approval_rows,
    load_audit_rows,
    load_run_records,
    snapshot_sqlite,
)

PREFLIGHT_SCHEMA = "kaliv-agent3-write-pilot-preflight/v1"
MAX_HTTP_BYTES = 1_048_576
MAX_NOTES_BYTES = 16_000_000
_ACTIVE_STATES = {"running", "waiting_confirmation"}


def _normalized_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _get_json(base_url: str, path: str, token: str, *, timeout: float = 8.0) -> dict[str, Any]:
    if not token.strip():
        raise PilotEvidenceError("MODELRIG_TOKEN is not set")
    url = base_url.rstrip("/") + path
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token.strip()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_HTTP_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_HTTP_BYTES + 1)
        status = exc.code
    except urllib.error.URLError as exc:
        raise PilotEvidenceError(f"cannot reach {url}: {exc.reason}") from exc
    if len(raw) > MAX_HTTP_BYTES:
        raise PilotEvidenceError(f"response from {path} exceeds {MAX_HTTP_BYTES} bytes")
    if status != 200:
        detail = raw.decode("utf-8", "replace")[:500]
        raise PilotEvidenceError(f"GET {path} returned HTTP {status}: {detail}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotEvidenceError(f"GET {path} did not return UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PilotEvidenceError(f"GET {path} did not return a JSON object")
    return value


def _load_notes(path: Path) -> tuple[str, bytes]:
    if path.is_symlink():
        raise PilotEvidenceError(f"notes path is a symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise PilotEvidenceError(f"notes path is not a regular file: {path}")
        size = path.stat().st_size
        if size > MAX_NOTES_BYTES:
            raise PilotEvidenceError(f"notes file exceeds {MAX_NOTES_BYTES} bytes")
        raw = path.read_bytes()
    else:
        parent = path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise PilotEvidenceError(f"notes directory is not a regular directory: {parent}")
        raw = b""
    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError as exc:
        raise PilotEvidenceError("notes file is not UTF-8") from exc


def _audit_marker(row: dict[str, Any]) -> str | None:
    try:
        args = json.loads(row.get("args_json") or "")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(args, dict):
        return None
    value = args.get("text")
    return value if isinstance(value, str) else None


def _run_markers(record: dict[str, Any]) -> list[str]:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return []
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return []
    markers: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        args = step.get("args")
        if isinstance(args, dict) and isinstance(args.get("text"), str):
            markers.append(args["text"])
    return markers


def judge_preflight(
    *,
    manifest: dict[str, Any],
    identity: dict[str, Any],
    rig_validation_assessment: dict[str, Any],
    rig_validation_sha256: str,
    live_status: dict[str, Any],
    live_tools: dict[str, Any],
    run_records: list[dict[str, Any]],
    approval_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    notes_text: str,
    notes_path: Path,
    negative_journal_exists: bool,
    notes_writable: bool = True,
    journal_parent_writable: bool = True,
    now: datetime | None = None,
) -> tuple[list[str], dict[str, Any]]:
    blockers = validate_manifest(manifest, require_bound=False)
    current = now or _utc_now()
    target = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
    runs = manifest.get("runs") if isinstance(manifest.get("runs"), list) else []
    prefix = str(manifest.get("marker_prefix") or "")
    markers = {
        item.get("marker")
        for item in runs
        if isinstance(item, dict) and isinstance(item.get("marker"), str)
    }

    bound_ordinals = [
        item.get("ordinal")
        for item in runs
        if isinstance(item, dict)
        and (item.get("run_id") is not None or item.get("bound_at") is not None)
    ]
    if bound_ordinals:
        blockers.append(
            "manifest is already in use; preflight requires all 20 runs unbound: "
            + ", ".join(map(str, bound_ordinals))
        )

    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        if target.get(field) != identity.get(field):
            blockers.append(f"candidate {field} does not match the prepared manifest")
    if target.get("rig_validation_report_sha256") != rig_validation_sha256:
        blockers.append("rig-validation report SHA does not match the prepared manifest")
    if rig_validation_assessment.get("eligible_for_write_pilot") is not True:
        blockers.append("rig-validation report is not eligible for the write pilot")

    created = _parse_time(manifest.get("created_at"))
    manifest_age_seconds: float | None = None
    if created is not None:
        manifest_age_seconds = (current - created).total_seconds()
        if manifest_age_seconds < -900:
            blockers.append("manifest creation time is more than 15 minutes in the future")
        elif manifest_age_seconds > PILOT_WINDOW_MAX_HOURS * 3600:
            blockers.append("manifest is older than the complete 12-hour pilot window")

    required_status = {
        "enabled": True,
        "experimental": True,
        "write_approval_required": True,
        "production_tools_path_untouched": True,
        "production_activation": False,
    }
    for field, expected in required_status.items():
        if live_status.get(field) is not expected:
            blockers.append(f"live Agent 3 status {field} must be {expected!r}")
    if live_status.get("write_approval") != "backend-issued-device-bound-single-use":
        blockers.append("live Agent 3 approval mode is not the device-bound single-use contract")
    if live_status.get("worker_version") != target.get("version"):
        blockers.append("live worker version does not match the manifest candidate")
    if live_status.get("code_sha256") != target.get("code_sha256"):
        blockers.append("live worker code identity does not match the manifest candidate")
    live_rig = live_status.get("rig_validation")
    if not isinstance(live_rig, dict):
        blockers.append("live Agent 3 status has no rig_validation object")
        live_rig = {}
    for field in ("eligible_for_write_pilot", "version_match", "code_match"):
        if live_rig.get(field) is not True:
            blockers.append(f"live rig_validation {field} is not true")
    if live_rig.get("report_sha256") != target.get("rig_validation_report_sha256"):
        blockers.append("live worker is evaluating another rig-validation report")

    tools = live_tools.get("tools")
    if live_tools.get("enabled") is not True:
        blockers.append("the live tool layer is disabled")
    if not isinstance(tools, list):
        blockers.append("live tool registry is not an array")
        tools = []
    note_tools = [
        item for item in tools
        if isinstance(item, dict) and item.get("name") == "note_append"
    ]
    if len(note_tools) != 1:
        blockers.append("live tool registry must contain exactly one note_append entry")
    else:
        note = note_tools[0]
        expected_note = {
            "enabled": True,
            "risk": "write",
            "impact": "write",
            "network": "none",
            "idempotent": False,
        }
        for field, expected in expected_note.items():
            if note.get(field) != expected:
                blockers.append(f"live note_append {field} must be {expected!r}")
    other_enabled_writes = sorted(
        str(item.get("name"))
        for item in tools
        if isinstance(item, dict)
        and item.get("name") != "note_append"
        and item.get("enabled") is True
        and (item.get("risk") != "read" or item.get("impact") != "read")
    )
    if other_enabled_writes:
        blockers.append(
            "other write/admin/destructive tools are enabled: "
            + ", ".join(other_enabled_writes)
        )
    tools_dir = live_tools.get("tools_dir")
    if not isinstance(tools_dir, str) or not tools_dir.strip():
        blockers.append("live tool registry does not report tools_dir")
    else:
        expected_notes = _normalized_path(Path(tools_dir) / "notes.md")
        if expected_notes != _normalized_path(notes_path):
            blockers.append("the supplied notes path does not match live tools_dir")

    note_lines = notes_text.splitlines()
    contaminated_notes = sorted(
        line for line in note_lines
        if line.startswith(prefix) or line in markers
    )
    if contaminated_notes:
        blockers.append(
            f"notes.md already contains {len(contaminated_notes)} marker(s) for this pilot"
        )

    contaminated_runs = sorted(
        str(record.get("id"))
        for record in run_records
        if any(
            marker.startswith(prefix) or marker in markers
            for marker in _run_markers(record)
        )
    )
    if contaminated_runs:
        blockers.append(
            "Agent 3 ledger already contains this pilot prefix: "
            + ", ".join(contaminated_runs)
        )
    active_runs = sorted(
        str(record.get("id"))
        for record in run_records
        if record.get("state") in _ACTIVE_STATES
    )
    if active_runs:
        blockers.append("Agent 3 is not idle: " + ", ".join(active_runs))

    contaminated_audits = [
        marker
        for row in audit_rows
        if isinstance((marker := _audit_marker(row)), str)
        and (marker.startswith(prefix) or marker in markers)
    ]
    if contaminated_audits:
        blockers.append(
            f"ToolGate audit already contains {len(contaminated_audits)} marker(s) for this pilot"
        )
    if not notes_writable:
        blockers.append("notes file/directory is not writable by the preflight process")
    if negative_journal_exists:
        blockers.append("negative evidence journal already exists; use a fresh path")
    if not journal_parent_writable:
        blockers.append("negative evidence journal directory is not writable")

    details = {
        "manifest_age_seconds": manifest_age_seconds,
        "bound_ordinals": bound_ordinals,
        "baseline": {
            "agent_runs": len(run_records),
            "approval_uses": len(approval_rows),
            "tool_audit_rows": len(audit_rows),
            "notes_lines": len(note_lines),
        },
        "contamination": {
            "note_markers": len(contaminated_notes),
            "run_ids": contaminated_runs,
            "audit_markers": len(contaminated_audits),
            "active_run_ids": active_runs,
        },
        "live": {
            "worker_version": live_status.get("worker_version"),
            "code_sha256": live_status.get("code_sha256"),
            "write_approval_required": live_status.get("write_approval_required"),
            "tools_dir": tools_dir,
            "other_enabled_writes": other_enabled_writes,
        },
        "production_activation": False,
    }
    return blockers, details


def run_preflight(
    *,
    manifest_path: Path,
    rig_validation_path: Path,
    agent_db: Path,
    approval_db: Path,
    audit_db: Path,
    notes_path: Path,
    negative_journal_path: Path,
    base_url: str,
    token: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    manifest, manifest_raw = _load_json(manifest_path)
    identity = candidate_identity()
    assessment, rig_sha = assess_rig_validation(
        rig_validation_path,
        identity,
        now=(now or _utc_now()).timestamp(),
    )
    live_status = _get_json(
        base_url, "/api/v1/experimental/agent3/status", token
    )
    live_tools = _get_json(base_url, "/api/v1/tools", token)
    notes_text, notes_raw = _load_notes(notes_path)

    notes_target = notes_path if notes_path.exists() else notes_path.parent
    notes_writable = os.access(notes_target, os.W_OK)
    journal_parent = negative_journal_path.parent
    if journal_parent.is_symlink() or not journal_parent.is_dir():
        raise PilotEvidenceError(
            f"negative evidence journal directory is not a regular directory: {journal_parent}"
        )
    journal_parent_writable = os.access(journal_parent, os.W_OK)

    snapshots: list[Path] = []
    try:
        for database in (agent_db, approval_db, audit_db):
            snapshots.append(snapshot_sqlite(database))
        agent_snapshot, approval_snapshot, audit_snapshot = snapshots
        run_records = load_run_records(agent_snapshot)
        approval_rows = load_approval_rows(approval_snapshot)
        audit_rows = load_audit_rows(audit_snapshot)
        blockers, details = judge_preflight(
            manifest=manifest,
            identity=identity,
            rig_validation_assessment=assessment,
            rig_validation_sha256=rig_sha,
            live_status=live_status,
            live_tools=live_tools,
            run_records=run_records,
            approval_rows=approval_rows,
            audit_rows=audit_rows,
            notes_text=notes_text,
            notes_path=notes_path,
            negative_journal_exists=(negative_journal_path.exists() or negative_journal_path.is_symlink()),
            notes_writable=notes_writable,
            journal_parent_writable=journal_parent_writable,
            now=now,
        )
        evidence = {
            "manifest_sha256": _sha_bytes(manifest_raw),
            "rig_validation_report_sha256": rig_sha,
            "agent_db_sha256": _sha_bytes(agent_snapshot.read_bytes()),
            "approval_db_sha256": _sha_bytes(approval_snapshot.read_bytes()),
            "audit_db_sha256": _sha_bytes(audit_snapshot.read_bytes()),
            "notes_sha256": _sha_bytes(notes_raw),
            "live_status_sha256": _sha_bytes(_canonical_json(live_status)),
            "live_tools_sha256": _sha_bytes(_canonical_json(live_tools)),
        }
    finally:
        for snapshot in snapshots:
            snapshot.unlink(missing_ok=True)

    return {
        "schema": PREFLIGHT_SCHEMA,
        "success": not blockers,
        "generated_at": _iso(now or _utc_now()),
        "pilot_id": manifest.get("pilot_id"),
        "operator": manifest.get("operator"),
        "candidate": {
            key: identity.get(key)
            for key in (
                "version",
                "git_sha",
                "code_sha256",
                "identity_source",
                "working_tree_clean",
                "version_stamps_consistent",
            )
        },
        "backend": {"base_url": base_url.rstrip("/")},
        "evidence": evidence,
        **details,
        "blockers": blockers,
        "production_activation": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--rig-validation", required=True)
    parser.add_argument("--agent-db", required=True)
    parser.add_argument("--approval-db", required=True)
    parser.add_argument("--audit-db", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--negative-journal", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MODELRIG_BASE_URL", "http://127.0.0.1:8080"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        token = os.environ.get("MODELRIG_TOKEN", "")
        report = run_preflight(
            manifest_path=Path(args.manifest),
            rig_validation_path=Path(args.rig_validation),
            agent_db=Path(args.agent_db),
            approval_db=Path(args.approval_db),
            audit_db=Path(args.audit_db),
            notes_path=Path(args.notes),
            negative_journal_path=Path(args.negative_journal),
            base_url=args.base_url,
            token=token,
        )
        _atomic_json(Path(args.report), report)
        if report["success"]:
            print(f"T-022 preflight is GREEN: {args.report}")
            return 0
        print(f"T-022 preflight is RED ({len(report['blockers'])} blockers):")
        for blocker in report["blockers"]:
            print(f"- {blocker}")
        return 1
    except PilotEvidenceError as exc:
        print(f"T-022 preflight error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
