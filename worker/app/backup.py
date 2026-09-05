"""Kaliv backup & restore.

Bundles the persistent rig state that cannot be rebuilt from the repo into one
timestamped archive, and restores it. The archive deliberately contains data,
not installation artifacts or operator secrets.

The backup inventory follows the current 2.x persistent stores:

  rag.db                       embedding index
  data.json                    Go backend pairing/device-token state
  audit.db                     append-only tool audit log
  tools-state.json             persisted tool kill-switch state
  jobs.db                      async job state
  schedules.db                 schedules + scheduler approval-use state
  agent3-*.db                  Agent 3 runs/reviews/replans/memory/plans/approvals
  home-rig-*.db/data-sharing   home-rig pilot authorization/audit state
  notes/                       what note_append wrote

WHAT IS NOT INCLUDED: model weights (re-pullable via Ollama), Piper voices,
repository files, modelrig.env, API keys, approval secrets or other credentials.
Those are installation/configuration inputs, not portable data archives.

Schema 1 is the original V7 inventory. Schema 2 is the current 2.x inventory.
New code accepts both so old backups remain restorable; new archives use schema
2 so old code fails closed instead of accepting an archive whose newer keys it
would silently skip.

The manifest records a schema version and every stored file's sha256, so a
restore can refuse a corrupt or truncated archive instead of writing half of one
over live data. For a cross-machine migration, stop the appliance first; the
Windows migration wrapper in scripts/migrate-new-rig-state.ps1 does that and
fails closed if ModelRig processes remain alive.

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
import sys
import tarfile
import time
from dataclasses import dataclass
from typing import Optional

BACKUP_SCHEMA = 2
SUPPORTED_BACKUP_SCHEMAS = frozenset({1, BACKUP_SCHEMA})

# Resolve paths exactly like the worker. Relative defaults are anchored under
# the stable Kaliv data root; explicit env overrides continue to win.
from . import paths as _paths  # noqa: E402
from . import tools as _tools  # noqa: E402


@dataclass
class Item:
    key: str          # stable name inside the archive
    path: str         # absolute source path on the rig
    kind: str         # "file" or "dir"
    required: bool    # a missing required item aborts restore; optional is fine


def _resolved(default: str, env: str) -> str:
    return _paths.resolve(default, env=env)


def _backend_data() -> str:
    # The Go server reads its device-token file from MODELRIG_DATA. Honour an
    # explicit value verbatim; otherwise use the conventional stable data root.
    value = os.getenv("MODELRIG_DATA")
    if value:
        return value
    return _paths.resolve("./modelrig-data.json")


def items() -> list[Item]:
    """Return the authoritative portable-state inventory.

    Keep create and restore on one list so they cannot disagree. All stores are
    optional because a feature that has never been used legitimately has no file
    yet. Once present, however, it is part of the migration archive.
    """
    files = [
        ("rag.db", "./modelrig-rag.db", "MODELRIG_DB"),
        ("audit.db", "./kaliv-audit.db", "KALIV_AUDIT_DB"),
        ("tools-state.json", "./kaliv-tools-state.json", "KALIV_TOOLS_STATE"),
        ("jobs.db", "./modelrig-jobs.db", "MODELRIG_JOBS_DB"),
        ("schedules.db", "./kaliv-schedules.db", "KALIV_SCHEDULES_DB"),
        ("agent3-runs.db", "./kaliv-agent3.db", "KALIV_AGENT3_DB"),
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
    out = [Item(key, _resolved(default, env), "file", required=False) for key, default, env in files]
    out.insert(1, Item("data.json", _backend_data(), "file", required=False))
    out.append(Item("notes", _tools.tools_dir(), "dir", required=False))
    return out


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _walk(path: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(path):
        for fn in sorted(files):
            out.append(os.path.join(root, fn))
    return sorted(out)


def create(out_dir: str = ".") -> str:
    """Write a timestamped archive. Returns its path."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    archive = os.path.join(out_dir, f"kaliv-backup-{stamp}.tar.gz")

    manifest: dict = {"schema": BACKUP_SCHEMA, "created": stamp, "files": {}}

    # Build the archive in a temp path, then atomically rename: a reader must
    # never see a half-written backup and mistake it for a whole one.
    tmp = archive + ".tmp"
    with tarfile.open(tmp, "w:gz") as tar:
        for it in items():
            if it.kind == "file":
                if not os.path.exists(it.path):
                    continue
                digest = _sha256_file(it.path)
                manifest["files"][it.key] = {"sha256": digest, "kind": "file"}
                tar.add(it.path, arcname=f"data/{it.key}")
            else:  # dir
                if not os.path.isdir(it.path):
                    continue
                filed: dict = {}
                for f in _walk(it.path):
                    rel = os.path.relpath(f, it.path)
                    arc = f"data/{it.key}/{rel}"
                    filed[rel] = _sha256_file(f)
                    tar.add(f, arcname=arc)
                manifest["files"][it.key] = {"kind": "dir", "files": filed}

        payload = json.dumps(manifest, indent=2, sort_keys=True).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    os.replace(tmp, archive)
    return archive


def _read_manifest(archive: str) -> dict:
    with tarfile.open(archive, "r:gz") as tar:
        try:
            f = tar.extractfile("manifest.json")
        except KeyError:
            raise ValueError("not a Kaliv backup: no manifest.json")
        if f is None:
            raise ValueError("manifest.json is not a file")
        return json.loads(f.read())


def verify(archive: str) -> dict:
    """Check every stored file against its recorded hash WITHOUT extracting."""
    manifest = _read_manifest(archive)
    if manifest.get("schema") not in SUPPORTED_BACKUP_SCHEMAS:
        raise ValueError(f"unsupported backup schema: {manifest.get('schema')}")

    problems: list[str] = []
    checked = 0
    with tarfile.open(archive, "r:gz") as tar:
        for key, meta in manifest["files"].items():
            if meta["kind"] == "file":
                member = f"data/{key}"
                got = _member_sha(tar, member)
                if got is None:
                    problems.append(f"missing from archive: {key}")
                elif got != meta["sha256"]:
                    problems.append(f"hash mismatch: {key}")
                else:
                    checked += 1
            else:
                for rel, want in meta["files"].items():
                    member = f"data/{key}/{rel}"
                    got = _member_sha(tar, member)
                    if got is None:
                        problems.append(f"missing from archive: {key}/{rel}")
                    elif got != want:
                        problems.append(f"hash mismatch: {key}/{rel}")
                    else:
                        checked += 1
    return {"ok": not problems, "checked": checked, "problems": problems}


def _member_sha(tar: tarfile.TarFile, name: str) -> Optional[str]:
    try:
        f = tar.extractfile(name)
    except KeyError:
        return None
    if f is None:
        return None
    return _sha256_bytes(f.read())


def restore(archive: str, force: bool = False) -> dict:
    """Restore an archive over the live locations.

    Verifies the whole archive FIRST and refuses if anything fails. Without
    --force, refuses to overwrite existing files, so a restore cannot silently
    clobber a rig that already has data.
    """
    check = verify(archive)
    if not check["ok"]:
        raise ValueError(f"archive failed verification, refusing to restore: {check['problems']}")

    manifest = _read_manifest(archive)
    targets = {it.key: it for it in items()}

    # Pre-flight: without --force, refuse if any destination already exists.
    if not force:
        clashes = []
        for key in manifest["files"]:
            it = targets.get(key)
            if it and os.path.exists(it.path):
                clashes.append(it.path)
        if clashes:
            raise FileExistsError(
                "these already exist (use --force to overwrite): " + ", ".join(clashes)
            )

    restored: list[str] = []
    with tarfile.open(archive, "r:gz") as tar:
        for key, meta in manifest["files"].items():
            it = targets.get(key)
            if it is None:
                continue  # schema-1 archives may contain keys not known here
            if meta["kind"] == "file":
                _extract_to(tar, f"data/{key}", it.path)
                restored.append(it.path)
            else:
                os.makedirs(it.path, exist_ok=True)
                for rel in meta["files"]:
                    dest = os.path.join(it.path, rel)
                    _extract_to(tar, f"data/{key}/{rel}", dest)
                    restored.append(dest)
    return {"restored": restored}


def _extract_to(tar: tarfile.TarFile, member: str, dest: str) -> None:
    f = tar.extractfile(member)
    if f is None:
        raise ValueError(f"cannot read {member} from archive")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as out:
        out.write(f.read())
    os.replace(tmp, dest)  # atomic per file: never a half-written restore


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kaliv-backup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--out", default=".")
    r = sub.add_parser("restore"); r.add_argument("archive"); r.add_argument("--force", action="store_true")
    v = sub.add_parser("verify"); v.add_argument("archive")
    args = ap.parse_args(argv)

    if args.cmd == "create":
        path = create(args.out)
        res = verify(path)  # never hand back a backup without checking it
        print(f"created {path} ({res['checked']} files, verified)")
        return 0
    if args.cmd == "verify":
        res = verify(args.archive)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    if args.cmd == "restore":
        res = restore(args.archive, force=args.force)
        print(f"restored {len(res['restored'])} files")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())