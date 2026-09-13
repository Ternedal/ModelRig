"""Guarded public facade for Kaliv backup/restore.

The schema-5 authority implementation lives in ``backup_schema5`` so its
previously qualified backup semantics remain byte-for-byte intact. This facade
adds the newer cross-process Agent3 runtime/restore guard without weakening the
schema-5 pair/snapshot/semantic checks.
"""
from __future__ import annotations

from typing import Optional

from . import backup_schema5 as _impl
from .agent3.runtime_restore_guard import agent3_restore_guard

# Preserve the historical app.backup module contract, including private helper
# names used by migration/adoption regressions. The implementation remains the
# owner of all backup-schema logic; this module only owns restore exclusion.
for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

_original_restore = _impl.restore


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
