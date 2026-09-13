"""Guarded public facade for Kaliv backup/restore.

The schema-5 authority implementation lives in ``backup_schema5`` so its
previously qualified pair/snapshot semantics remain intact. This facade layers
newer cross-process restore exclusion, closed run-store schema validation and a
fail-closed runs-first snapshot boundary on that implementation without
duplicating the backup state machine.
"""
from __future__ import annotations

import threading
from typing import Optional

from . import backup_schema5 as _impl
from .agent3.authority_pair import (
    EVENTS_TABLE_SQL as _EVENTS_TABLE_SQL,
    PAIR_TABLE as _PAIR_TABLE,
    PAIR_TABLE_SQL as _PAIR_TABLE_SQL,
    RUNS_ROLE as _RUNS_ROLE,
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
_original_sqlite_snapshot = _impl._sqlite_snapshot
_snapshot_state = threading.local()


def _runs_first_sqlite_snapshot(source: str, destination: str) -> None:
    """Keep the qualified core API while reversing its unsafe paired call order.

    ``backup_schema5.create`` historically asks for the progress snapshot first
    and the run snapshot second. Defer that first progress copy until the paired
    run copy arrives. The actual SQLite snapshot order then becomes runs first,
    progress second. If execution crosses the boundary, the staged progress
    ledger can only be as new as or newer than the staged run payload; the
    existing semantic validator therefore fails closed instead of silently
    losing the only watermark proving a non-idempotent step started.

    State is thread-local so independent backup callers cannot borrow or flush
    another caller's deferred snapshot.
    """
    pending = getattr(_snapshot_state, "pending_progress", None)
    destination_name = _impl.os.path.basename(destination)

    if pending is not None:
        if destination_name == "runs.db":
            try:
                _original_sqlite_snapshot(source, destination)
                _original_sqlite_snapshot(*pending)
            finally:
                _snapshot_state.pending_progress = None
            return
        # A future core changed the expected paired sequence. Preserve ordinary
        # snapshot semantics rather than carrying deferred state into another
        # operation; the dedicated regression will then fail instead of hiding
        # the contract drift.
        _snapshot_state.pending_progress = None
        _original_sqlite_snapshot(*pending)

    if destination_name == "progress.db" and source.endswith(".execution-progress"):
        _snapshot_state.pending_progress = (source, destination)
        return

    _original_sqlite_snapshot(source, destination)


# Functions defined in backup_schema5 resolve globals in that module. Interpose
# the snapshot primitive there so direct ``backup_schema5.create`` callers also
# retain the safe paired ordering.
_impl._sqlite_snapshot = _runs_first_sqlite_snapshot
globals()["_sqlite_snapshot"] = _runs_first_sqlite_snapshot


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
    after restore. Two exact variants are valid: the minimal historical run
    store and the full runtime store with its event log. Neither permits any
    extra SQLite object.
    """
    del run_count  # row count is semantic authority, not a reason to allow drift.
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

    common = [
        ("index", "sqlite_autoindex_agent_runs_1", "agent_runs", None),
        ("table", "agent_runs", "agent_runs", _impl._normalize_sql(_RUNS_TABLE_SQL)),
    ]
    if pair_id is not None:
        common.append(
            ("table", _PAIR_TABLE, _PAIR_TABLE, _impl._normalize_sql(_PAIR_TABLE_SQL))
        )
    if snapshot_id is not None:
        common.append(
            (
                "table",
                _impl._SNAPSHOT_TABLE,
                _impl._SNAPSHOT_TABLE,
                _impl._normalize_sql(_impl._SNAPSHOT_TABLE_SQL),
            )
        )

    minimal = sorted(common, key=lambda row: (row[0], row[1], row[2]))
    full = list(common)
    full.extend(
        [
            (
                "table",
                "agent_events",
                "agent_events",
                _impl._normalize_sql(_EVENTS_TABLE_SQL),
            ),
            (
                "table",
                "sqlite_sequence",
                "sqlite_sequence",
                "CREATE TABLE sqlite_sequence(name,seq)",
            ),
        ]
    )
    full = sorted(full, key=lambda row: (row[0], row[1], row[2]))

    if actual == minimal or actual == full:
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
    # create() performs an initial structural run-store read before it resolves
    # the cross-store pair id. A canonical binding already present in this run
    # store is therefore structural evidence we must account for, not schema
    # drift. Equality with the progress-store binding is still checked later by
    # _live_pair_id_problem before any snapshot is published.
    effective_pair_id = pair_id
    if effective_pair_id is None:
        binding, binding_problem = _impl._read_pair_binding_path(path)
        if binding_problem:
            return None, binding_problem
        if binding is not None:
            detected_pair_id, detected_role = binding
            if detected_role != _RUNS_ROLE:
                return None, "persistent Agent 3 pair binding has the wrong run-store role"
            effective_pair_id = detected_pair_id

    count, problem = _original_runs_row_count_path(
        path,
        snapshot_id=snapshot_id,
        pair_id=effective_pair_id,
    )
    if problem or count is None:
        return count, problem
    schema_problem = _run_store_schema_problem_path(
        path,
        run_count=count,
        snapshot_id=snapshot_id,
        pair_id=effective_pair_id,
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
