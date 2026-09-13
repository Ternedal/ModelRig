"""Compatibility facade for Kaliv backup/restore.

The schema-5 implementation owns every authority-critical invariant itself:
closed run/progress schemas, pair/snapshot semantics, replay-safe snapshot
ordering, restore exclusion and failure-atomic publication. This module keeps
the historical ``app.backup`` import surface plus the physical-snapshot test
hook; importing it is no longer required to make ``backup_schema5`` safe.
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


def main(argv: Optional[list[str]] = None) -> int:
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
