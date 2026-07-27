#!/usr/bin/env python3
"""Read-only SQLite and run-ledger forensics for the T-022 write pilot."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

from agent3_write_pilot_common import (
    _REQUIRED_EVENTS, _SHA256, PilotEvidenceError, _canonical_json, _sha_bytes,
    _sha_text,
)

def _ro(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise PilotEvidenceError(f"database is not a regular file: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def snapshot_sqlite(path: Path) -> Path:
    """Create one transactionally consistent SQLite image, including WAL state."""
    source = _ro(path)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".snapshot.", suffix=".db")
    os.close(fd)
    target_path = Path(tmp_name)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
        target.commit()
    except Exception:
        target.close()
        source.close()
        target_path.unlink(missing_ok=True)
        raise
    target.close()
    source.close()
    return target_path


def load_run_records(agent_db: Path) -> list[dict[str, Any]]:
    conn = _ro(agent_db)
    try:
        rows = conn.execute(
            "SELECT id,state,payload,updated_at FROM agent_runs ORDER BY updated_at"
        ).fetchall()
        events = conn.execute(
            "SELECT run_id,ts,kind,payload FROM agent_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    by_run: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = row["payload"]
        by_run.setdefault(row["run_id"], []).append(
            {"ts": row["ts"], "kind": row["kind"], "payload": payload}
        )
    result = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = None
        result.append(
            {
                "id": row["id"],
                "state": row["state"],
                "payload": payload,
                "updated_at": row["updated_at"],
                "events": by_run.get(row["id"], []),
            }
        )
    return result


def load_approval_rows(approval_db: Path) -> list[dict[str, Any]]:
    conn = _ro(approval_db)
    try:
        rows = conn.execute(
            "SELECT nonce_sha256,action_sha256,used_at,run_id,step_id,device_id,"
            "plan_revision,token_sha256 FROM agent3_approval_uses ORDER BY used_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def load_audit_rows(audit_db: Path) -> list[dict[str, Any]]:
    conn = _ro(audit_db)
    try:
        rows = conn.execute(
            "SELECT id,ts,conversation_id,tool,args_json,risk,outcome,confirmation_id,"
            "origin,result_summary,duration_ms FROM audit ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _ordered_contains(values: list[str], required: Iterable[str]) -> bool:
    cursor = 0
    for item in required:
        try:
            cursor = values.index(item, cursor) + 1
        except ValueError:
            return False
    return True


def _action_sha(run_id: str, step_id: str, digest: str, revision: int) -> str:
    return _sha_bytes(
        _canonical_json(
            {
                "run_id": run_id,
                "step_id": step_id,
                "confirmation_digest": digest,
                "plan_revision": revision,
            }
        )
    )


def _marker_from_run(record: dict[str, Any]) -> str | None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    steps = payload.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
        return None
    args = steps[0].get("args")
    if not isinstance(args, dict) or set(args) != {"text"}:
        return None
    text = args.get("text")
    return text if isinstance(text, str) else None


def _event_one(record: dict[str, Any], kind: str) -> dict[str, Any] | None:
    matches = [event for event in record.get("events", []) if event.get("kind") == kind]
    if len(matches) != 1 or not isinstance(matches[0].get("payload"), dict):
        return None
    return matches[0]


def _validate_success_run(
    *,
    record: dict[str, Any],
    marker: str,
    approval_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    errors: list[str],
    label: str,
) -> dict[str, Any] | None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        errors.append(f"{label}: run payload is invalid JSON")
        return None
    run_id = record.get("id")
    if record.get("state") != "completed" or payload.get("state") != "completed":
        errors.append(f"{label}: run is not completed")
    route = payload.get("route")
    if not isinstance(route, dict) or route.get("kind") != "rig_tools_local":
        errors.append(f"{label}: run route is not rig_tools_local")
    steps = payload.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
        errors.append(f"{label}: run must contain exactly one step")
        return None
    step = steps[0]
    if (
        step.get("tool") != "note_append"
        or step.get("args") != {"text": marker}
        or step.get("risk") != "write"
        or step.get("egress") != "local"
        or step.get("idempotent") is not False
        or step.get("state") != "succeeded"
    ):
        errors.append(f"{label}: immutable step is not the exact append-only marker")
    step_id = step.get("id")
    if not isinstance(step_id, str) or not step_id:
        errors.append(f"{label}: step id is missing")
        return None

    kinds = [str(event.get("kind") or "") for event in record.get("events", [])]
    if not _ordered_contains(kinds, _REQUIRED_EVENTS):
        errors.append(f"{label}: required event chain is incomplete or out of order")
    for forbidden in (
        "confirmation_denied",
        "confirmation_expired",
        "run_cancelled",
        "step_completed_after_cancel",
        "step_failed",
    ):
        if forbidden in kinds:
            errors.append(f"{label}: forbidden event {forbidden} is present")
    for exactly_once in (
        "approval_consumed",
        "confirmation_approved",
        "step_started",
        "step_succeeded",
        "run_completed",
    ):
        if kinds.count(exactly_once) != 1:
            errors.append(f"{label}: event {exactly_once} must occur exactly once")

    approval_event = _event_one(record, "approval_consumed")
    if approval_event is None:
        errors.append(f"{label}: approval_consumed attribution is missing")
        return None
    receipt = approval_event["payload"]
    if receipt.get("step_id") != step_id or receipt.get("tool") != "note_append":
        errors.append(f"{label}: approval event is bound to another step/tool")
    device_id = receipt.get("device_id")
    revision = receipt.get("plan_revision")
    digest = receipt.get("confirmation_digest")
    args_sha = receipt.get("args_sha256")
    action_sha = receipt.get("approval_action_sha256")
    nonce_sha = receipt.get("approval_nonce_sha256")
    token_sha = receipt.get("approval_token_sha256")
    if not isinstance(device_id, str) or not device_id.strip():
        errors.append(f"{label}: approval device attribution is missing")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        errors.append(f"{label}: approval plan revision is invalid")
    for name, value in (
        ("confirmation_digest", digest),
        ("args_sha256", args_sha),
        ("approval_action_sha256", action_sha),
        ("approval_nonce_sha256", nonce_sha),
        ("approval_token_sha256", token_sha),
    ):
        if not _SHA256.fullmatch(str(value or "")):
            errors.append(f"{label}: {name} is invalid")
    if args_sha != _sha_text(marker):
        errors.append(f"{label}: approval args hash does not bind the exact marker")
    if (
        isinstance(revision, int)
        and isinstance(digest, str)
        and _SHA256.fullmatch(digest)
        and action_sha != _action_sha(str(run_id), step_id, digest, revision)
    ):
        errors.append(f"{label}: approval action hash does not bind run/step/digest/revision")

    matching_approvals = [
        row
        for row in approval_rows
        if row.get("run_id") == run_id and row.get("step_id") == step_id
    ]
    if len(matching_approvals) != 1:
        errors.append(f"{label}: approval-use database must contain exactly one matching row")
    else:
        row = matching_approvals[0]
        for field, expected in (
            ("device_id", device_id),
            ("plan_revision", revision),
            ("action_sha256", action_sha),
            ("nonce_sha256", nonce_sha),
            ("token_sha256", token_sha),
        ):
            if row.get(field) != expected:
                errors.append(f"{label}: approval DB {field} disagrees with the run ledger")
        used_at = row.get("used_at")
        issued_at = receipt.get("issued_at")
        expires_at = receipt.get("expires_at")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (used_at, issued_at, expires_at)):
            errors.append(f"{label}: approval times are invalid")
        elif not (issued_at - 30 <= used_at <= expires_at):
            errors.append(f"{label}: approval consumption is outside its validity window")

    matching_audits = []
    for row in audit_rows:
        if row.get("tool") != "note_append":
            continue
        try:
            args = json.loads(row.get("args_json") or "")
        except (TypeError, json.JSONDecodeError):
            continue
        if args == {"text": marker}:
            matching_audits.append(row)
    executed = [row for row in matching_audits if row.get("outcome") == "executed"]
    if len(executed) != 1:
        errors.append(f"{label}: ToolGate audit must contain exactly one executed append")
    elif executed[0].get("risk") != "write" or executed[0].get("origin") != "local":
        errors.append(f"{label}: executed audit has the wrong risk/origin")

    return {
        "run_id": run_id,
        "step_id": step_id,
        "device_id": device_id,
        "plan_revision": revision,
        "marker_sha256": _sha_text(marker),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
        "approval_used_at": matching_approvals[0].get("used_at") if len(matching_approvals) == 1 else None,
    }
