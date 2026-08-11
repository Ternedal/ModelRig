"""Side-effect-free T-044 schedule occurrence/job read projection.

The scheduler and JobStore constructors are intentionally NOT used here:
opening either writer abstraction can create/migrate/reconcile persistent state.
Control Center is an observation surface, so it computes the existing paths
without mkdir and opens SQLite in ``mode=ro`` only.

The occurrence ledger is the durable execution authority. JobStore is a separate
persistence domain with no cross-database transaction, so its status is exposed
as an independently observed fact and never allowed to rewrite an occurrence
outcome. A client can therefore see a transient cross-store window without the
server inventing atomicity that does not exist.
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from . import paths

SCHEMA = "kaliv-control-center-schedule-history/v1"
_OCCURRENCE_STATUSES = {
    "reserved",
    "reserved_noslot",
    "executed",
    "released",
    "abandoned",
    "unknown",
}
_JOB_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
}
_TERMINAL_OUTCOME = {
    "executed": "executed",
    "released": "not_run",
    "abandoned": "abandoned",
    "unknown": "unknown",
}


def _db_uri(path: str) -> str:
    # Path.as_uri quotes spaces/#/? correctly. abspath preserves the historical
    # meaning of an explicitly configured relative DB path without creating it.
    return Path(os.path.abspath(path)).as_uri() + "?mode=ro"


def _open_readonly(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _source(state: str, reason: str | None = None) -> dict[str, Any]:
    return {"state": state, "reason": reason}


def _strict_nonnegative_int(value: Any) -> int:
    if type(value) is not int or value < 0:  # bool and SQLite REAL both fail.
        raise ValueError("not a non-negative integer")
    return value


def _strict_finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("not finite")
    return result


def _schedule_path() -> str:
    return paths.peek_resolve("./kaliv-schedules.db", env="KALIV_SCHEDULES_DB")


def _jobs_path() -> str:
    return paths.peek_resolve("./modelrig-jobs.db", env="MODELRIG_JOBS_DB")


def _read_occurrences(path: str, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not os.path.isfile(path):
        return _source("unavailable", "database_missing"), []
    try:
        connection = _open_readonly(path)
    except sqlite3.Error:
        return _source("unavailable", "open_failed"), []
    try:
        occurrence_columns = _columns(connection, "occurrences")
        schedule_columns = _columns(connection, "schedules")
        required_occurrence = {
            "claim_id",
            "schedule_id",
            "occurrence_due_at",
            "status",
            "created",
            "resolved",
            "job_id",
        }
        if not required_occurrence.issubset(occurrence_columns):
            return _source("unavailable", "occurrence_schema_missing"), []
        if not {"id", "tool"}.issubset(schedule_columns):
            return _source("unavailable", "schedule_schema_missing"), []

        rows = connection.execute(
            "SELECT o.claim_id, o.schedule_id, o.occurrence_due_at, o.status, "
            "o.created, o.resolved, o.job_id, s.tool "
            "FROM occurrences o LEFT JOIN schedules s ON s.id=o.schedule_id "
            "ORDER BY o.occurrence_due_at DESC, o.created DESC, o.claim_id DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return _source("unavailable", "query_failed"), []
    finally:
        connection.close()

    result: list[dict[str, Any]] = []
    try:
        for row in rows:
            status = str(row["status"])
            if status not in _OCCURRENCE_STATUSES:
                # An unknown future enum could be either pending or terminal.
                # Do not lie in either direction: in_flight is explicitly unknown.
                normalized_status = "unknown_schema_value"
                terminal_outcome = "unknown"
                in_flight = None
            else:
                normalized_status = status
                terminal_outcome = _TERMINAL_OUTCOME.get(status)
                in_flight = status in {"reserved", "reserved_noslot"}
            result.append(
                {
                    "occurrence_id": str(row["claim_id"]),
                    "schedule_id": str(row["schedule_id"]),
                    "tool": str(row["tool"]) if row["tool"] is not None else None,
                    "due_at": _strict_finite_number(row["occurrence_due_at"]),
                    "occurrence_status": normalized_status,
                    "in_flight": in_flight,
                    "terminal_outcome": terminal_outcome,
                    "created_at": _strict_finite_number(row["created"]),
                    "resolved_at": (
                        _strict_finite_number(row["resolved"])
                        if row["resolved"] is not None
                        else None
                    ),
                    "job_id": str(row["job_id"]) if row["job_id"] is not None else None,
                }
            )
    except (TypeError, ValueError):
        return _source("unavailable", "occurrence_value_invalid"), []
    return _source("ready"), result


def _read_jobs(path: str, job_ids: list[str]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not job_ids:
        # There is no need to touch the jobs DB when no occurrence references it.
        return _source("not_required"), {}
    if not os.path.isfile(path):
        return _source("unavailable", "database_missing"), {}
    try:
        connection = _open_readonly(path)
    except sqlite3.Error:
        return _source("unavailable", "open_failed"), {}
    try:
        columns = _columns(connection, "jobs")
        required = {
            "id",
            "kind",
            "status",
            "progress_completed",
            "progress_total",
            "created",
            "updated",
        }
        if not required.issubset(columns):
            return _source("unavailable", "job_schema_missing"), {}
        placeholders = ",".join("?" for _ in job_ids)
        rows = connection.execute(
            "SELECT id, kind, status, progress_completed, progress_total, "
            f"created, updated FROM jobs WHERE id IN ({placeholders})",
            tuple(job_ids),
        ).fetchall()
    except sqlite3.Error:
        return _source("unavailable", "query_failed"), {}
    finally:
        connection.close()

    jobs: dict[str, dict[str, Any]] = {}
    try:
        for row in rows:
            status = str(row["status"])
            jobs[str(row["id"])] = {
                "status": status if status in _JOB_STATUSES else "unknown_schema_value",
                "kind": str(row["kind"]),
                "progress_completed": _strict_nonnegative_int(row["progress_completed"]),
                "progress_total": _strict_nonnegative_int(row["progress_total"]),
                "created_at": _strict_finite_number(row["created"]),
                "updated_at": _strict_finite_number(row["updated"]),
            }
    except (TypeError, ValueError):
        return _source("unavailable", "job_value_invalid"), {}
    return _source("ready"), jobs


def build_control_center_schedule_history(
    *,
    limit: int = 50,
    clock: Callable[[], float] = time.time,
    schedule_db_path: str | None = None,
    jobs_db_path: str | None = None,
) -> dict[str, Any]:
    """Return recent durable schedule execution facts without mutating storage."""
    bounded_limit = max(1, min(int(limit), 100))
    schedule_path = schedule_db_path or _schedule_path()
    jobs_path = jobs_db_path or _jobs_path()

    schedule_source, occurrences = _read_occurrences(schedule_path, bounded_limit)
    job_ids = sorted({row["job_id"] for row in occurrences if row["job_id"]})
    jobs_source, jobs = _read_jobs(jobs_path, job_ids)

    items: list[dict[str, Any]] = []
    for occurrence in occurrences:
        row = dict(occurrence)
        job_id = row.get("job_id")
        row["job"] = jobs.get(job_id) if job_id else None
        items.append(row)

    return {
        "schema": SCHEMA,
        "generated_at": _strict_finite_number(clock()),
        "sources": {
            "occurrence_ledger": schedule_source,
            "jobs": jobs_source,
        },
        "items": items,
        "production_activation": False,
    }
