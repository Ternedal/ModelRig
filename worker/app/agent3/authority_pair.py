from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Callable, Optional

PAIR_TABLE = "kaliv_agent3_authority_pair"
PAIR_TABLE_SQL = (
    "CREATE TABLE kaliv_agent3_authority_pair ("
    "pair_id TEXT NOT NULL, store_role TEXT NOT NULL)"
)
RUNS_ROLE = "agent3-runs"
PROGRESS_ROLE = "agent3-execution-progress"

RUNS_TABLE_SQL = (
    "CREATE TABLE agent_runs ("
    "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
)
EVENTS_TABLE_SQL = (
    "CREATE TABLE agent_events ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "
    "kind TEXT NOT NULL, payload TEXT NOT NULL)"
)
PROGRESS_TABLE_SQL = (
    "CREATE TABLE agent_execution_starts ("
    "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
    "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"
)

PairValidator = Callable[[sqlite3.Connection], Optional[str]]


def _normalize_sql(value: object) -> Optional[str]:
    if value is None:
        return None
    return " ".join(str(value).split())


def uuid_problem(value: object, *, label: str = "Agent 3 pair id") -> Optional[str]:
    if not isinstance(value, str):
        return f"{label} is missing or not a string"
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return f"{label} is not a UUID"
    if str(parsed) != value.lower():
        return f"{label} is not canonical"
    return None


def inspect_binding(
    con: sqlite3.Connection,
    *,
    schema: str = "main",
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Return one canonical pair binding, distinguish absent from malformed."""
    if schema not in {"main", "progressdb"}:
        raise ValueError("unsupported SQLite schema name")
    try:
        row = con.execute(
            f"SELECT sql FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (PAIR_TABLE,),
        ).fetchone()
        if row is None:
            return None, None
        columns = list(con.execute(f"PRAGMA {schema}.table_xinfo({PAIR_TABLE})"))
        values = list(
            con.execute(f"SELECT pair_id,store_role FROM {schema}.{PAIR_TABLE}")
        )
    except sqlite3.Error as exc:
        return None, f"cannot inspect persistent Agent 3 pair binding: {exc}"

    if _normalize_sql(row[0]) != PAIR_TABLE_SQL:
        return None, "persistent Agent 3 pair binding table is non-canonical"
    actual_columns = [
        (str(col[1]), str(col[2]).upper(), int(col[3]), int(col[5]), int(col[6]))
        for col in columns
    ]
    expected_columns = [
        ("pair_id", "TEXT", 1, 0, 0),
        ("store_role", "TEXT", 1, 0, 0),
    ]
    if actual_columns != expected_columns:
        return None, "persistent Agent 3 pair binding columns are non-canonical"
    if len(values) != 1:
        return None, "persistent Agent 3 pair binding must contain exactly one row"
    pair_id, role = str(values[0][0]), str(values[0][1])
    problem = uuid_problem(pair_id)
    if problem:
        return None, problem
    if role not in {RUNS_ROLE, PROGRESS_ROLE}:
        return None, f"persistent Agent 3 pair binding has invalid role {role!r}"
    return (pair_id, role), None


def read_binding_path(
    path: str,
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    try:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        return None, f"cannot open persistent Agent 3 pair authority: {exc}"
    try:
        return inspect_binding(con)
    finally:
        con.close()


def binding_problem_path(
    path: str,
    *,
    pair_id: str,
    role: str,
) -> Optional[str]:
    binding, problem = read_binding_path(path)
    if problem:
        return problem
    if binding is None:
        return "persistent Agent 3 pair binding table is missing"
    if binding != (pair_id, role):
        return (
            "persistent Agent 3 pair binding does not match the expected "
            f"pair id and role {role!r}"
        )
    return None


def _journal_delete(con: sqlite3.Connection, schema: str) -> None:
    row = con.execute(f"PRAGMA {schema}.journal_mode=DELETE").fetchone()
    if row is None or str(row[0]).lower() != "delete":
        raise RuntimeError(f"could not put {schema} Agent 3 authority in DELETE journal mode")


def _validate_bound_pair(
    runs_binding: tuple[str, str],
    progress_binding: tuple[str, str],
) -> str:
    run_pair_id, run_role = runs_binding
    progress_pair_id, progress_role = progress_binding
    if run_role != RUNS_ROLE or progress_role != PROGRESS_ROLE:
        raise RuntimeError("Agent 3 persistent pair roles do not match their stores")
    if run_pair_id != progress_pair_id:
        raise RuntimeError("Agent 3 run/progress stores belong to different live pairs")
    return run_pair_id


def _insert_pair_rows(con: sqlite3.Connection, pair_id: str) -> None:
    con.execute(PAIR_TABLE_SQL)
    con.execute(
        f"INSERT INTO {PAIR_TABLE}(pair_id,store_role) VALUES(?,?)",
        (pair_id, RUNS_ROLE),
    )
    con.execute(
        "CREATE TABLE progressdb." + PAIR_TABLE_SQL.removeprefix("CREATE TABLE ")
    )
    con.execute(
        f"INSERT INTO progressdb.{PAIR_TABLE}(pair_id,store_role) VALUES(?,?)",
        (pair_id, PROGRESS_ROLE),
    )


def ensure_live_pair(runs_path: str) -> str:
    """Create/validate persistent provenance for the live run + progress pair.

    Pair bootstrap is deliberately narrow. New/empty authority can receive a
    fresh identity. Existing non-empty authority without an identity is refused:
    assigning a new id there would silently bless potentially unrelated source
    stores. Existing installations must instead use the explicit offline
    ``app.backup adopt-agent3-pair`` transition, which validates run/watermark
    semantics under one multi-database write boundary before stamping the pair.

    The two binding rows are created in one SQLite multi-database transaction.
    DELETE journaling is required because SQLite only guarantees atomic commit
    across ATTACHed databases when the main database is file-backed and WAL is
    not in use.
    """
    if runs_path == ":memory:":
        raise RuntimeError("persistent Agent 3 pair authority requires a file-backed run store")

    runs_path = os.path.abspath(runs_path)
    progress_path = runs_path + ".execution-progress"
    os.makedirs(os.path.dirname(runs_path), exist_ok=True)

    con = sqlite3.connect(runs_path)
    try:
        _journal_delete(con, "main")
        con.execute("ATTACH DATABASE ? AS progressdb", (progress_path,))
        _journal_delete(con, "progressdb")
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute(f"CREATE TABLE IF NOT EXISTS {RUNS_TABLE_SQL.removeprefix('CREATE TABLE ')}")
            con.execute(f"CREATE TABLE IF NOT EXISTS {EVENTS_TABLE_SQL.removeprefix('CREATE TABLE ')}")
            con.execute(
                "CREATE TABLE IF NOT EXISTS progressdb."
                + PROGRESS_TABLE_SQL.removeprefix("CREATE TABLE ")
            )

            runs_binding, runs_problem = inspect_binding(con, schema="main")
            progress_binding, progress_problem = inspect_binding(con, schema="progressdb")
            if runs_problem or progress_problem:
                raise RuntimeError(str(runs_problem or progress_problem))

            run_count = int(con.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0])
            progress_count = int(
                con.execute(
                    "SELECT COUNT(*) FROM progressdb.agent_execution_starts"
                ).fetchone()[0]
            )

            if runs_binding is None and progress_binding is None:
                if run_count or progress_count:
                    raise RuntimeError(
                        "refusing to assign a new Agent 3 pair id to non-empty unbound authority; "
                        "stop the appliance and run `python -m app.backup adopt-agent3-pair`"
                    )
                pair_id = str(uuid.uuid4())
                _insert_pair_rows(con, pair_id)
            elif runs_binding is None or progress_binding is None:
                raise RuntimeError(
                    "Agent 3 persistent pair binding exists on only one authority store"
                )
            else:
                pair_id = _validate_bound_pair(runs_binding, progress_binding)

            con.commit()
            return pair_id
        except Exception:
            con.rollback()
            raise
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot establish persistent Agent 3 pair authority: {exc}") from exc
    finally:
        con.close()


def adopt_live_pair(runs_path: str, validator: PairValidator) -> str:
    """Explicitly bind existing authority while both stores are write-locked.

    This is intentionally separate from startup bootstrap. It is the one-time
    trust transition for a pre-pair-id installation and must only be invoked by
    an offline migration/operator path. ``validator`` runs after BEGIN IMMEDIATE
    with both databases attached, so pair metadata is committed only if the
    caller proves the existing run/watermark relation safe inside the same
    locked boundary. Re-running the transition is idempotent for an already
    valid pair, but never repairs one-sided or mismatched bindings.
    """
    if runs_path == ":memory:":
        raise RuntimeError("persistent Agent 3 pair authority requires a file-backed run store")

    runs_path = os.path.abspath(runs_path)
    progress_path = runs_path + ".execution-progress"
    if not os.path.isfile(runs_path) or not os.path.isfile(progress_path):
        raise RuntimeError("offline Agent 3 pair adoption requires both authority files")

    con = sqlite3.connect(runs_path)
    try:
        _journal_delete(con, "main")
        con.execute("ATTACH DATABASE ? AS progressdb", (progress_path,))
        _journal_delete(con, "progressdb")
        con.execute("BEGIN IMMEDIATE")
        try:
            runs_binding, runs_problem = inspect_binding(con, schema="main")
            progress_binding, progress_problem = inspect_binding(con, schema="progressdb")
            if runs_problem or progress_problem:
                raise RuntimeError(str(runs_problem or progress_problem))
            if (runs_binding is None) != (progress_binding is None):
                raise RuntimeError(
                    "Agent 3 persistent pair binding exists on only one authority store"
                )

            problem = validator(con)
            if problem:
                raise RuntimeError(
                    "refusing offline Agent 3 pair adoption: " + problem
                )

            if runs_binding is not None and progress_binding is not None:
                pair_id = _validate_bound_pair(runs_binding, progress_binding)
            else:
                pair_id = str(uuid.uuid4())
                _insert_pair_rows(con, pair_id)

            con.commit()
            return pair_id
        except Exception:
            con.rollback()
            raise
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot adopt persistent Agent 3 pair authority: {exc}") from exc
    finally:
        con.close()
