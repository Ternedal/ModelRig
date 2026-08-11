#!/usr/bin/env python3
"""T-044 status/freshness plus read-only schedule-history contracts.

Run: PYTHONPATH=worker python3 tests/worker_control_center_status.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.control_center_schedule_history import (  # noqa: E402
    SCHEMA as SCHEDULE_HISTORY_SCHEMA,
    build_control_center_schedule_history,
)
from app.control_center_status import (  # noqa: E402
    SCHEMA,
    build_control_center_status,
    collect_control_center_status,
)
from app.paths import peek_resolve  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


NOW = 2_000_000_000.0


def component(ok=True, *, age=1.0, enabled=True, detail=None):
    return {
        "ok": ok,
        "enabled": enabled,
        "observed_at": NOW - age,
        "detail": detail,
    }


def healthy_components(agent3=None):
    return {
        "backend": component(detail="backend reachable"),
        "worker": component(detail="worker reachable"),
        "models": component(detail="models loaded"),
        "agent3": agent3 if agent3 is not None else component(enabled=False),
    }


# A deliberately disabled optional surface is truthful and does not make the
# required local stack unhealthy.
status = build_control_center_status(
    healthy_components(),
    {
        "configured_surface": "disabled",
        "active_surface": "agent_v2",
        "observed_at": NOW - 1,
    },
    now=NOW,
)
check(status["schema"] == SCHEMA, "status uses the versioned v1 schema")
check(status["overall"] == "healthy" and status["green"], "fresh required stack is green")
check(status["components"]["agent3"]["state"] == "disabled", "disabled Agent 3 is explicit")
check(not status["components"]["agent3"]["green"], "disabled is never painted green")
check(status["routing"]["state"] == "disabled", "routing reports intentional disablement")

# ok=true without time evidence is not health evidence.
missing_time = healthy_components()
missing_time["worker"] = {"ok": True, "detail": "looks fine"}
status = build_control_center_status(
    missing_time,
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(status["components"]["worker"]["state"] == "unknown", "missing timestamp fails closed")
check(status["overall"] == "unknown" and not status["green"], "missing required freshness blocks green")

# A once-green but old source is stale, not green.
stale = healthy_components()
stale["backend"] = component(age=31)
status = build_control_center_status(
    stale,
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
    freshness_s=30,
)
check(status["components"]["backend"]["state"] == "stale", "old green becomes stale")
check(status["components"]["backend"]["green"] is False, "stale source is never green")
check(status["summary"]["required_failures"] == ["backend"], "required stale source is named")

# Future observations beyond bounded clock skew are unknown.
future = healthy_components()
future["models"] = {"ok": True, "observed_at": NOW + 6}
status = build_control_center_status(
    future,
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(status["components"]["models"]["reason"] == "observation_from_future", "future timestamp is rejected")
check(status["overall"] == "unknown", "future required source blocks green")

# Enabled but unready Agent 3 is attention, not a full local-stack outage.
status = build_control_center_status(
    healthy_components(agent3=component(ok=False, enabled=True, detail="pilot not ready")),
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(status["components"]["agent3"]["state"] == "unavailable", "enabled unready Agent 3 is unavailable")
check(status["overall"] == "attention", "optional unready surface yields attention")

# Server-selected fallback must say why. Clients may not invent the reason.
status = build_control_center_status(
    healthy_components(agent3=component(ok=False, enabled=True)),
    {
        "configured_surface": "agent3_developer",
        "active_surface": "agent_v2",
        "fallback_reason": "readiness report expired",
        "observed_at": NOW,
    },
    now=NOW,
)
check(status["routing"]["state"] == "fallback", "fresh explained fallback is explicit")
check(status["routing"]["fallback_reason"] == "readiness report expired", "server reason is preserved")
check(status["overall"] == "attention", "fallback is visible as attention")

status = build_control_center_status(
    healthy_components(),
    {
        "configured_surface": "agent3_developer",
        "active_surface": "agent_v2",
        "observed_at": NOW,
    },
    now=NOW,
)
check(status["routing"]["state"] == "unknown", "fallback without reason fails closed")
check(status["routing"]["reason"] == "fallback_reason_missing", "missing reason is machine-readable")
check(not status["green"], "unexplained fallback is never green")

# Provider exceptions expose only their type, not potentially sensitive text.
def broken_provider():
    raise RuntimeError("secret URL and token must not escape")

collected = collect_control_center_status(
    {
        "backend": lambda: component(),
        "worker": broken_provider,
        "models": lambda: component(),
        "agent3": lambda: component(enabled=False),
    },
    lambda: {
        "configured_surface": "disabled",
        "active_surface": "agent_v2",
        "observed_at": NOW,
    },
    now=NOW,
)
worker_detail = collected["components"]["worker"]["detail"] or ""
check("provider_error:RuntimeError" in worker_detail, "provider failure type is visible")
check("secret URL" not in worker_detail and "token" not in worker_detail, "exception message is not leaked")
check(collected["components"]["worker"]["state"] == "unknown", "provider exception is unknown")

# Contract bounds and validation are explicit.
long_detail = "x" * 500
status = build_control_center_status(
    healthy_components(agent3=component(enabled=False, detail=long_detail)),
    {"configured_surface": "disabled", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(len(status["components"]["agent3"]["detail"]) == 240, "operator detail is bounded")

for bad in (0, -1, 3601, float("inf")):
    error = None
    try:
        build_control_center_status(healthy_components(), None, now=NOW, freshness_s=bad)
    except ValueError as exc:
        error = exc
    check(error is not None, f"invalid freshness {bad!r} is rejected")


# ---- Side-effect-free durable scheduler read authority ---------------------

def create_schedule_fixture(path: Path, *, status_value: str = "executed", job_id: str | None = "job000000001"):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schedules (id TEXT PRIMARY KEY, tool TEXT NOT NULL);
        CREATE TABLE occurrences (
            claim_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            occurrence_due_at REAL NOT NULL,
            status TEXT NOT NULL,
            created REAL NOT NULL,
            resolved REAL,
            job_id TEXT
        );
        """
    )
    connection.execute("INSERT INTO schedules (id, tool) VALUES (?, ?)", ("0a1b2c3d4e5f", "note_append"))
    connection.execute(
        "INSERT INTO occurrences VALUES (?,?,?,?,?,?,?)",
        (
            "0123456789abcdef0123456789abcdef",
            "0a1b2c3d4e5f",
            NOW - 60,
            status_value,
            NOW - 55,
            None if status_value in {"reserved", "reserved_noslot"} else NOW - 50,
            job_id,
        ),
    )
    connection.commit()
    connection.close()


def create_jobs_fixture(path: Path, *, status_value: str = "completed"):
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE jobs (
               id TEXT PRIMARY KEY,
               kind TEXT NOT NULL,
               status TEXT NOT NULL,
               detail TEXT NOT NULL DEFAULT '',
               progress_completed INTEGER NOT NULL DEFAULT 0,
               progress_total INTEGER NOT NULL DEFAULT 0,
               cancel_requested INTEGER NOT NULL DEFAULT 0,
               created REAL NOT NULL,
               updated REAL NOT NULL)"""
    )
    values = (
        "job000000001",
        "schedule",
        status_value,
        "PRIVATE ARGUMENT MUST NOT LEAK",
        1,
        1,
        NOW - 54,
        NOW - 50,
    )
    placeholders = ",".join("?" for _ in values)
    connection.execute(
        "INSERT INTO jobs (id,kind,status,detail,progress_completed,progress_total,created,updated) "
        f"VALUES ({placeholders})",
        values,
    )
    connection.commit()
    connection.close()


# Merely locating or reading absent state must not create the data root.
with tempfile.TemporaryDirectory() as temp:
    missing_root = Path(temp) / "never-created"
    old_root = os.environ.get("KALIV_DATA_DIR")
    try:
        os.environ["KALIV_DATA_DIR"] = str(missing_root)
        resolved = peek_resolve("./kaliv-schedules.db", env="KALIV_SCHEDULES_DB")
        check(resolved == str(missing_root / "kaliv-schedules.db"), "peek path matches writer location")
        check(not missing_root.exists(), "peek path creates no data directory")
        history = build_control_center_schedule_history(clock=lambda: NOW)
        check(history["schema"] == SCHEDULE_HISTORY_SCHEMA, "history uses versioned schema")
        check(history["sources"]["occurrence_ledger"]["state"] == "unavailable", "missing ledger is explicit")
        check(history["sources"]["jobs"]["state"] == "not_required", "jobs DB is untouched without job refs")
        check(history["items"] == [], "missing ledger never fabricates occurrences")
        check(not missing_root.exists(), "Control Center GET path creates zero files or directories")
    finally:
        if old_root is None:
            os.environ.pop("KALIV_DATA_DIR", None)
        else:
            os.environ["KALIV_DATA_DIR"] = old_root

# A real ledger is read byte-for-byte without writer constructors or migrations.
with tempfile.TemporaryDirectory() as temp:
    schedule_db = Path(temp) / "schedules.db"
    jobs_db = Path(temp) / "jobs.db"
    create_schedule_fixture(schedule_db)
    create_jobs_fixture(jobs_db)
    schedule_before = schedule_db.read_bytes()
    jobs_before = jobs_db.read_bytes()
    history = build_control_center_schedule_history(
        clock=lambda: NOW,
        schedule_db_path=str(schedule_db),
        jobs_db_path=str(jobs_db),
    )
    check(history["production_activation"] is False, "history cannot authorize production")
    check(history["sources"]["occurrence_ledger"]["state"] == "ready", "ledger source is ready")
    check(history["sources"]["jobs"]["state"] == "ready", "job source is ready")
    item = history["items"][0]
    check(item["occurrence_status"] == "executed", "durable executed status is preserved")
    check(item["terminal_outcome"] == "executed" and item["in_flight"] is False, "ledger owns terminal outcome")
    check(item["tool"] == "note_append" and item["schedule_id"] == "0a1b2c3d4e5f", "safe schedule identity is joined")
    check(item["job"]["status"] == "completed", "job state is independently visible")
    serialized = str(history)
    check("PRIVATE ARGUMENT" not in serialized and "detail" not in item["job"], "job detail/private payload is not exposed")
    check(schedule_db.read_bytes() == schedule_before, "schedule DB remains byte-identical after read")
    check(jobs_db.read_bytes() == jobs_before, "job DB remains byte-identical after read")

# Unresolved claims remain in-flight and never become synthetic terminal success.
with tempfile.TemporaryDirectory() as temp:
    schedule_db = Path(temp) / "schedules.db"
    create_schedule_fixture(schedule_db, status_value="reserved", job_id=None)
    history = build_control_center_schedule_history(
        clock=lambda: NOW,
        schedule_db_path=str(schedule_db),
        jobs_db_path=str(Path(temp) / "missing-jobs.db"),
    )
    item = history["items"][0]
    check(item["in_flight"] is True and item["terminal_outcome"] is None, "reserved occurrence stays in-flight")
    check(history["sources"]["jobs"]["state"] == "not_required", "unbound occurrence does not open jobs DB")

# Unknown persisted enum values are visible but fail closed to unknown outcome.
with tempfile.TemporaryDirectory() as temp:
    schedule_db = Path(temp) / "schedules.db"
    create_schedule_fixture(schedule_db, status_value="future_success", job_id=None)
    history = build_control_center_schedule_history(
        clock=lambda: NOW,
        schedule_db_path=str(schedule_db),
        jobs_db_path=str(Path(temp) / "missing-jobs.db"),
    )
    item = history["items"][0]
    check(item["occurrence_status"] == "unknown_schema_value", "unknown occurrence enum is not trusted")
    check(item["terminal_outcome"] == "unknown" and item["in_flight"] is None, "unknown enum keeps in-flight unknown")

# An older DB that lacks job_id is not migrated by a read; it is unavailable.
with tempfile.TemporaryDirectory() as temp:
    old_db = Path(temp) / "old.db"
    connection = sqlite3.connect(old_db)
    connection.executescript(
        """
        CREATE TABLE schedules (id TEXT PRIMARY KEY, tool TEXT NOT NULL);
        CREATE TABLE occurrences (
            claim_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            occurrence_due_at REAL NOT NULL,
            status TEXT NOT NULL,
            created REAL NOT NULL,
            resolved REAL
        );
        """
    )
    connection.commit()
    connection.close()
    before = old_db.read_bytes()
    history = build_control_center_schedule_history(
        clock=lambda: NOW,
        schedule_db_path=str(old_db),
        jobs_db_path=str(Path(temp) / "jobs.db"),
    )
    check(history["sources"]["occurrence_ledger"]["reason"] == "occurrence_schema_missing", "old schema fails closed")
    check(old_db.read_bytes() == before, "Control Center does not migrate old schema")

print(f"\n===== CONTROL CENTER STATUS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
