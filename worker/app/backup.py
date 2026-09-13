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
  agent3-execution-progress.db rollback-resistant Agent 3 execution-start authority
  home-rig-*.db/data-sharing   home-rig pilot authorization/audit state
  notes/                       what note_append wrote

WHAT IS NOT INCLUDED: model weights (re-pullable via Ollama), Piper voices,
repository files, modelrig.env, API keys, approval secrets or other credentials.
Those are installation/configuration inputs, not portable data archives.

Schema 1 is the original V7 inventory. Schema 2 expanded the 2.x inventory.
Schema 3 adds the separate Agent 3 execution-progress authority introduced to
fence rollback/replay of non-idempotent steps. New code can read schemas 1/2/3,
but a legacy archive that contains Agent 3 runs without the matching progress
sidecar is refused as unsafe rather than silently restoring weaker authority.
New archives use schema 3 so older code fails closed instead of accepting a
backup whose execution-authority key it would silently skip.

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
import sqlite3
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

BACKUP_SCHEMA = 3
SUPPORTED_BACKUP_SCHEMAS = frozenset({1, 2, BACKUP_SCHEMA})
AGENT3_RUNS_KEY = "agent3-runs.db"
AGENT3_EXECUTION_PROGRESS_KEY = "agent3-execution-progress.db"

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
        (AGENT3_RUNS_KEY, "./kaliv-agent3.db", "KALIV_AGENT3_DB"),
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

    # AgentRunStore deliberately keeps execution-start watermarks in a separate
    # SQLite file at exactly <KALIV_AGENT3_DB>.execution-progress. Derive the
    # portable path from the already-resolved run DB so custom locations cannot
    # make create/restore disagree about the sidecar.
    runs_index = next(i for i, item in enumerate(out) if item.key == AGENT3_RUNS_KEY)
    out.insert(
        runs_index + 1,
        Item(
            AGENT3_EXECUTION_PROGRESS_KEY,
            f"{out[runs_index].path}.execution-progress",
            "file",
            required=False,
        ),
    )
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


_AGENT3_RUNS_SCHEMA = [
    ("id", "TEXT", 0, 1),
    ("state", "TEXT", 1, 0),
    ("payload", "TEXT", 1, 0),
    ("updated_at", "REAL", 1, 0),
]
_AGENT3_PROGRESS_SCHEMA = [
    ("run_id", "TEXT", 1, 1),
    ("step_index", "INTEGER", 1, 2),
    ("step_sha256", "TEXT", 1, 3),
    ("started_at", "REAL", 1, 0),
]


def _sqlite_table_status(
    path: str,
    table: str,
    expected_schema: list[tuple[str, str, int, int]],
    *,
    count_rows: bool = False,
) -> tuple[Optional[str], Optional[int]]:
    """Read-only structural validation for authority SQLite files."""
    conn = None
    try:
        conn = sqlite3.connect(path)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            return f"SQLite integrity_check failed for {table}", None
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        actual = [(row[1], str(row[2]).upper(), int(row[3]), int(row[5])) for row in rows]
        if actual != expected_schema:
            return f"required table schema is missing or invalid for {table}", None
        count = int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) if count_rows else None
        return None, count
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        return f"cannot read SQLite authority for {table}: {type(exc).__name__}", None
    finally:
        if conn is not None:
            conn.close()


def _sqlite_bytes_status(
    data: bytes,
    table: str,
    expected_schema: list[tuple[str, str, int, int]],
    *,
    count_rows: bool = False,
) -> tuple[Optional[str], Optional[int]]:
    fd, path = tempfile.mkstemp(prefix="kaliv-backup-sqlite-", suffix=".db")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(data)
        return _sqlite_table_status(
            path, table, expected_schema, count_rows=count_rows
        )
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _execution_progress_problem(path: str) -> Optional[str]:
    problem, _ = _sqlite_table_status(
        path, "agent_execution_starts", _AGENT3_PROGRESS_SCHEMA
    )
    return problem


def _member_bytes(tar: tarfile.TarFile, name: str) -> Optional[bytes]:
    try:
        f = tar.extractfile(name)
    except KeyError:
        return None
    return None if f is None else f.read()


def _agent3_archive_authority_problems(tar: tarfile.TarFile, manifest: dict) -> list[str]:
    """Validate replay authority, while preserving safe legacy empty-run restores."""
    problems: list[str] = []
    files = manifest.get("files", {})
    schema = manifest.get("schema")
    has_runs = AGENT3_RUNS_KEY in files
    has_progress = AGENT3_EXECUTION_PROGRESS_KEY in files

    if has_progress:
        data = _member_bytes(tar, f"data/{AGENT3_EXECUTION_PROGRESS_KEY}")
        if data is not None:
            problem, _ = _sqlite_bytes_status(
                data, "agent_execution_starts", _AGENT3_PROGRESS_SCHEMA
            )
            if problem:
                problems.append(
                    "invalid Agent 3 execution-progress authority database: " + problem
                )

    if has_runs and not has_progress:
        # Schema 3 promises an explicit authority pair. Legacy schemas predate
        # the sidecar and remain safe only when the archived run table is empty.
        if schema == BACKUP_SCHEMA:
            problems.append(
                "Agent 3 run state is present without execution-progress authority; "
                "schema 3 requires the authority pair"
            )
        else:
            data = _member_bytes(tar, f"data/{AGENT3_RUNS_KEY}")
            if data is not None:
                problem, count = _sqlite_bytes_status(
                    data, "agent_runs", _AGENT3_RUNS_SCHEMA, count_rows=True
                )
                if problem:
                    problems.append(
                        "cannot prove legacy Agent 3 run store is empty: " + problem
                    )
                elif count:
                    problems.append(
                        "Agent 3 run state is present without execution-progress authority; "
                        "restoring it could replay a previously-started non-idempotent step"
                    )
    return problems


def create(out_dir: str = ".") -> str:
    """Write a timestamped archive. Returns its path."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    archive = os.path.join(out_dir, f"kaliv-backup-{stamp}.tar.gz")

    inventory = items()
    by_key = {item.key: item for item in inventory}
    runs = by_key[AGENT3_RUNS_KEY]
    progress = by_key[AGENT3_EXECUTION_PROGRESS_KEY]
    if os.path.exists(runs.path) and not os.path.exists(progress.path):
        raise ValueError(
            "refusing to back up Agent 3 runs without the execution-progress sidecar: "
            + progress.path
        )
    if os.path.exists(progress.path):
        progress_problem = _execution_progress_problem(progress.path)
        if progress_problem:
            raise ValueError(
                "refusing to back up invalid Agent 3 execution-progress authority: "
                + progress_problem
            )

    manifest: dict = {"schema": BACKUP_SCHEMA, "created": stamp, "files": {}}

    # Build the archive in a temp path, then atomically rename: a reader must
    # never see a half-written backup and mistake it for a whole one.
    tmp = archive + ".tmp"
    with tarfile.open(tmp, "w:gz") as tar:
        for it in inventory:
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
        problems.extend(_agent3_archive_authority_problems(tar, manifest))
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
                continue  # older archives may contain keys not known here
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
        if not res["ok"]:
            raise ValueError(f"created backup failed verification: {res['problems']}")
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
