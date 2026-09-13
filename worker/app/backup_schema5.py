"""Kaliv backup & restore.

Bundles persistent rig state that cannot be rebuilt from the repo into one
verified archive. The archive contains data, never installation artifacts or
operator secrets.

Backup schema history:

* schema 1: original V7 inventory;
* schema 2: expanded 2.x inventory;
* schema 3: separate Agent 3 execution-progress authority;
* schema 4: snapshot-bound Agent 3 run/progress authority with failure-atomic
  paired restore semantics;
* schema 5: persistent live-pair identity plus semantic run/watermark validation
  before snapshot binding.

The Agent 3 run database and its execution-progress sidecar are one authority
unit. A live pair carries one persistent pair id in both SQLite stores. New
backups refuse non-empty unbound state, mismatched pair ids and progress rows
that contradict the run payload before taking SQLite snapshots. The snapshots
retain the live pair identity, receive one additional random snapshot id, and
only that doubly-bound pair is accepted by schema-5 verification.

On restore, only backup-only snapshot metadata is removed from staged copies;
the persistent pair identity remains. Publication uses the authoritative run-db
path itself as a durable restore fence: it is atomically replaced by a
deliberately non-SQLite marker before the progress DB is published and is
replaced by the staged run DB only after the progress DB is in place. If restore
is interrupted at either replacement, Agent 3 startup cannot validate/open the
fenced authority and fails closed until restore is retried.

WHAT IS NOT INCLUDED: model weights (re-pullable via Ollama), Piper voices,
repository files, modelrig.env, API keys, approval secrets or other credentials.
Those are installation/configuration inputs, not portable data archives.

Usage:
    python -m worker.app.backup create  [--out DIR]
    python -m worker.app.backup restore ARCHIVE.tar.gz [--force]
    python -m worker.app.backup verify  ARCHIVE.tar.gz
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

BACKUP_SCHEMA = 5
SUPPORTED_BACKUP_SCHEMAS = frozenset({1, 2, 3, 4, BACKUP_SCHEMA})
AGENT3_RUNS_KEY = "agent3-runs.db"
AGENT3_EXECUTION_PROGRESS_KEY = "agent3-execution-progress.db"
AGENT3_SNAPSHOT_MANIFEST_KEY = "agent3_authority_snapshot_id"
AGENT3_PAIR_MANIFEST_KEY = "agent3_authority_pair_id"
_SNAPSHOT_TABLE = "kaliv_backup_snapshot"
_SNAPSHOT_TABLE_SQL = (
    "CREATE TABLE kaliv_backup_snapshot ("
    "snapshot_id TEXT NOT NULL, store_role TEXT NOT NULL)"
)
_RESTORE_FENCE_PREFIX = b"KALIV_AGENT3_PAIRED_RESTORE_IN_PROGRESS\n"

# Resolve paths exactly like the worker. Relative defaults are anchored under
# the stable Kaliv data root; explicit env overrides continue to win.
from . import paths as _paths  # noqa: E402
from . import tools as _tools  # noqa: E402
from .agent3.authority_pair import (  # noqa: E402
    PAIR_TABLE as _PAIR_TABLE,
    PAIR_TABLE_SQL as _PAIR_TABLE_SQL,
    PROGRESS_ROLE as _AGENT3_PROGRESS_ROLE,
    PROGRESS_TABLE_SQL as _PROGRESS_TABLE_SQL,
    RUNS_ROLE as _AGENT3_RUNS_ROLE,
    binding_problem_path as _pair_binding_problem_path,
    read_binding_path as _read_pair_binding_path,
    uuid_problem as _pair_id_problem,
)


@dataclass
class Item:
    key: str
    path: str
    kind: str
    required: bool


def _resolved(default: str, env: str) -> str:
    return _paths.resolve(default, env=env)


def _backend_data() -> str:
    value = os.getenv("MODELRIG_DATA")
    if value:
        return value
    return _paths.resolve("./modelrig-data.json")


def items() -> list[Item]:
    """Return the authoritative portable-state inventory."""
    files = [
        ("rag.db", "./modelrig-rag.db", "MODELRIG_DB"),
        ("audit.db", "./kaliv-audit.db", "KALIV_AUDIT_DB"),
        ("tools-state.json", "./kaliv-tools-state.json", "KALIV_TOOLS_STATE"),
        ("jobs.db", "./modelrig-jobs.db", "MODELRIG_JOBS_DB"),
        ("schedules.db", "./kaliv-schedules.db", "KALIV_SCHEDULES_DB"),
        (AGENT3_RUNS_KEY, "./kaliv-agent3.db", "KALIV_AGENT3_DB"),
        (
            "agent3-read-reviews.db",
            "./kaliv-agent3-read-reviews.db",
            "KALIV_AGENT3_REVIEW_DB",
        ),
        ("agent3-replans.db", "./kaliv-agent3-replans.db", "KALIV_AGENT3_REPLAN_DB"),
        (
            "agent3-replan-previews.db",
            "./kaliv-agent3-replan-previews.db",
            "KALIV_AGENT3_REPLAN_PREVIEW_DB",
        ),
        ("agent3-memory.db", "./kaliv-agent3-memory.db", "KALIV_AGENT3_MEMORY_DB"),
        (
            "agent3-memory-grants.db",
            "./kaliv-agent3-memory-grants.db",
            "KALIV_AGENT3_MEMORY_GRANT_DB",
        ),
        ("agent3-plans.db", "./kaliv-agent3-plans.db", "KALIV_AGENT3_PLAN_DB"),
        (
            "agent3-task-plans.db",
            "./kaliv-agent3-task-plans.db",
            "KALIV_AGENT3_TASK_PLAN_DB",
        ),
        (
            "agent3-approvals.db",
            "./kaliv-agent3-approvals.db",
            "KALIV_AGENT3_APPROVAL_DB",
        ),
        (
            "home-rig-grants.db",
            "./kaliv-home-rig-grants.db",
            "KALIV_HOME_RIG_GRANTS_DB",
        ),
        (
            "home-rig-audit.db",
            "./kaliv-home-rig-audit.db",
            "KALIV_HOME_RIG_AUDIT_DB",
        ),
        (
            "data-sharing.db",
            "./kaliv-data-sharing.db",
            "KALIV_DATA_SHARING_DB",
        ),
    ]
    out = [
        Item(key, _resolved(default, env), "file", required=False)
        for key, default, env in files
    ]
    out.insert(1, Item("data.json", _backend_data(), "file", required=False))
    runs_index = next(i for i, item in enumerate(out) if item.key == AGENT3_RUNS_KEY)
    out.insert(
        runs_index + 1,
        Item(
            AGENT3_EXECUTION_PROGRESS_KEY,
            f"{out[runs_index].path}.execution-progress",
            "file",
            required=False,
        ),
    )
    out.append(Item("notes", _tools.tools_dir(), "dir", required=False))
    return out


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _walk(path: str) -> list[str]:
    found: list[str] = []
    for root, _dirs, files in os.walk(path):
        for filename in sorted(files):
            found.append(os.path.join(root, filename))
    return sorted(found)


def _readonly_sqlite(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _normalize_sql(value: object) -> Optional[str]:
    if value is None:
        return None
    return " ".join(str(value).split())


def _sqlite_table_problem(
    path: str,
    *,
    table: str,
    required: dict[str, tuple[str, int | None, int | None]],
) -> Optional[str]:
    try:
        con = _readonly_sqlite(path)
    except sqlite3.Error as exc:
        return f"cannot open SQLite database: {exc}"
    try:
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                return (
                    "SQLite integrity_check failed: "
                    + (str(integrity[0]) if integrity else "no result")
                )
            rows = list(con.execute(f"PRAGMA table_info({table})"))
        except sqlite3.Error as exc:
            return f"cannot inspect SQLite authority: {exc}"
        if not rows:
            return f"required table {table} is missing"
        columns = {str(row[1]): row for row in rows}
        for name, (want_type, want_notnull, want_pk) in required.items():
            row = columns.get(name)
            if row is None:
                return f"required column {table}.{name} is missing"
            got_type = str(row[2]).upper()
            if got_type != want_type:
                return f"column {table}.{name} has type {got_type!r}, expected {want_type}"
            if want_notnull is not None and int(row[3]) != want_notnull:
                return f"column {table}.{name} has invalid NOT NULL authority"
            if want_pk is not None and int(row[5]) != want_pk:
                return f"column {table}.{name} has invalid primary-key authority"
        return None
    finally:
        con.close()


def _snapshot_id_problem(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return "Agent 3 snapshot id is missing or not a string"
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return "Agent 3 snapshot id is not a UUID"
    if str(parsed) != value.lower():
        return "Agent 3 snapshot id is not canonical"
    return None


def _snapshot_binding_problem_path(
    path: str,
    *,
    snapshot_id: str,
    role: str,
) -> Optional[str]:
    try:
        con = _readonly_sqlite(path)
    except sqlite3.Error as exc:
        return f"cannot open SQLite snapshot authority: {exc}"
    try:
        try:
            row = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (_SNAPSHOT_TABLE,),
            ).fetchone()
            columns = list(con.execute(f"PRAGMA table_xinfo({_SNAPSHOT_TABLE})"))
            values = list(
                con.execute(
                    f"SELECT snapshot_id,store_role FROM {_SNAPSHOT_TABLE}"
                )
            )
        except sqlite3.Error as exc:
            return f"cannot inspect Agent 3 snapshot binding: {exc}"
        if row is None or _normalize_sql(row[0]) != _SNAPSHOT_TABLE_SQL:
            return "Agent 3 snapshot binding table is missing or non-canonical"
        actual_columns = [
            (str(col[1]), str(col[2]).upper(), int(col[3]), int(col[5]), int(col[6]))
            for col in columns
        ]
        expected_columns = [
            ("snapshot_id", "TEXT", 1, 0, 0),
            ("store_role", "TEXT", 1, 0, 0),
        ]
        if actual_columns != expected_columns:
            return "Agent 3 snapshot binding columns are non-canonical"
        if values != [(snapshot_id, role)]:
            return (
                "Agent 3 snapshot binding does not match the manifest generation "
                f"and role {role!r}"
            )
        return None
    finally:
        con.close()


def _execution_progress_problem_path(
    path: str,
    *,
    snapshot_id: Optional[str] = None,
    pair_id: Optional[str] = None,
) -> Optional[str]:
    problem = _sqlite_table_problem(
        path,
        table="agent_execution_starts",
        required={
            "run_id": ("TEXT", 1, 1),
            "step_index": ("INTEGER", 1, 2),
            "step_sha256": ("TEXT", 1, 3),
            "started_at": ("REAL", 1, 0),
        },
    )
    if problem:
        return problem
    try:
        con = _readonly_sqlite(path)
    except sqlite3.Error as exc:
        return f"cannot open SQLite database: {exc}"
    try:
        try:
            schema_rows = list(
                con.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master "
                    "ORDER BY type,name,tbl_name"
                )
            )
            column_rows = list(con.execute("PRAGMA table_xinfo(agent_execution_starts)"))
        except sqlite3.Error as exc:
            return f"cannot inspect SQLite execution-authority schema: {exc}"

        expected_schema: list[tuple[str, str, str, Optional[str]]] = [
            (
                "index",
                "sqlite_autoindex_agent_execution_starts_1",
                "agent_execution_starts",
                None,
            ),
            (
                "table",
                "agent_execution_starts",
                "agent_execution_starts",
                _PROGRESS_TABLE_SQL,
            ),
        ]
        if pair_id is not None:
            expected_schema.append(("table", _PAIR_TABLE, _PAIR_TABLE, _PAIR_TABLE_SQL))
        if snapshot_id is not None:
            expected_schema.append(
                ("table", _SNAPSHOT_TABLE, _SNAPSHOT_TABLE, _SNAPSHOT_TABLE_SQL)
            )
        normalized_schema = [
            (str(row[0]), str(row[1]), str(row[2]), _normalize_sql(row[3]))
            for row in schema_rows
        ]
        if normalized_schema != expected_schema:
            rendered = [
                f"{row[0]}:{row[1]}->{row[2]} sql={row[3]!r}"
                for row in normalized_schema
            ]
            return (
                "execution-progress database does not match the canonical authority schema: "
                + (", ".join(rendered) if rendered else "none")
            )

        expected_columns = [
            ("run_id", "TEXT", 1, 1, 0),
            ("step_index", "INTEGER", 1, 2, 0),
            ("step_sha256", "TEXT", 1, 3, 0),
            ("started_at", "REAL", 1, 0, 0),
        ]
        actual_columns = [
            (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]), int(row[6]))
            for row in column_rows
        ]
        if actual_columns != expected_columns:
            return "execution-progress table does not match the exact authority column schema"
    finally:
        con.close()

    if pair_id is not None:
        pair_problem = _pair_binding_problem_path(
            path,
            pair_id=pair_id,
            role=_AGENT3_PROGRESS_ROLE,
        )
        if pair_problem:
            return pair_problem
    if snapshot_id is not None:
        return _snapshot_binding_problem_path(
            path,
            snapshot_id=snapshot_id,
            role=_AGENT3_PROGRESS_ROLE,
        )
    return None


def _agent3_runs_row_count_path(
    path: str,
    *,
    snapshot_id: Optional[str] = None,
    pair_id: Optional[str] = None,
) -> tuple[Optional[int], Optional[str]]:
    problem = _sqlite_table_problem(
        path,
        table="agent_runs",
        required={
            "id": ("TEXT", None, 1),
            "state": ("TEXT", 1, 0),
            "payload": ("TEXT", 1, 0),
            "updated_at": ("REAL", 1, 0),
        },
    )
    if problem:
        return None, problem
    if pair_id is not None:
        pair_problem = _pair_binding_problem_path(
            path,
            pair_id=pair_id,
            role=_AGENT3_RUNS_ROLE,
        )
        if pair_problem:
            return None, pair_problem
    if snapshot_id is not None:
        binding_problem = _snapshot_binding_problem_path(
            path,
            snapshot_id=snapshot_id,
            role=_AGENT3_RUNS_ROLE,
        )
        if binding_problem:
            return None, binding_problem
    con = _readonly_sqlite(path)
    try:
        try:
            row = con.execute("SELECT COUNT(*) FROM agent_runs").fetchone()
        except sqlite3.Error as exc:
            return None, f"cannot count Agent 3 runs: {exc}"
        if row is None:
            return None, "cannot count Agent 3 runs: no result"
        return int(row[0]), None
    finally:
        con.close()


def _execution_progress_row_count_path(path: str) -> tuple[Optional[int], Optional[str]]:
    con: Optional[sqlite3.Connection] = None
    try:
        con = _readonly_sqlite(path)
        row = con.execute("SELECT COUNT(*) FROM agent_execution_starts").fetchone()
        if row is None:
            return None, "cannot count execution-progress rows: no result"
        return int(row[0]), None
    except sqlite3.Error as exc:
        return None, f"cannot count execution-progress rows: {exc}"
    finally:
        if con is not None:
            con.close()


def _execution_step_sha256(step: dict) -> str:
    payload = {
        "tool": step.get("tool"),
        "args": step.get("args", {}),
        "risk": step.get("risk"),
        "sensitivity": step.get("sensitivity", "operational"),
        "egress": step.get("egress", "local"),
        "origin": step.get("origin", "local"),
        "conversation_id": step.get("conversation_id"),
        "idempotent": bool(step.get("idempotent", False)),
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _agent3_pair_semantic_problem_paths(
    runs_path: str,
    progress_path: str,
) -> Optional[str]:
    """Reject a progress ledger that is unsafe relative to the run snapshot."""
    try:
        runs_con = _readonly_sqlite(runs_path)
        progress_con = _readonly_sqlite(progress_path)
    except sqlite3.Error as exc:
        return f"cannot open Agent 3 pair for semantic validation: {exc}"
    try:
        try:
            run_rows = list(runs_con.execute("SELECT id,state,payload FROM agent_runs"))
            progress_rows = list(
                progress_con.execute(
                    "SELECT run_id,step_index,step_sha256 FROM agent_execution_starts "
                    "ORDER BY run_id,step_index,step_sha256"
                )
            )
        except sqlite3.Error as exc:
            return f"cannot inspect Agent 3 pair semantics: {exc}"

        runs: dict[str, dict] = {}
        for run_id, state, raw_payload in run_rows:
            try:
                payload = json.loads(raw_payload)
            except (json.JSONDecodeError, TypeError) as exc:
                return f"run {run_id!r} has invalid JSON payload: {exc}"
            if not isinstance(payload, dict):
                return f"run {run_id!r} payload is not an object"
            if payload.get("id") not in {None, run_id}:
                return f"run {run_id!r} payload id does not match its authority row"
            if payload.get("state") not in {None, state}:
                return f"run {run_id!r} payload state does not match its authority row"
            if not isinstance(payload.get("steps"), list):
                return f"run {run_id!r} payload has no valid steps list"
            try:
                int(payload.get("current_step", 0))
            except (TypeError, ValueError):
                return f"run {run_id!r} has invalid current_step authority"
            runs[str(run_id)] = payload

        for run_id, step_index, expected_sha in progress_rows:
            payload = runs.get(str(run_id))
            if payload is None:
                return f"execution watermark references missing run {run_id!r}"
            steps = payload["steps"]
            try:
                index = int(step_index)
            except (TypeError, ValueError):
                return f"execution watermark for run {run_id!r} has invalid step index"
            if index < 0 or index >= len(steps):
                return f"execution watermark for run {run_id!r} points outside the run plan"
            step = steps[index]
            if not isinstance(step, dict):
                return f"run {run_id!r} step {index} is not an object"
            if _execution_step_sha256(step) != str(expected_sha):
                return f"execution watermark digest does not match run {run_id!r} step {index}"
            current_step = int(payload.get("current_step", 0))
            if current_step < index:
                return f"execution watermark is ahead of run {run_id!r} current_step"
            if current_step == index:
                step_state = str(step.get("state", "pending"))
                if step_state in {"approved", "waiting_confirmation"}:
                    return (
                        f"execution watermark contradicts pre-execution state for run {run_id!r} "
                        f"step {index}"
                    )
                if step_state == "pending" and not bool(step.get("idempotent", False)):
                    return (
                        f"execution watermark would make non-idempotent pending run {run_id!r} "
                        f"step {index} replayable"
                    )
        return None
    finally:
        runs_con.close()
        progress_con.close()


def _live_pair_id_problem(
    runs_path: str,
    progress_path: str,
) -> tuple[Optional[str], Optional[str]]:
    runs_binding, runs_problem = _read_pair_binding_path(runs_path)
    progress_binding, progress_problem = _read_pair_binding_path(progress_path)
    if runs_problem or progress_problem:
        return None, str(runs_problem or progress_problem)
    if runs_binding is None or progress_binding is None:
        return None, "persistent Agent 3 live-pair binding is missing from one or both stores"
    run_pair_id, run_role = runs_binding
    progress_pair_id, progress_role = progress_binding
    if run_role != _AGENT3_RUNS_ROLE or progress_role != _AGENT3_PROGRESS_ROLE:
        return None, "persistent Agent 3 live-pair roles do not match their stores"
    if run_pair_id != progress_pair_id:
        return None, "Agent 3 run/progress stores belong to different persistent live pairs"
    return run_pair_id, None


_T = TypeVar("_T")


def _with_temp_sqlite(data: bytes, inspector: Callable[[str], _T]) -> _T:
    fd, path = tempfile.mkstemp(prefix="kaliv-backup-sqlite-", suffix=".db")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(data)
        return inspector(path)
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _execution_progress_problem_bytes(
    data: bytes,
    *,
    snapshot_id: Optional[str] = None,
    pair_id: Optional[str] = None,
) -> Optional[str]:
    return _with_temp_sqlite(
        data,
        lambda path: _execution_progress_problem_path(
            path, snapshot_id=snapshot_id, pair_id=pair_id
        ),
    )


def _execution_progress_row_count_bytes(data: bytes) -> tuple[Optional[int], Optional[str]]:
    return _with_temp_sqlite(data, _execution_progress_row_count_path)


def _agent3_runs_row_count_bytes(
    data: bytes,
    *,
    snapshot_id: Optional[str] = None,
    pair_id: Optional[str] = None,
) -> tuple[Optional[int], Optional[str]]:
    return _with_temp_sqlite(
        data,
        lambda path: _agent3_runs_row_count_path(
            path, snapshot_id=snapshot_id, pair_id=pair_id
        ),
    )


def _pair_semantic_problem_bytes(run_data: bytes, progress_data: bytes) -> Optional[str]:
    fd_run, run_path = tempfile.mkstemp(prefix="kaliv-backup-runs-", suffix=".db")
    fd_progress, progress_path = tempfile.mkstemp(
        prefix="kaliv-backup-progress-", suffix=".db"
    )
    os.close(fd_run)
    os.close(fd_progress)
    try:
        with open(run_path, "wb") as f:
            f.write(run_data)
        with open(progress_path, "wb") as f:
            f.write(progress_data)
        return _agent3_pair_semantic_problem_paths(run_path, progress_path)
    finally:
        for path in (run_path, progress_path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def _member_bytes(tar: tarfile.TarFile, name: str) -> Optional[bytes]:
    try:
        f = tar.extractfile(name)
    except KeyError:
        return None
    if f is None:
        return None
    return f.read()


def _member_sha(tar: tarfile.TarFile, name: str) -> Optional[str]:
    data = _member_bytes(tar, name)
    return None if data is None else _sha256_bytes(data)


def _sqlite_snapshot(source: str, destination: str) -> None:
    src = _readonly_sqlite(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


def _add_snapshot_binding(path: str, *, snapshot_id: str, role: str) -> None:
    con = sqlite3.connect(path)
    try:
        existing = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (_SNAPSHOT_TABLE,)
        ).fetchone()
        if existing is not None:
            raise ValueError(
                f"refusing to overwrite pre-existing {_SNAPSHOT_TABLE} in {role} snapshot"
            )
        con.execute(_SNAPSHOT_TABLE_SQL)
        con.execute(
            f"INSERT INTO {_SNAPSHOT_TABLE}(snapshot_id,store_role) VALUES(?,?)",
            (snapshot_id, role),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _strip_snapshot_binding(path: str, *, snapshot_id: str, role: str) -> None:
    problem = _snapshot_binding_problem_path(
        path, snapshot_id=snapshot_id, role=role
    )
    if problem:
        raise ValueError("invalid staged Agent 3 snapshot binding: " + problem)
    con = sqlite3.connect(path)
    try:
        con.execute(f"DROP TABLE {_SNAPSHOT_TABLE}")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _agent3_authority_problem(files: dict, *, runs_have_rows: bool) -> Optional[str]:
    has_runs = AGENT3_RUNS_KEY in files
    has_progress = AGENT3_EXECUTION_PROGRESS_KEY in files
    if has_progress and not has_runs:
        return (
            "execution-progress authority is present without the Agent 3 run store; "
            "restoring the sidecar alone could replace watermarks for retained live run state"
        )
    if runs_have_rows and not has_progress:
        return (
            "Agent 3 run state is present without execution-progress authority; "
            "restoring it could replay a previously-started non-idempotent step"
        )
    return None


def create(out_dir: str = ".") -> str:
    """Write a timestamped archive and return its path."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    archive = os.path.join(out_dir, f"kaliv-backup-{stamp}.tar.gz")

    inventory = items()
    by_key = {item.key: item for item in inventory}
    runs = by_key[AGENT3_RUNS_KEY]
    progress = by_key[AGENT3_EXECUTION_PROGRESS_KEY]
    runs_exists = os.path.exists(runs.path)
    progress_exists = os.path.exists(progress.path)
    runs_have_rows = False
    pair_id: Optional[str] = None

    if runs_exists:
        run_count, run_problem = _agent3_runs_row_count_path(runs.path)
        if run_problem:
            raise ValueError(
                "refusing to back up an invalid Agent 3 run store: " + run_problem
            )
        runs_have_rows = bool(run_count)
    if progress_exists and not runs_exists:
        raise ValueError(
            "refusing to back up execution-progress authority without the Agent 3 run store: "
            + progress.path
        )
    if runs_exists and progress_exists:
        pair_id, pair_problem = _live_pair_id_problem(runs.path, progress.path)
        if pair_problem:
            raise ValueError(
                "refusing to back up unproven Agent 3 live-pair authority: " + pair_problem
            )
        assert pair_id is not None
        run_count, run_problem = _agent3_runs_row_count_path(
            runs.path, pair_id=pair_id
        )
        progress_problem = _execution_progress_problem_path(
            progress.path, pair_id=pair_id
        )
        semantic_problem = None
        if not run_problem and not progress_problem:
            semantic_problem = _agent3_pair_semantic_problem_paths(runs.path, progress.path)
        if run_problem:
            raise ValueError(
                "refusing to back up invalid Agent 3 run authority: " + run_problem
            )
        if progress_problem:
            raise ValueError(
                "refusing to back up invalid Agent 3 execution-progress authority: "
                + progress_problem
            )
        if semantic_problem:
            raise ValueError(
                "refusing to back up semantically inconsistent Agent 3 authority: "
                + semantic_problem
            )
        runs_have_rows = bool(run_count)
    elif progress_exists:
        progress_problem = _execution_progress_problem_path(progress.path)
        if progress_problem:
            raise ValueError(
                "refusing to back up invalid Agent 3 execution-progress authority: "
                + progress_problem
            )
    elif runs_exists:
        binding, binding_problem = _read_pair_binding_path(runs.path)
        if binding_problem:
            raise ValueError(
                "refusing to back up invalid Agent 3 pair binding: " + binding_problem
            )
        if binding is not None:
            raise ValueError(
                "refusing to back up one member of a persistent Agent 3 live pair"
            )

    if runs_have_rows and not progress_exists:
        raise ValueError(
            "refusing to back up Agent 3 runs without the execution-progress sidecar: "
            + progress.path
        )

    manifest: dict = {"schema": BACKUP_SCHEMA, "created": stamp, "files": {}}
    tmp_archive = archive + ".tmp"
    try:
        with tempfile.TemporaryDirectory(prefix="kaliv-agent3-backup-") as stage_dir:
            archive_sources: dict[str, str] = {}

            if runs_exists and progress_exists:
                assert pair_id is not None
                snapshot_id = str(uuid.uuid4())
                progress_snapshot = os.path.join(stage_dir, "progress.db")
                runs_snapshot = os.path.join(stage_dir, "runs.db")

                # Runs-first / progress-second is the replay-safe monotone
                # boundary. If execution crosses the two physical copies, the
                # staged progress ledger is newer than the staged run payload;
                # semantic validation below then observes the watermark against
                # stale PENDING authority and refuses publication. The inverse
                # order can silently omit the only watermark proving a
                # non-idempotent step already started.
                _sqlite_snapshot(runs.path, runs_snapshot)
                _sqlite_snapshot(progress.path, progress_snapshot)
                _add_snapshot_binding(
                    progress_snapshot,
                    snapshot_id=snapshot_id,
                    role=_AGENT3_PROGRESS_ROLE,
                )
                _add_snapshot_binding(
                    runs_snapshot,
                    snapshot_id=snapshot_id,
                    role=_AGENT3_RUNS_ROLE,
                )
                progress_problem = _execution_progress_problem_path(
                    progress_snapshot,
                    snapshot_id=snapshot_id,
                    pair_id=pair_id,
                )
                run_count, run_problem = _agent3_runs_row_count_path(
                    runs_snapshot,
                    snapshot_id=snapshot_id,
                    pair_id=pair_id,
                )
                semantic_problem = None
                if not progress_problem and not run_problem:
                    semantic_problem = _agent3_pair_semantic_problem_paths(
                        runs_snapshot, progress_snapshot
                    )
                if progress_problem or run_problem or semantic_problem:
                    raise ValueError(
                        "refusing to publish an invalid bound Agent 3 backup snapshot: "
                        + str(progress_problem or run_problem or semantic_problem)
                    )
                if bool(run_count) != runs_have_rows:
                    raise ValueError("Agent 3 run snapshot changed unexpectedly during backup")
                manifest[AGENT3_PAIR_MANIFEST_KEY] = pair_id
                manifest[AGENT3_SNAPSHOT_MANIFEST_KEY] = snapshot_id
                archive_sources[AGENT3_RUNS_KEY] = runs_snapshot
                archive_sources[AGENT3_EXECUTION_PROGRESS_KEY] = progress_snapshot
            elif runs_exists:
                # A structurally valid empty, never-paired run store has no
                # execution authority yet. Snapshot it without pair metadata so
                # old never-used installations remain portable.
                runs_snapshot = os.path.join(stage_dir, "runs-empty.db")
                _sqlite_snapshot(runs.path, runs_snapshot)
                archive_sources[AGENT3_RUNS_KEY] = runs_snapshot

            with tarfile.open(tmp_archive, "w:gz") as tar:
                for item in inventory:
                    if item.kind == "file":
                        source = archive_sources.get(item.key, item.path)
                        if not os.path.exists(source):
                            continue
                        digest = _sha256_file(source)
                        manifest["files"][item.key] = {
                            "sha256": digest,
                            "kind": "file",
                        }
                        tar.add(source, arcname=f"data/{item.key}")
                    else:
                        if not os.path.isdir(item.path):
                            continue
                        stored: dict[str, str] = {}
                        for filename in _walk(item.path):
                            rel = os.path.relpath(filename, item.path)
                            stored[rel] = _sha256_file(filename)
                            tar.add(filename, arcname=f"data/{item.key}/{rel}")
                        manifest["files"][item.key] = {
                            "kind": "dir",
                            "files": stored,
                        }

                payload = json.dumps(manifest, indent=2, sort_keys=True).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
        os.replace(tmp_archive, archive)
    finally:
        try:
            os.remove(tmp_archive)
        except FileNotFoundError:
            pass
    return archive


def _read_manifest(archive: str) -> dict:
    with tarfile.open(archive, "r:gz") as tar:
        try:
            f = tar.extractfile("manifest.json")
        except KeyError as exc:
            raise ValueError("not a Kaliv backup: no manifest.json") from exc
        if f is None:
            raise ValueError("manifest.json is not a file")
        try:
            value = json.loads(f.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid backup manifest") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid backup manifest: root must be an object")
        return value


def verify(archive: str) -> dict:
    """Check transport hashes and Agent 3 authority semantics without restoring."""
    manifest = _read_manifest(archive)
    schema = manifest.get("schema")
    if schema not in SUPPORTED_BACKUP_SCHEMAS:
        raise ValueError(f"unsupported backup schema: {schema}")
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("invalid backup manifest: files must be an object")

    problems: list[str] = []
    checked = 0
    with tarfile.open(archive, "r:gz") as tar:
        has_runs = AGENT3_RUNS_KEY in files
        has_progress = AGENT3_EXECUTION_PROGRESS_KEY in files
        run_bytes = (
            _member_bytes(tar, f"data/{AGENT3_RUNS_KEY}") if has_runs else None
        )
        progress_bytes = (
            _member_bytes(tar, f"data/{AGENT3_EXECUTION_PROGRESS_KEY}")
            if has_progress
            else None
        )
        runs_have_rows = False
        run_count: Optional[int] = None
        progress_count: Optional[int] = None

        snapshot_id: Optional[str] = None
        if schema in {4, BACKUP_SCHEMA} and has_progress:
            raw_snapshot_id = manifest.get(AGENT3_SNAPSHOT_MANIFEST_KEY)
            snapshot_problem = _snapshot_id_problem(raw_snapshot_id)
            if snapshot_problem:
                problems.append(snapshot_problem)
            else:
                snapshot_id = str(raw_snapshot_id)
        elif schema in {4, BACKUP_SCHEMA} and manifest.get(AGENT3_SNAPSHOT_MANIFEST_KEY) is not None:
            problems.append(
                "Agent 3 snapshot id is present without paired execution-progress authority"
            )

        pair_id: Optional[str] = None
        if schema == BACKUP_SCHEMA and has_progress:
            raw_pair_id = manifest.get(AGENT3_PAIR_MANIFEST_KEY)
            pair_problem = _pair_id_problem(raw_pair_id)
            if pair_problem:
                problems.append(pair_problem)
            else:
                pair_id = str(raw_pair_id)
        elif schema == BACKUP_SCHEMA and manifest.get(AGENT3_PAIR_MANIFEST_KEY) is not None:
            problems.append(
                "Agent 3 pair id is present without paired execution-progress authority"
            )

        if run_bytes is not None:
            run_count, run_problem = _agent3_runs_row_count_bytes(
                run_bytes,
                snapshot_id=snapshot_id if schema in {4, BACKUP_SCHEMA} and has_progress else None,
                pair_id=pair_id if schema == BACKUP_SCHEMA and has_progress else None,
            )
            if run_problem:
                problems.append(f"invalid Agent 3 run store: {run_problem}")
            else:
                runs_have_rows = bool(run_count)

        authority_problem = _agent3_authority_problem(
            files, runs_have_rows=runs_have_rows
        )
        if authority_problem:
            problems.append(authority_problem)

        progress_ok = False
        if progress_bytes is not None:
            progress_problem = _execution_progress_problem_bytes(
                progress_bytes,
                snapshot_id=snapshot_id if schema in {4, BACKUP_SCHEMA} else None,
                pair_id=pair_id if schema == BACKUP_SCHEMA else None,
            )
            if progress_problem:
                problems.append(
                    "invalid Agent 3 execution-progress authority: " + progress_problem
                )
            else:
                progress_ok = True
                progress_count, count_problem = _execution_progress_row_count_bytes(
                    progress_bytes
                )
                if count_problem:
                    progress_ok = False
                    problems.append(
                        "invalid Agent 3 execution-progress authority: " + count_problem
                    )

        if (
            schema == BACKUP_SCHEMA
            and has_runs
            and has_progress
            and run_bytes is not None
            and progress_bytes is not None
            and pair_id is not None
            and snapshot_id is not None
            and run_count is not None
            and progress_ok
        ):
            semantic_problem = _pair_semantic_problem_bytes(run_bytes, progress_bytes)
            if semantic_problem:
                problems.append(
                    "invalid Agent 3 run/progress semantic relation: " + semantic_problem
                )

        if schema < BACKUP_SCHEMA and (has_progress or bool(run_count)):
            problems.append(
                "legacy Agent 3 authority lacks schema-5 persistent live-pair binding"
            )

        if schema == BACKUP_SCHEMA and has_progress and (snapshot_id is None or pair_id is None):
            # Detailed id errors were already recorded. Keep relation fail-closed.
            pass
        elif schema == BACKUP_SCHEMA and has_progress and not has_runs:
            problems.append("schema-5 Agent 3 authority requires both paired stores")

        for key, meta in files.items():
            if not isinstance(meta, dict) or meta.get("kind") not in {"file", "dir"}:
                problems.append(f"invalid manifest entry: {key}")
                continue
            if meta["kind"] == "file":
                want = meta.get("sha256")
                got = _member_sha(tar, f"data/{key}")
                if got is None:
                    problems.append(f"missing from archive: {key}")
                elif not isinstance(want, str) or got != want:
                    problems.append(f"hash mismatch: {key}")
                else:
                    checked += 1
            else:
                recorded = meta.get("files")
                if not isinstance(recorded, dict):
                    problems.append(f"invalid directory manifest entry: {key}")
                    continue
                for rel, want in recorded.items():
                    got = _member_sha(tar, f"data/{key}/{rel}")
                    if got is None:
                        problems.append(f"missing from archive: {key}/{rel}")
                    elif got != want:
                        problems.append(f"hash mismatch: {key}/{rel}")
                    else:
                        checked += 1

    return {"ok": not problems, "checked": checked, "problems": problems}


def _write_bytes_fsync(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def _fsync_dir(path: str) -> None:
    """Best-effort directory fsync where the platform exposes directory handles."""
    if os.name == "nt":
        return
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stage_member_near(tar: tarfile.TarFile, member: str, destination: str) -> str:
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    fd, stage = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination)}.restore-",
        dir=parent,
    )
    os.close(fd)
    data = _member_bytes(tar, member)
    if data is None:
        try:
            os.remove(stage)
        except FileNotFoundError:
            pass
        raise ValueError(f"cannot read {member} from archive")
    _write_bytes_fsync(stage, data)
    return stage


def _publish_agent3_pair(
    *,
    runs_stage: str,
    progress_stage: str,
    runs_path: str,
    progress_path: str,
    snapshot_id: str,
) -> None:
    """Publish a paired authority restore with the run path as durable fence."""
    run_parent = os.path.dirname(os.path.abspath(runs_path))
    progress_parent = os.path.dirname(os.path.abspath(progress_path))
    os.makedirs(run_parent, exist_ok=True)
    os.makedirs(progress_parent, exist_ok=True)
    fd, fence_stage = tempfile.mkstemp(
        prefix=f".{os.path.basename(runs_path)}.fence-", dir=run_parent
    )
    os.close(fd)
    try:
        _write_bytes_fsync(
            fence_stage,
            _RESTORE_FENCE_PREFIX + snapshot_id.encode("ascii") + b"\n",
        )
        os.replace(fence_stage, runs_path)
        _fsync_dir(run_parent)
        fence_stage = ""

        os.replace(progress_stage, progress_path)
        _fsync_dir(progress_parent)

        os.replace(runs_stage, runs_path)
        _fsync_dir(run_parent)
    finally:
        if fence_stage:
            try:
                os.remove(fence_stage)
            except FileNotFoundError:
                pass


def restore(archive: str, force: bool = False) -> dict:
    """Restore an archive after complete verification.

    Schema-5 Agent 3 authority is staged, snapshot-unbound, pair-validated and
    published as one fenced pair before any unrelated file is replaced.
    """
    check = verify(archive)
    if not check["ok"]:
        raise ValueError(
            f"archive failed verification, refusing to restore: {check['problems']}"
        )

    manifest = _read_manifest(archive)
    schema = manifest["schema"]
    targets = {item.key: item for item in items()}
    files = manifest["files"]

    if not force:
        clashes = []
        for key in files:
            item = targets.get(key)
            if item and os.path.exists(item.path):
                clashes.append(item.path)
        if clashes:
            raise FileExistsError(
                "these already exist (use --force to overwrite): " + ", ".join(clashes)
            )

    restored: list[str] = []
    pair_keys: set[str] = set()
    with tarfile.open(archive, "r:gz") as tar:
        if (
            schema == BACKUP_SCHEMA
            and AGENT3_RUNS_KEY in files
            and AGENT3_EXECUTION_PROGRESS_KEY in files
        ):
            snapshot_id = manifest.get(AGENT3_SNAPSHOT_MANIFEST_KEY)
            snapshot_problem = _snapshot_id_problem(snapshot_id)
            pair_id = manifest.get(AGENT3_PAIR_MANIFEST_KEY)
            pair_problem = _pair_id_problem(pair_id)
            if snapshot_problem or pair_problem:
                raise ValueError(str(snapshot_problem or pair_problem))
            assert isinstance(snapshot_id, str)
            assert isinstance(pair_id, str)
            runs_item = targets[AGENT3_RUNS_KEY]
            progress_item = targets[AGENT3_EXECUTION_PROGRESS_KEY]
            runs_stage = _stage_member_near(
                tar, f"data/{AGENT3_RUNS_KEY}", runs_item.path
            )
            progress_stage = _stage_member_near(
                tar, f"data/{AGENT3_EXECUTION_PROGRESS_KEY}", progress_item.path
            )
            try:
                run_count, run_problem = _agent3_runs_row_count_path(
                    runs_stage,
                    snapshot_id=snapshot_id,
                    pair_id=pair_id,
                )
                progress_problem = _execution_progress_problem_path(
                    progress_stage,
                    snapshot_id=snapshot_id,
                    pair_id=pair_id,
                )
                semantic_problem = None
                if not run_problem and not progress_problem:
                    semantic_problem = _agent3_pair_semantic_problem_paths(
                        runs_stage, progress_stage
                    )
                if run_problem or progress_problem or semantic_problem:
                    raise ValueError(
                        "invalid staged Agent 3 authority pair: "
                        + str(run_problem or progress_problem or semantic_problem)
                    )

                _strip_snapshot_binding(
                    runs_stage,
                    snapshot_id=snapshot_id,
                    role=_AGENT3_RUNS_ROLE,
                )
                _strip_snapshot_binding(
                    progress_stage,
                    snapshot_id=snapshot_id,
                    role=_AGENT3_PROGRESS_ROLE,
                )

                live_run_count, live_run_problem = _agent3_runs_row_count_path(
                    runs_stage, pair_id=pair_id
                )
                live_progress_problem = _execution_progress_problem_path(
                    progress_stage, pair_id=pair_id
                )
                live_semantic_problem = None
                if not live_run_problem and not live_progress_problem:
                    live_semantic_problem = _agent3_pair_semantic_problem_paths(
                        runs_stage, progress_stage
                    )
                if live_run_problem or live_progress_problem or live_semantic_problem:
                    raise ValueError(
                        "invalid snapshot-unbound staged Agent 3 authority pair: "
                        + str(
                            live_run_problem
                            or live_progress_problem
                            or live_semantic_problem
                        )
                    )
                if live_run_count != run_count:
                    raise ValueError("Agent 3 run count changed while removing snapshot binding")

                _publish_agent3_pair(
                    runs_stage=runs_stage,
                    progress_stage=progress_stage,
                    runs_path=runs_item.path,
                    progress_path=progress_item.path,
                    snapshot_id=snapshot_id,
                )
                runs_stage = ""
                progress_stage = ""
                restored.extend([runs_item.path, progress_item.path])
                pair_keys = {AGENT3_RUNS_KEY, AGENT3_EXECUTION_PROGRESS_KEY}
            finally:
                for stage in (runs_stage, progress_stage):
                    if stage:
                        try:
                            os.remove(stage)
                        except FileNotFoundError:
                            pass

        for key, meta in files.items():
            if key in pair_keys:
                continue
            item = targets.get(key)
            if item is None:
                continue
            if meta["kind"] == "file":
                _extract_to(tar, f"data/{key}", item.path)
                restored.append(item.path)
            else:
                os.makedirs(item.path, exist_ok=True)
                for rel in meta["files"]:
                    destination = os.path.join(item.path, rel)
                    _extract_to(tar, f"data/{key}/{rel}", destination)
                    restored.append(destination)
    return {"restored": restored}


def _extract_to(tar: tarfile.TarFile, member: str, dest: str) -> None:
    data = _member_bytes(tar, member)
    if data is None:
        raise ValueError(f"cannot read {member} from archive")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".tmp"
    try:
        _write_bytes_fsync(tmp, data)
        os.replace(tmp, dest)
        _fsync_dir(os.path.dirname(os.path.abspath(dest)))
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kaliv-backup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--out", default=".")
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("archive")
    restore_parser.add_argument("--force", action="store_true")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("archive")
    args = parser.parse_args(argv)

    if args.cmd == "create":
        path = create(args.out)
        result = verify(path)
        if not result["ok"]:
            raise ValueError(f"created backup failed verification: {result['problems']}")
        print(f"created {path} ({result['checked']} files, verified)")
        return 0
    if args.cmd == "verify":
        result = verify(args.archive)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if args.cmd == "restore":
        result = restore(args.archive, force=args.force)
        print(f"restored {len(result['restored'])} files")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
