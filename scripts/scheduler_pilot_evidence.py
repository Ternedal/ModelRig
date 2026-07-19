#!/usr/bin/env python3
"""Collect candidate-bound evidence after the physical Scheduler pilot (T-019).

The collector is read-only. It does not create, approve, enable, revoke or execute
schedules. It reads the backend/worker identities plus the existing schedule,
job and audit SQLite files and writes one redacted atomic report.

The manifest names exact schedule and occurrence ids. No fuzzy "latest run"
selection is allowed. The report never contains the paired-device token,
`note_append` text, full tool results, raw args, receipt nonces or database paths.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "kaliv-scheduler-pilot-evidence/v1"
MANIFEST_SCHEMA = "kaliv-scheduler-pilot-manifest/v1"
MAX_JSON_BYTES = 256 * 1024
_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_OCCURRENCES = {"executed", "released", "abandoned"}
_TERMINAL_JOBS = {"completed", "failed", "cancelled", "interrupted"}


class PilotError(RuntimeError):
    """Evidence cannot be collected or trusted."""


@dataclass(frozen=True)
class DataPaths:
    schedules: Path
    jobs: Path
    audit: Path
    notes: Path


RuntimeGet = Callable[[str, str | None], dict[str, Any]]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_sha(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise PilotError(f"JSON path must not be a symlink: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PilotError(f"cannot read JSON file: {path}: {exc}") from exc
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise PilotError(f"JSON file size is invalid: {path} ({len(raw)} bytes)")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotError(f"JSON file is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PilotError(f"JSON root must be an object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        temp = Path(handle.name)
    temp.replace(path)


def _run(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def _worker_code_fingerprint(root: Path) -> str:
    path = root / "worker" / "app" / "build_identity.py"
    spec = importlib.util.spec_from_file_location("pilot_build_identity", path)
    if spec is None or spec.loader is None:
        raise PilotError("worker build identity module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.code_fingerprint()
    if not isinstance(value, str) or not _HEX_64.fullmatch(value):
        raise PilotError("worker source fingerprint is malformed")
    return value


def source_candidate(root: Path) -> dict[str, str]:
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PilotError("VERSION cannot be read") from exc
    rc, git_sha = _run(root, "git", "rev-parse", "HEAD")
    if not version or rc != 0 or not _HEX_40.fullmatch(git_sha):
        raise PilotError("source candidate identity is incomplete")
    _, dirty = _run(root, "git", "status", "--porcelain")
    if dirty:
        raise PilotError("working tree must be clean while collecting pilot evidence")
    return {
        "version": version,
        "git_sha": git_sha,
        "code_sha256": _worker_code_fingerprint(root),
    }


def _require_text(value: Any, label: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")
        return None
    return value.strip()


def _require_int(value: Any, label: str, errors: list[str], *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        errors.append(f"{label} must be an integer >= {minimum}")
        return None
    return value


def _iso_epoch(value: Any, label: str, errors: list[str]) -> float | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be an ISO-8601 datetime with offset")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} must be an ISO-8601 datetime with offset")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} must include a timezone offset")
        return None
    return parsed.astimezone(timezone.utc).timestamp()


def _audit_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _within_window(value: Any, window: dict[str, float]) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and window["started_epoch"] <= float(value) <= window["finished_epoch"]
    )


def _claim_ids(value: Any, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty array")
        return []
    if not all(isinstance(item, str) and item.strip() for item in value):
        errors.append(f"{label} must contain non-empty strings")
        return []
    result = [item.strip() for item in value]
    if len(set(result)) != len(result):
        errors.append(f"{label} contains duplicate claim ids")
    return result


def validate_manifest(value: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if value.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"manifest.schema must be {MANIFEST_SCHEMA!r}")
    candidate = value.get("candidate")
    if not isinstance(candidate, dict):
        errors.append("manifest.candidate must be an object")
        candidate = {}
    for key, pattern in (("version", None), ("git_sha", _HEX_40), ("code_sha256", _HEX_64)):
        item = _require_text(candidate.get(key), f"candidate.{key}", errors)
        if item is not None and pattern is not None and not pattern.fullmatch(item):
            errors.append(f"candidate.{key} has an invalid digest shape")

    window_raw = value.get("window")
    if not isinstance(window_raw, dict):
        errors.append("manifest.window must be an object")
        window_raw = {}
    started_epoch = _iso_epoch(window_raw.get("started_at"), "window.started_at", errors)
    finished_epoch = _iso_epoch(window_raw.get("finished_at"), "window.finished_at", errors)
    if (
        started_epoch is not None
        and finished_epoch is not None
        and started_epoch >= finished_epoch
    ):
        errors.append("window.started_at must be before window.finished_at")

    trials = value.get("trials")
    if not isinstance(trials, dict):
        errors.append("manifest.trials must be an object")
        trials = {}

    normalized: dict[str, Any] = {}
    for name in ("read", "write"):
        raw = trials.get(name)
        if not isinstance(raw, dict):
            errors.append(f"trials.{name} must be an object")
            raw = {}
        normalized[name] = {
            "schedule_id": _require_text(raw.get("schedule_id"), f"trials.{name}.schedule_id", errors),
            "tool": _require_text(raw.get("tool"), f"trials.{name}.tool", errors),
            "cadence": _require_text(raw.get("cadence"), f"trials.{name}.cadence", errors),
            "max_runs": _require_int(raw.get("max_runs"), f"trials.{name}.max_runs", errors, minimum=1),
            "claim_ids": _claim_ids(raw.get("claim_ids"), f"trials.{name}.claim_ids", errors),
            "args_sha256": _require_text(raw.get("args_sha256"), f"trials.{name}.args_sha256", errors),
        }
        digest = normalized[name]["args_sha256"]
        if digest is not None and not _HEX_64.fullmatch(digest):
            errors.append(f"trials.{name}.args_sha256 must be 64 lowercase hex characters")

    write = normalized["write"]
    write_raw = trials.get("write") if isinstance(trials.get("write"), dict) else {}
    write["marker_sha256"] = _require_text(
        write_raw.get("marker_sha256"), "trials.write.marker_sha256", errors
    )
    if write["marker_sha256"] is not None and not _HEX_64.fullmatch(write["marker_sha256"]):
        errors.append("trials.write.marker_sha256 must be 64 lowercase hex characters")
    write["device_id"] = _require_text(
        write_raw.get("device_id"), "trials.write.device_id", errors
    )

    for name in ("revoke", "recovery"):
        raw = trials.get(name)
        if not isinstance(raw, dict):
            errors.append(f"trials.{name} must be an object")
            raw = {}
        normalized[name] = {
            "schedule_id": _require_text(raw.get("schedule_id"), f"trials.{name}.schedule_id", errors),
            "claim_id": _require_text(raw.get("claim_id"), f"trials.{name}.claim_id", errors),
        }
    recovery_raw = trials.get("recovery") if isinstance(trials.get("recovery"), dict) else {}
    expected = recovery_raw.get("expected_status")
    if expected not in {"executed", "abandoned"}:
        errors.append("trials.recovery.expected_status must be 'executed' or 'abandoned'")
    normalized["recovery"]["expected_status"] = expected

    all_claims = (
        normalized["read"]["claim_ids"]
        + normalized["write"]["claim_ids"]
        + [normalized["revoke"].get("claim_id"), normalized["recovery"].get("claim_id")]
    )
    clean_claims = [item for item in all_claims if isinstance(item, str)]
    if len(clean_claims) != len(set(clean_claims)):
        errors.append("claim ids must be unique across all pilot trials")

    return {
        "schema": MANIFEST_SCHEMA,
        "candidate": dict(candidate),
        "window": {
            "started_at": window_raw.get("started_at"),
            "finished_at": window_raw.get("finished_at"),
            "started_epoch": started_epoch,
            "finished_epoch": finished_epoch,
        },
        "trials": normalized,
    }, errors


def _loopback_url(value: str, label: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise PilotError(f"{label} must be an HTTP(S) URL without userinfo")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PilotError(f"{label} must be loopback; evidence collection runs on the rig")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise PilotError(f"{label} must be a base URL")
    return value.rstrip("/")


def http_get_json(url: str, token: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise PilotError(f"GET {url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PilotError(f"cannot reach {url}: {exc.reason}") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise PilotError(f"GET {url} returned an oversized response")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotError(f"GET {url} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise PilotError(f"GET {url} returned a non-object JSON response")
    return value


def collect_runtime(
    backend_url: str,
    worker_url: str,
    token: str,
    get_json: RuntimeGet = http_get_json,
) -> dict[str, Any]:
    backend = get_json(_loopback_url(backend_url, "backend URL") + "/api/v1/status", token)
    worker = get_json(_loopback_url(worker_url, "worker URL") + "/health/full", None)
    scheduler = get_json(_loopback_url(worker_url, "worker URL") + "/schedules/status", None)
    return {
        "backend_version": backend.get("version"),
        "worker_version": ((worker.get("checks") or {}).get("worker") or {}).get("version"),
        "worker_code_sha256": (worker.get("build") or {}).get("code_sha256"),
        "worker_frozen": (worker.get("build") or {}).get("frozen"),
        "scheduler_configured": scheduler.get("configured"),
        "scheduler_running": scheduler.get("running"),
        "scheduler_resources_open": scheduler.get("resources_open"),
        "scheduler_last_error": scheduler.get("last_error"),
    }


def _default_data_root() -> Path:
    explicit = os.getenv("KALIV_DATA_DIR")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Kaliv"
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "kaliv"


def default_paths() -> DataPaths:
    root = _default_data_root()
    tools_dir = Path(os.getenv("KALIV_TOOLS_DIR") or (Path.home() / "Documents" / "Kaliv"))
    return DataPaths(
        schedules=Path(os.getenv("KALIV_SCHEDULES_DB") or (root / "kaliv-schedules.db")),
        jobs=Path(os.getenv("MODELRIG_JOBS_DB") or (root / "modelrig-jobs.db")),
        audit=Path(os.getenv("KALIV_AUDIT_DB") or (root / "kaliv-audit.db")),
        notes=tools_dir / "notes.md",
    )


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise PilotError(f"required SQLite file is missing or invalid: {path.name}")
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise PilotError(f"cannot open SQLite file read-only: {path.name}") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error as exc:
        raise PilotError(f"cannot inspect table {table!r}") from exc


def _require_columns(conn: sqlite3.Connection, table: str, expected: set[str]) -> None:
    missing = expected - _table_columns(conn, table)
    if missing:
        raise PilotError(f"table {table!r} is missing columns: {sorted(missing)}")


def _load_sources(paths: DataPaths) -> tuple[sqlite3.Connection, sqlite3.Connection, sqlite3.Connection]:
    schedules = _connect_readonly(paths.schedules)
    jobs = _connect_readonly(paths.jobs)
    audit = _connect_readonly(paths.audit)
    try:
        _require_columns(
            schedules,
            "schedules",
            {"id", "tool", "args", "cadence", "approved_fingerprint", "max_runs", "runs_used", "enabled", "revision"},
        )
        _require_columns(
            schedules,
            "occurrences",
            {"claim_id", "schedule_id", "occurrence_due_at", "status", "created", "resolved", "job_id"},
        )
        _require_columns(
            schedules,
            "approval_receipts",
            {"schedule_id", "kind", "fingerprint", "device_id", "nonce", "issued_at", "consumed_at", "revision"},
        )
        _require_columns(jobs, "jobs", {"id", "kind", "status", "detail", "created", "updated"})
        _require_columns(
            audit,
            "audit",
            {"ts", "conversation_id", "tool", "args_json", "risk", "outcome", "confirmation_id", "origin"},
        )
    except Exception:
        schedules.close()
        jobs.close()
        audit.close()
        raise
    return schedules, jobs, audit


def _schedule(conn: sqlite3.Connection, schedule_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
    if row is None:
        return None
    value = dict(row)
    try:
        args = json.loads(value["args"])
    except (TypeError, json.JSONDecodeError):
        args = None
    value["args_value"] = args
    return value


def _occurrence(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM occurrences WHERE claim_id=?", (claim_id,)).fetchone()
    return dict(row) if row is not None else None


def _job(conn: sqlite3.Connection, job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row is not None else None


def _audits(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT ts, conversation_id, tool, args_json, risk, outcome, "
        "confirmation_id, origin FROM audit WHERE conversation_id=? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _receipts(conn: sqlite3.Connection, schedule_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT kind, fingerprint, device_id, nonce, issued_at, consumed_at, revision "
        "FROM approval_receipts WHERE schedule_id=? ORDER BY id",
        (schedule_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _check_schedule(
    conn: sqlite3.Connection,
    spec: dict[str, Any],
    *,
    require_approval: bool,
    errors: list[str],
) -> dict[str, Any] | None:
    schedule_id = spec["schedule_id"]
    row = _schedule(conn, schedule_id)
    if row is None:
        errors.append(f"schedule {schedule_id!r} does not exist")
        return None
    if row.get("tool") != spec["tool"]:
        errors.append(f"schedule {schedule_id}: tool mismatch")
    if row.get("cadence") != spec["cadence"]:
        errors.append(f"schedule {schedule_id}: cadence mismatch")
    if row.get("max_runs") != spec["max_runs"]:
        errors.append(f"schedule {schedule_id}: max_runs mismatch")
    args = row.get("args_value")
    if not isinstance(args, dict):
        errors.append(f"schedule {schedule_id}: args are not a JSON object")
    elif _json_sha(args) != spec["args_sha256"]:
        errors.append(f"schedule {schedule_id}: args hash mismatch")
    fp = row.get("approved_fingerprint")
    if require_approval:
        if not isinstance(fp, str) or not _HEX_32.fullmatch(fp):
            errors.append(f"schedule {schedule_id}: approved fingerprint is missing or malformed")
    elif fp is not None:
        errors.append(f"schedule {schedule_id}: read schedule unexpectedly has write approval")
    return row


def _claim_evidence(
    schedules: sqlite3.Connection,
    jobs: sqlite3.Connection,
    audit: sqlite3.Connection,
    schedule_id: str,
    claim_id: str,
    *,
    expected_status: str,
    expected_tool: str | None,
    expected_risk: str | None,
    expected_confirmation: str | None,
    expected_args_sha256: str | None,
    window: dict[str, float],
    errors: list[str],
) -> dict[str, Any]:
    occurrence = _occurrence(schedules, claim_id)
    result: dict[str, Any] = {
        "claim_id": claim_id,
        "status": None,
        "job_id": None,
        "job_status": None,
        "audit_executions": 0,
    }
    if occurrence is None:
        errors.append(f"claim {claim_id!r} does not exist")
        return result
    if occurrence.get("schedule_id") != schedule_id:
        errors.append(f"claim {claim_id}: schedule binding mismatch")
    status = occurrence.get("status")
    result["status"] = status
    result["occurrence_due_at"] = occurrence.get("occurrence_due_at")
    result["created"] = occurrence.get("created")
    result["resolved"] = occurrence.get("resolved")
    if status != expected_status:
        errors.append(f"claim {claim_id}: expected status {expected_status!r}, got {status!r}")
    if status not in _TERMINAL_OCCURRENCES:
        errors.append(f"claim {claim_id}: occurrence is not terminal")
    if not _within_window(occurrence.get("created"), window):
        errors.append(f"claim {claim_id}: occurrence was not created inside the pilot window")
    if not _within_window(occurrence.get("resolved"), window):
        errors.append(f"claim {claim_id}: occurrence was not resolved inside the pilot window")

    job_id = occurrence.get("job_id")
    result["job_id"] = job_id
    job = _job(jobs, job_id)
    if job is None:
        errors.append(f"claim {claim_id}: bound job is missing")
    else:
        result["job_status"] = job.get("status")
        result["job_kind"] = job.get("kind")
        if job.get("status") not in _TERMINAL_JOBS:
            errors.append(f"claim {claim_id}: job is not terminal")
        expected_job_states = {
            "executed": {"completed"},
            "released": {"cancelled", "failed"},
            "abandoned": {"failed", "interrupted"},
        }[expected_status]
        if job.get("status") not in expected_job_states:
            errors.append(
                f"claim {claim_id}: job status {job.get('status')!r} "
                f"does not match occurrence status {expected_status!r}"
            )
        if not _within_window(job.get("created"), window):
            errors.append(f"claim {claim_id}: job was not created inside the pilot window")
        if not _within_window(job.get("updated"), window):
            errors.append(f"claim {claim_id}: job was not finalized inside the pilot window")

    conversation_id = f"schedule:{schedule_id}:occ:{claim_id}"
    rows = _audits(audit, conversation_id)
    executed = [row for row in rows if row.get("outcome") == "executed"]
    result["audit_rows"] = len(rows)
    result["audit_executions"] = len(executed)
    if expected_status == "executed":
        if len(executed) != 1:
            errors.append(f"claim {claim_id}: expected exactly one executed audit row")
        elif expected_tool is not None:
            row = executed[0]
            if row.get("tool") != expected_tool:
                errors.append(f"claim {claim_id}: audit tool mismatch")
            if row.get("risk") != expected_risk:
                errors.append(f"claim {claim_id}: audit risk mismatch")
            if row.get("origin") != "schedule":
                errors.append(f"claim {claim_id}: audit origin is not schedule")
            if row.get("confirmation_id") != expected_confirmation:
                errors.append(f"claim {claim_id}: audit confirmation binding mismatch")
            audit_epoch = _audit_epoch(row.get("ts"))
            if audit_epoch is None or not _within_window(audit_epoch, window):
                errors.append(f"claim {claim_id}: audit execution is outside the pilot window")
            try:
                audit_args = json.loads(row.get("args_json") or "")
            except json.JSONDecodeError:
                audit_args = None
            if (
                expected_args_sha256 is not None
                and (not isinstance(audit_args, dict) or _json_sha(audit_args) != expected_args_sha256)
            ):
                errors.append(f"claim {claim_id}: audit args hash mismatch")
    elif executed:
        errors.append(f"claim {claim_id}: non-executed occurrence has executed audit evidence")
    return result


def collect_evidence(
    manifest: dict[str, Any],
    *,
    candidate: dict[str, str],
    runtime: dict[str, Any],
    paths: DataPaths,
    now: float | None = None,
) -> tuple[dict[str, Any], int]:
    generated = time.time() if now is None else now
    normalized, errors = validate_manifest(manifest)
    window = normalized["window"]
    if not isinstance(window.get("started_epoch"), (int, float)) or not isinstance(
        window.get("finished_epoch"), (int, float)
    ):
        # Keep later checks deterministic even for a malformed manifest.
        window = {"started_epoch": math.inf, "finished_epoch": -math.inf}
    expected_candidate = normalized["candidate"]
    for key in ("version", "git_sha", "code_sha256"):
        if expected_candidate.get(key) != candidate.get(key):
            errors.append(f"manifest candidate {key} does not match the checkout")
    if runtime.get("backend_version") != candidate["version"]:
        errors.append("backend version does not match the checkout")
    if runtime.get("worker_version") != candidate["version"]:
        errors.append("worker version does not match the checkout")
    if runtime.get("worker_code_sha256") != candidate["code_sha256"]:
        errors.append("worker code fingerprint does not match the checkout")
    if runtime.get("worker_frozen") is not True:
        errors.append("worker is not the packaged appliance build")
    if runtime.get("scheduler_configured") is not True:
        errors.append("scheduler runtime is not configured")
    if runtime.get("scheduler_running") is not True:
        errors.append("scheduler runtime is not running")
    if runtime.get("scheduler_resources_open") is not True:
        errors.append("scheduler runtime resources are not open")
    if runtime.get("scheduler_last_error") not in (None, ""):
        errors.append("scheduler runtime reports an error")

    phases: dict[str, Any] = {}
    schedules = jobs = audit = None
    try:
        schedules, jobs, audit = _load_sources(paths)
        read_spec = normalized["trials"]["read"]
        read_errors: list[str] = []
        read_schedule = _check_schedule(
            schedules, read_spec, require_approval=False, errors=read_errors
        )
        read_receipts = _receipts(schedules, read_spec["schedule_id"])
        if read_receipts:
            read_errors.append("read schedule has approval receipts")
        read_claims = [
            _claim_evidence(
                schedules,
                jobs,
                audit,
                read_spec["schedule_id"],
                claim_id,
                expected_status="executed",
                expected_tool=read_spec["tool"],
                expected_risk="read",
                expected_confirmation=None,
                expected_args_sha256=read_spec["args_sha256"],
                window=window,
                errors=read_errors,
            )
            for claim_id in read_spec["claim_ids"]
        ]
        if read_schedule is not None:
            if not _within_window(read_schedule.get("created"), window):
                read_errors.append("read schedule was not created inside the pilot window")
            if read_schedule.get("runs_used") != len(read_claims):
                read_errors.append("read schedule run budget does not equal its executed claims")
        phases["read"] = {
            "passed": not read_errors,
            "errors": read_errors,
            "schedule_id": read_spec["schedule_id"],
            "tool": read_spec["tool"],
            "cadence": read_spec["cadence"],
            "claims": read_claims,
            "receipt_count": len(read_receipts),
        }

        write_spec = normalized["trials"]["write"]
        write_errors: list[str] = []
        write_schedule = _check_schedule(
            schedules, write_spec, require_approval=True, errors=write_errors
        )
        write_receipts = _receipts(schedules, write_spec["schedule_id"])
        approved_fp = write_schedule.get("approved_fingerprint") if write_schedule else None
        if len(write_receipts) != 1:
            write_errors.append("write pilot requires exactly one approval receipt")
        receipt_summary: dict[str, Any] | None = None
        if write_receipts:
            receipt = write_receipts[-1]
            if receipt.get("kind") != "create":
                write_errors.append("write pilot receipt kind must be create")
            if receipt.get("fingerprint") != approved_fp:
                write_errors.append("write pilot receipt fingerprint mismatch")
            if receipt.get("device_id") != write_spec["device_id"]:
                write_errors.append("write pilot receipt device mismatch")
            if not _within_window(receipt.get("consumed_at"), window):
                write_errors.append("write pilot receipt was not consumed inside the pilot window")
            nonce = receipt.get("nonce")
            if not isinstance(nonce, str) or not nonce:
                write_errors.append("write pilot receipt nonce is missing")
                nonce_hash = None
            else:
                nonce_hash = _sha256(nonce.encode("utf-8"))
            issued = receipt.get("issued_at")
            consumed = receipt.get("consumed_at")
            if (
                isinstance(issued, bool)
                or not isinstance(issued, (int, float))
                or isinstance(consumed, bool)
                or not isinstance(consumed, (int, float))
                or consumed < issued
            ):
                write_errors.append("write pilot receipt timestamps are invalid")
            receipt_summary = {
                "kind": receipt.get("kind"),
                "device_id": receipt.get("device_id"),
                "nonce_sha256": nonce_hash,
                "issued_at": issued,
                "consumed_at": consumed,
                "revision": receipt.get("revision"),
                "fingerprint_sha256": _sha256(str(receipt.get("fingerprint") or "").encode()),
            }

        confirmation = f"schedule:{str(approved_fp)[:12]}" if approved_fp else None
        write_claims = [
            _claim_evidence(
                schedules,
                jobs,
                audit,
                write_spec["schedule_id"],
                claim_id,
                expected_status="executed",
                expected_tool=write_spec["tool"],
                expected_risk="write",
                expected_confirmation=confirmation,
                expected_args_sha256=write_spec["args_sha256"],
                window=window,
                errors=write_errors,
            )
            for claim_id in write_spec["claim_ids"]
        ]
        marker_count: int | None = None
        if write_schedule is not None:
            if not _within_window(write_schedule.get("created"), window):
                write_errors.append("write schedule was not created inside the pilot window")
            args = write_schedule.get("args_value")
            marker = args.get("text") if isinstance(args, dict) else None
            if not isinstance(marker, str) or not marker.strip():
                write_errors.append("write schedule does not contain a non-empty text marker")
            else:
                marker = marker.strip()
                if _sha256(marker.encode("utf-8")) != write_spec["marker_sha256"]:
                    write_errors.append("write marker hash mismatch")
                try:
                    note_text = paths.notes.read_text(encoding="utf-8")
                except OSError:
                    write_errors.append("notes file cannot be read")
                else:
                    marker_count = note_text.count(marker)
                    if marker_count != len(write_claims):
                        write_errors.append(
                            "notes marker count does not equal the executed write claims"
                        )
            if write_schedule.get("runs_used") != len(write_claims):
                write_errors.append("write schedule run budget does not equal its executed claims")
        phases["write"] = {
            "passed": not write_errors,
            "errors": write_errors,
            "schedule_id": write_spec["schedule_id"],
            "tool": write_spec["tool"],
            "cadence": write_spec["cadence"],
            "args_sha256": write_spec["args_sha256"],
            "marker_sha256": write_spec["marker_sha256"],
            "marker_count": marker_count,
            "claims": write_claims,
            "approval_receipt": receipt_summary,
        }

        revoke_spec = normalized["trials"]["revoke"]
        revoke_errors: list[str] = []
        revoke_schedule = _schedule(schedules, revoke_spec["schedule_id"])
        if revoke_schedule is None:
            revoke_errors.append("revocation schedule does not exist")
        elif not _within_window(revoke_schedule.get("created"), window):
            revoke_errors.append("revocation schedule was not created inside the pilot window")
        elif bool(revoke_schedule.get("enabled")):
            revoke_errors.append("revocation schedule is still enabled")
        revoke_claim = _claim_evidence(
            schedules,
            jobs,
            audit,
            revoke_spec["schedule_id"],
            revoke_spec["claim_id"],
            expected_status="released",
            expected_tool=None,
            expected_risk=None,
            expected_confirmation=None,
            expected_args_sha256=None,
            window=window,
            errors=revoke_errors,
        )
        phases["revoke"] = {
            "passed": not revoke_errors,
            "errors": revoke_errors,
            "schedule_id": revoke_spec["schedule_id"],
            "claim": revoke_claim,
        }

        recovery_spec = normalized["trials"]["recovery"]
        recovery_errors: list[str] = []
        recovery_schedule = _schedule(schedules, recovery_spec["schedule_id"])
        if recovery_schedule is None:
            recovery_errors.append("recovery schedule does not exist")
        elif not _within_window(recovery_schedule.get("created"), window):
            recovery_errors.append("recovery schedule was not created inside the pilot window")
        recovery_claim = _claim_evidence(
            schedules,
            jobs,
            audit,
            recovery_spec["schedule_id"],
            recovery_spec["claim_id"],
            expected_status=recovery_spec["expected_status"],
            expected_tool=(recovery_schedule or {}).get("tool"),
            expected_risk="read" if (recovery_schedule or {}).get("approved_fingerprint") is None else "write",
            expected_confirmation=(
                None
                if (recovery_schedule or {}).get("approved_fingerprint") is None
                else f"schedule:{str((recovery_schedule or {}).get('approved_fingerprint'))[:12]}"
            ),
            expected_args_sha256=(
                _json_sha((recovery_schedule or {}).get("args_value"))
                if isinstance((recovery_schedule or {}).get("args_value"), dict)
                else None
            ),
            window=window,
            errors=recovery_errors,
        )
        phases["recovery"] = {
            "passed": not recovery_errors,
            "errors": recovery_errors,
            "schedule_id": recovery_spec["schedule_id"],
            "expected_status": recovery_spec["expected_status"],
            "claim": recovery_claim,
        }

        all_schedule_ids = {
            normalized["trials"][name]["schedule_id"]
            for name in ("read", "write", "revoke", "recovery")
        }
        placeholders = ",".join("?" for _ in all_schedule_ids)
        reserved = schedules.execute(
            f"SELECT claim_id FROM occurrences WHERE schedule_id IN ({placeholders}) "
            "AND status LIKE 'reserved%'",
            tuple(sorted(all_schedule_ids)),
        ).fetchall()
        if reserved:
            errors.append("pilot schedules still have non-terminal reserved occurrences")
    except (PilotError, sqlite3.Error) as exc:
        errors.append(f"data-source validation failed: {type(exc).__name__}: {str(exc)[:300]}")
    finally:
        for conn in (audit, jobs, schedules):
            if conn is not None:
                conn.close()

    for phase_name, phase in phases.items():
        if not phase.get("passed"):
            errors.append(f"phase {phase_name} failed")
    report = {
        "schema": SCHEMA,
        "generated_at": generated,
        "candidate": dict(candidate),
        "pilot_window": {
            "started_at": normalized["window"].get("started_at"),
            "finished_at": normalized["window"].get("finished_at"),
        },
        "runtime": {
            "backend_version": runtime.get("backend_version"),
            "worker_version": runtime.get("worker_version"),
            "worker_code_sha256": runtime.get("worker_code_sha256"),
            "worker_frozen": runtime.get("worker_frozen"),
            "scheduler_configured": runtime.get("scheduler_configured"),
            "scheduler_running": runtime.get("scheduler_running"),
            "scheduler_resources_open": runtime.get("scheduler_resources_open"),
            "scheduler_last_error_present": runtime.get("scheduler_last_error") not in (None, ""),
        },
        "sources": {
            "schedules_db": {"name": paths.schedules.name},
            "jobs_db": {"name": paths.jobs.name},
            "audit_db": {"name": paths.audit.name},
            "notes_file": {"name": paths.notes.name},
        },
        "phases": phases,
        "gate": {
            "passed": not errors,
            "errors": errors,
            "physical_scheduler_pilot_complete": not errors,
            "production_activation": False,
        },
    }
    return report, 0 if not errors else 1


def inventory(paths: DataPaths) -> dict[str, Any]:
    schedules = jobs = audit = None
    try:
        schedules, jobs, audit = _load_sources(paths)
        schedule_rows = schedules.execute(
            "SELECT id, tool, cadence, max_runs, runs_used, enabled, revision "
            "FROM schedules ORDER BY created DESC LIMIT 30"
        ).fetchall()
        occurrence_rows = schedules.execute(
            "SELECT claim_id, schedule_id, status, job_id, created, resolved "
            "FROM occurrences ORDER BY created DESC LIMIT 100"
        ).fetchall()
        return {
            "schema": "kaliv-scheduler-pilot-inventory/v1",
            "schedules": [dict(row) for row in schedule_rows],
            "occurrences": [dict(row) for row in occurrence_rows],
        }
    finally:
        for conn in (audit, jobs, schedules):
            if conn is not None:
                conn.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("eval/scheduler_pilot_manifest.json"))
    parser.add_argument("--report", type=Path, default=Path("validation/scheduler-pilot-latest.json"))
    parser.add_argument("--backend-url", default=os.getenv("MODELRIG_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--worker-url", default=os.getenv("MODELRIG_WORKER_URL", "http://127.0.0.1:8099"))
    parser.add_argument("--schedules-db", type=Path)
    parser.add_argument("--jobs-db", type=Path)
    parser.add_argument("--audit-db", type=Path)
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument("--inventory", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    defaults = default_paths()
    paths = DataPaths(
        schedules=args.schedules_db or defaults.schedules,
        jobs=args.jobs_db or defaults.jobs,
        audit=args.audit_db or defaults.audit,
        notes=args.notes_file or defaults.notes,
    )
    if args.inventory:
        try:
            print(json.dumps(inventory(paths), ensure_ascii=False, indent=2, sort_keys=True))
        except (PilotError, sqlite3.Error) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        return 0

    token = os.getenv("MODELRIG_TOKEN", "").strip()
    if not token:
        print("ERROR: MODELRIG_TOKEN is required in the environment", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    try:
        manifest = _read_json(args.manifest)
        candidate = source_candidate(root)
        runtime = collect_runtime(args.backend_url, args.worker_url, token)
        report, exit_code = collect_evidence(
            manifest,
            candidate=candidate,
            runtime=runtime,
            paths=paths,
        )
        _write_json_atomic(args.report, report)
    except (PilotError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        "PASS: candidate-bound scheduler pilot evidence"
        if exit_code == 0
        else "FAIL: scheduler pilot evidence did not pass"
    )
    print(f"report: {args.report}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
