"""Collect Kaliv's data files from old working directories into the data root.

Before v1.34.15 the RAG index, audit log, kill-switch state and device tokens
defaulted to RELATIVE paths, so they were written wherever the worker/server
happened to be launched from. After the anchoring fix they live under one data
root -- but files created before the upgrade are still sitting in those old
folders. This finds them and moves them in, so ingested knowledge and pairing
survive the upgrade.

Safe by design:
  - Never overwrites a file already in the data root that is NEWER than the
    candidate (your current state wins).
  - Copies then verifies size before removing the original (move is atomic-ish);
    with --keep it copies and leaves the original in place.
  - Dry-run by default: prints what it WOULD do. Pass --apply to act.

Usage (from the repo, on the rig):
    python -m app.migrate_data                 # dry run: show what would move
    python -m app.migrate_data --apply         # do it (move)
    python -m app.migrate_data --apply --keep   # copy, leave originals
"""
from __future__ import annotations

import argparse
import os
import shutil

from . import paths as _paths

# The data files we anchor, by their canonical basename in the data root.
DATA_FILES = [
    "modelrig-rag.db",       # RAG index
    "kaliv-audit.db",        # tool audit log
    "kaliv-tools-state.json",  # kill-switch state
    "modelrig-data.json",    # server device tokens / pairing
]


def _candidate_dirs() -> list[str]:
    """Directories a previous launch may have written relative data into."""
    home = os.path.expanduser("~")
    dirs = [
        os.getcwd(),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Desktop", "ModelRig"),
        os.path.join(home, "Desktop", "modelrig"),
        os.path.join(home, "Desktop", "modelrig-new"),
        os.path.join(home, "Desktop", "modelrig-mono"),
        os.path.join(home, "Desktop", "modelrig-monorepo"),
        home,
    ]
    # de-dup while preserving order, keep only existing dirs
    seen, out = set(), []
    for d in dirs:
        rd = os.path.realpath(d)
        if rd not in seen and os.path.isdir(rd):
            seen.add(rd)
            out.append(d)
    return out


def find() -> list[tuple[str, str]]:
    """Return (source_path, dest_path) for every data file found outside the root."""
    root = _paths.data_root()
    found = []
    for d in _candidate_dirs():
        for name in DATA_FILES:
            src = os.path.join(d, name)
            dst = os.path.join(root, name)
            if os.path.realpath(src) == os.path.realpath(dst):
                continue  # already the canonical file
            if os.path.isfile(src):
                found.append((src, dst))
    return found


def run(apply: bool, keep: bool) -> int:
    root = _paths.data_root()
    print(f"data root: {root}")
    hits = find()
    if not hits:
        print("Nothing to migrate -- no data files found in old locations.")
        return 0

    for src, dst in hits:
        action = "COPY" if keep else "MOVE"
        note = ""
        if os.path.exists(dst):
            if os.path.getmtime(dst) >= os.path.getmtime(src):
                print(f"  SKIP  {src}\n        (a same-or-newer {os.path.basename(dst)} is already in the root)")
                continue
            note = " (overwrites an OLDER file in the root)"
        print(f"  {action}  {src}\n     -> {dst}{note}")
        if not apply:
            continue
        os.makedirs(root, exist_ok=True)
        shutil.copy2(src, dst)
        if os.path.getsize(dst) != os.path.getsize(src):
            print(f"     ! size mismatch after copy -- left original in place")
            continue
        if not keep:
            os.remove(src)

    if not apply:
        print("\nDry run. Re-run with --apply to move the files (add --keep to copy instead).")
    else:
        print("\nDone.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect Kaliv data files into the data root.")
    ap.add_argument("--apply", action="store_true", help="actually move/copy (default: dry run)")
    ap.add_argument("--keep", action="store_true", help="copy and leave originals in place")
    a = ap.parse_args()
    return run(a.apply, a.keep)


if __name__ == "__main__":
    raise SystemExit(main())
