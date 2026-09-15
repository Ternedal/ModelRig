"""Regression contract for canonical backup manifest object kinds.

Run: PYTHONPATH=worker python3 tests/worker_backup_manifest_kind_authority.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile

_root = tempfile.mkdtemp(prefix="kaliv-backup-kind-authority-")
_live = os.path.join(_root, "live")
os.environ["KALIV_DATA_DIR"] = _live
os.environ["MODELRIG_DATA"] = os.path.join(_live, "data.json")
os.environ["KALIV_AGENT3_DB"] = os.path.join(_live, "agent3.db")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_live, "notes")

from app import backup_schema5 as backup  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def tree_snapshot(root: str) -> dict[str, bytes | None]:
    out: dict[str, bytes | None] = {}
    if not os.path.exists(root):
        return out
    for current, dirs, files in os.walk(root):
        rel_root = os.path.relpath(current, root)
        for dirname in sorted(dirs):
            rel = os.path.normpath(os.path.join(rel_root, dirname))
            out[rel + os.sep] = None
        for filename in sorted(files):
            path = os.path.join(current, filename)
            rel = os.path.normpath(os.path.join(rel_root, filename))
            with open(path, "rb") as handle:
                out[rel] = handle.read()
    return out


def write_archive(path: str, files: dict, members: dict[str, bytes]) -> None:
    manifest = {
        "schema": backup.BACKUP_SCHEMA,
        "created": "adversarial-kind-authority",
        "files": files,
    }
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))


os.makedirs(os.environ["KALIV_TOOLS_DIR"], exist_ok=True)
with open(os.environ["MODELRIG_DATA"], "wb") as handle:
    handle.write(b"live-data-json-sentinel")
with open(os.path.join(os.environ["KALIV_TOOLS_DIR"], "live.txt"), "wb") as handle:
    handle.write(b"live-notes-sentinel")

before = tree_snapshot(_live)
archive_dir = os.path.join(_root, "archives")
os.makedirs(archive_dir, exist_ok=True)

# A known file target may not be reinterpreted as a directory by archive input.
file_child = b"attacker-controlled-directory-member"
file_as_dir = os.path.join(archive_dir, "file-as-dir.tar.gz")
write_archive(
    file_as_dir,
    {
        "data.json": {
            "kind": "dir",
            "files": {"child.txt": hashlib.sha256(file_child).hexdigest()},
        }
    },
    {"data/data.json/child.txt": file_child},
)
file_as_dir_verify = backup.verify(file_as_dir)
check(
    not file_as_dir_verify["ok"]
    and any(
        "manifest kind" in str(problem).lower() and "data.json" in str(problem)
        for problem in file_as_dir_verify["problems"]
    ),
    "manifest kind: canonical file target cannot be declared as a directory",
)
try:
    backup.restore(file_as_dir, force=True)
    check(False, "manifest kind: file-to-dir confusion is refused before restore")
except ValueError:
    check(True, "manifest kind: file-to-dir confusion is refused before restore")
check(
    tree_snapshot(_live) == before,
    "manifest kind: refused file-to-dir archive mutates no live state",
)

# A known directory target may not be reinterpreted as a file either.
dir_payload = b"attacker-controlled-file-member"
dir_as_file = os.path.join(archive_dir, "dir-as-file.tar.gz")
write_archive(
    dir_as_file,
    {
        "notes": {
            "kind": "file",
            "sha256": hashlib.sha256(dir_payload).hexdigest(),
        }
    },
    {"data/notes": dir_payload},
)
dir_as_file_verify = backup.verify(dir_as_file)
check(
    not dir_as_file_verify["ok"]
    and any(
        "manifest kind" in str(problem).lower() and "notes" in str(problem)
        for problem in dir_as_file_verify["problems"]
    ),
    "manifest kind: canonical directory target cannot be declared as a file",
)
try:
    backup.restore(dir_as_file, force=True)
    check(False, "manifest kind: dir-to-file confusion is refused before restore")
except ValueError:
    check(True, "manifest kind: dir-to-file confusion is refused before restore")
check(
    tree_snapshot(_live) == before,
    "manifest kind: refused dir-to-file archive mutates no live state",
)

print(f"\n===== BACKUP MANIFEST KIND AUTHORITY: {passed} passed, {failed} failed =====")
sys.exit(0 if failed == 0 else 1)
