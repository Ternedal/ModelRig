"""Compatibility facade for Kaliv backup/restore.

The schema-5 implementation owns every authority-critical invariant itself:
closed run/progress schemas, pair/snapshot semantics, replay-safe snapshot
ordering, restore exclusion and failure-atomic publication. This module keeps
the historical ``app.backup`` import surface, the physical-snapshot test hook,
and the established independent replay-risk diagnostic for malformed legacy
archives. Importing this facade is no longer required to make
``backup_schema5`` safe.
"""
from __future__ import annotations

from typing import Optional

from . import backup_schema5 as _impl

# Preserve the historical app.backup module contract, including private helper
# names used by migration/adoption regressions.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

_original_restore = _impl.restore
_original_verify = _impl.verify
_original_runs_row_count_path = _impl._agent3_runs_row_count_path
_original_sqlite_snapshot = _impl._sqlite_snapshot


def _runs_first_sqlite_snapshot(source: str, destination: str) -> None:
    """Delegate one physical SQLite copy through the facade's test hook.

    Ordering itself belongs to ``backup_schema5.create``. This indirection only
    lets the existing regression inject execution after the first physical copy;
    it grants no authority and direct schema-5 callers do not depend on it.
    """
    _original_sqlite_snapshot(source, destination)


_impl._sqlite_snapshot = _runs_first_sqlite_snapshot
globals()["_sqlite_snapshot"] = _runs_first_sqlite_snapshot


def _missing_execution_authority_problem(archive: str) -> Optional[str]:
    """Keep the independent missing-watermark replay-risk diagnostic visible.

    Core closed-schema validation may reject a malformed legacy run member
    before the strict verifier records its row count. Missing execution-progress
    is nevertheless an independent replay-risk defect. Count only the canonical
    ``agent_runs`` table shape here; the core verifier still owns the actual
    closed-schema refusal and all direct-entry safety boundaries.
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
        lambda path: _impl._schema5_basic_runs_row_count_path(path),
    )
    if count_problem or not run_count:
        return None
    return (
        "Agent 3 run state is present without execution-progress authority; "
        "restoring it could replay a previously-started non-idempotent step"
    )


def verify(archive: str) -> dict:
    """Preserve independent diagnostics while core owns safety semantics."""
    result = _original_verify(archive)
    replay_problem = _missing_execution_authority_problem(archive)
    if replay_problem is None:
        return result

    problems = list(result.get("problems", []))
    if not any("execution-progress authority" in str(problem) for problem in problems):
        problems.append(replay_problem)
    return {**result, "ok": False, "problems": problems}


# Preserve historical facade diagnostics for callers of app.backup. This does
# not provide the direct-entry safety fix: backup_schema5 already owns closed
# schema validation and restore exclusion before this module is imported.
_impl.verify = verify
globals()["verify"] = verify


def main(argv: Optional[list[str]] = None) -> int:
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
