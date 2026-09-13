"""Guarded public facade for Kaliv backup/restore.

The schema-5 authority implementation lives in ``backup_schema5`` so its
previously qualified pair/snapshot semantics remain intact. This facade layers
newer cross-process restore exclusion and the closed run-store schema check on
that implementation without duplicating the backup state machine.
"""
from __future__ import annotations

from typing import Optional

from . import backup_schema5 as _impl
from .agent3.authority_pair import (
    EVENTS_TABLE_SQL as _EVENTS_TABLE_SQL,
    PAIR_TABLE as _PAIR_TABLE,
    PAIR_TABLE_SQL as _PAIR_TABLE_SQL,
    RUNS_TABLE_SQL as _RUNS_TABLE_SQL,
)
from .agent3.runtime_restore_guard import agent3_restore_guard

# Preserve the historical app.backup module contract, including private helper
# names used by migration/adoption regressions. The implementation remains the
# owner of the archive state machine; this module owns cross-process exclusion
# and additional structural qualification.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

_original_restore = _impl.restore
_original_runs_row_count_path = _impl._agent3_runs_row_count_path


def _run_store_schema_problem_path(
    path: str,
    *,
    run_count: int,
    snapshot_id: Optional[str],
    pair_id: Optional[str],
) -> Optional[str]:
    """Require a closed SQLite schema for Agent3 run authority.

    Progress authority has always been checked against complete sqlite_master.
    Run authority must have the same property: an unexpected trigger, view or
    index can otherwise survive a hash-valid backup and alter future run state
    after restore. Canonical legacy ``agent_runs`` stores are structurally
    admissible before the runtime has created its event journal, including the
    exact pair/snapshot binding tables requested by the caller. A canonical
    pair table may also be present during a shape-only probe; its row/role/id
    authority is still validated separately by the schema-5 state machine.
    This lets explicit offline adoption inspect and then bind non-empty legacy
    authority without blessing extra SQLite objects. Schema-5 backup/create
    still rejects materialized unbound authority; structural admission grants
    no execution authority by itself.
    """
    del run_count  # row cardinality is an authority rule, not a schema-shape rule
    try:
        con = _impl._readonly_sqlite(path)
    except _impl.sqlite3.Error as exc:
        return f"cannot open Agent 3 run store for closed-schema validation: {exc}"
    try:
        try:
            rows = list(
                con.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master "
                    "ORDER BY type,name,tbl_name"
                )
            )
        except _impl.sqlite3.Error as exc:
            return f"cannot inspect Agent 3 run-store schema: {exc}"
    finally:
        con.close()

    actual = [
        (str(row[0]), str(row[1]), str(row[2]), _impl._normalize_sql(row[3]))
        for row in rows
    ]
    pair_table_present = any(
        kind == "table" and name == _PAIR_TABLE for kind, name, _table, _sql in actual
    )

    def add_expected_bindings(expected: list[tuple[str, str, str, Optional[str]]]) -> None:
        if pair_id is not None or pair_table_present:
            expected.append(
                ("table", _PAIR_TABLE, _PAIR_TABLE, _impl._normalize_sql(_PAIR_TABLE_SQL))
            )
        if snapshot_id is not None:
            expected.append(
                (
                    "table",
                    _impl._SNAPSHOT_TABLE,
                    _impl._SNAPSHOT_TABLE,
                    _impl._SNAPSHOT_TABLE_SQL,
                )
            )
        expected.sort(key=lambda row: (row[0], row[1], row[2]))

    full: list[tuple[str, str, str, Optional[str]]] = [
        ("index", "sqlite_autoindex_agent_runs_1", "agent_runs", None),
        ("table", "agent_events", "agent_events", _impl._normalize_sql(_EVENTS_TABLE_SQL)),
        ("table", "agent_runs", "agent_runs", _impl._normalize_sql(_RUNS_TABLE_SQL)),
        ("table", "sqlite_sequence", "sqlite_sequence", "CREATE TABLE sqlite_sequence(name,seq)"),
    ]
    add_expected_bindings(full)
    if actual == full:
        return None

    minimal: list[tuple[str, str, str, Optional[str]]] = [
        ("index", "sqlite_autoindex_agent_runs_1", "agent_runs", None),
        ("table", "agent_runs", "agent_runs", _impl._normalize_sql(_RUNS_TABLE_SQL)),
    ]
    add_expected_bindings(minimal)
    if actual == minimal:
        return None

    rendered = [f"{kind}:{name}->{table} sql={sql!r}" for kind, name, table, sql in actual]
    return (
        "Agent 3 run database does not match the canonical closed authority schema: "
        + (", ".join(rendered) if rendered else "none")
    )


def _agent3_runs_row_count_path(
    path: str,
    *,
    snapshot_id: Optional[str] = None,
    pair_id: Optional[str] = None,
) -> tuple[Optional[int], Optional[str]]:
    count, problem = _original_runs_row_count_path(
        path,
        snapshot_id=snapshot_id,
        pair_id=pair_id,
    )
    if problem or count is None:
        return count, problem
    schema_problem = _run_store_schema_problem_path(
        path,
        run_count=count,
        snapshot_id=snapshot_id,
        pair_id=pair_id,
    )
    if schema_problem:
        return None, schema_problem
    return count, None


# Functions defined in backup_schema5 resolve globals in that module. Replace
# its row-count validator too, so create/verify/restore and offline adoption all
# use the closed run-store schema rather than only callers of this facade.
_impl._agent3_runs_row_count_path = _agent3_runs_row_count_path
globals()["_agent3_runs_row_count_path"] = _agent3_runs_row_count_path


def _restore_preflight(archive: str, *, force: bool) -> dict[str, object]:
    """Reject invalid/no-clobber restores before setting the durable guard bit."""
    check = _impl.verify(archive)
    if not check["ok"]:
        raise ValueError(
            f"archive failed verification, refusing to restore: {check['problems']}"
        )

    manifest = _impl._read_manifest(archive)
    targets = {item.key: item for item in _impl.items()}
    files = manifest["files"]
    if not force:
        clashes = []
        for key in files:
            item = targets.get(key)
            if item and _impl.os.path.exists(item.path):
                clashes.append(item.path)
        if clashes:
            raise FileExistsError(
                "these already exist (use --force to overwrite): " + ", ".join(clashes)
            )
    return targets


def restore(archive: str, force: bool = False) -> dict:
    """Restore schema-5 state only while Agent3 runtime authority is quiescent.

    Transport/semantic verification and the normal no-clobber check happen
    before restore authority is acquired. Once the guard is acquired, every
    failure intentionally leaves its durable incomplete marker set; a complete
    verified retry is then required before Agent3 runtime may start again.
    """
    targets = _restore_preflight(archive, force=force)
    run_path = targets[_impl.AGENT3_RUNS_KEY].path
    with agent3_restore_guard(run_path):
        return _original_restore(archive, force=force)


# ``backup_schema5.main`` resolves its globals in its own module. Point its
# restore symbol at the guarded facade so ``python -m app.backup restore`` and
# direct Python callers exercise the identical exclusion contract.
_impl.restore = restore


def main(argv: Optional[list[str]] = None) -> int:
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
