"""Guarded public facade for Kaliv backup/restore.

The schema-5 authority implementation lives in ``backup_schema5`` so its
previously qualified pair/snapshot semantics, including replay-safe runs-first
snapshot ordering, remain owned by the core implementation. This facade layers
newer cross-process restore exclusion and a closed run-store schema check
without duplicating the backup state machine.
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
_original_verify = _impl.verify
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
    after restore. Two exact variants are valid: the minimal historical run
    store and the full runtime store with its event log. Neither permits any
    extra SQLite object.

    ``backup_schema5.create`` performs one row-count discovery pass before it
    resolves the expected live pair id. During that pass an already-canonical
    pair table is structural metadata, not yet trusted identity. We therefore
    allow its exact schema if it parses canonically, while the subsequent
    ``_live_pair_id_problem`` + pair-aware validation still proves id/role
    equality. This does not bless one-sided or foreign pairs.
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

    allow_pair_table = pair_id is not None
    if not allow_pair_table:
        discovered_binding, binding_problem = _impl._read_pair_binding_path(path)
        if binding_problem:
            return binding_problem
        allow_pair_table = discovered_binding is not None

    common = [
        ("index", "sqlite_autoindex_agent_runs_1", "agent_runs", None),
        ("table", "agent_runs", "agent_runs", _impl._normalize_sql(_RUNS_TABLE_SQL)),
    ]
    if allow_pair_table:
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


def _missing_execution_authority_problem(archive: str) -> Optional[str]:
    """Keep replay-risk diagnostics visible even when run schema is also invalid.

    Closed-schema validation can reject a legacy/downgraded run member before
    the strict verifier records its row count. Missing execution-progress is an
    independent safety defect: materialized runs without their watermark store
    can make a previously-started non-idempotent step look replayable. Count
    only the canonical ``agent_runs`` table shape here, without trusting any of
    the extra SQLite objects that caused the strict schema rejection.
    """
    manifest = _impl._read_manifest(archive)
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        return None
    if (
        _impl.AGENT3_RUNS_KEY not in files
        or _impl.AGENT3_EXECUTION_PROGRESS_KEY in files
    ):
        return None

    with _impl.tarfile.open(archive, "r:gz") as tar:
        run_data = _impl._member_bytes(tar, f"data/{_impl.AGENT3_RUNS_KEY}")
    if run_data is None:
        return None

    run_count, count_problem = _impl._with_temp_sqlite(
        run_data,
        lambda path: _original_runs_row_count_path(path),
    )
    if count_problem or not run_count:
        return None
    return (
        "Agent 3 run state is present without execution-progress authority; "
        "restoring it could replay a previously-started non-idempotent step"
    )


def verify(archive: str) -> dict:
    """Verify strictly while reporting independent replay-risk defects too."""
    result = _original_verify(archive)
    replay_problem = _missing_execution_authority_problem(archive)
    if replay_problem is None:
        return result

    problems = list(result.get("problems", []))
    if not any("execution-progress authority" in str(problem) for problem in problems):
        problems.append(replay_problem)
    return {**result, "ok": False, "problems": problems}


# The schema-5 implementation's restore function resolves ``verify`` in its own
# module at call time. Install the facade verifier there as well so direct
# verification and guarded restore use the same comprehensive fail-closed gate.
_impl.verify = verify
globals()["verify"] = verify


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
