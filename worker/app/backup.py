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
from pathlib import Path
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


def _readonly_sqlite(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _sqlite_table_problem(
    path: str,
    *,
    table: str,
    required: dict[str, tuple[str, int | None, int | None]],
) -> Optional[str]:
    try:
        con = _readonly_sqlite(path)
    except sqlite3.Error as exc:
        return f"cannot open SQLite database: {exc}"
    try:
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                return f"SQLite integrity_check failed: {integrity[0] if integrity else 'no result'}"
            rows = list(con.execute(f"PRAGMA table_info({table})"))
        except sqlite3.Error as exc:
            return f"cannot inspect SQLite authority: {exc}"
        if not rows:
            return f"required table {table} is missing"
        columns = {str(row[1]): row for row in rows}
        for name, (want_type, want_notnull, want_pk) in required.items():
            row = columns.get(name)
            if row is None:
                return f"required column {table}.{name} is missing"
            got_type = str(row[2]).upper()
            if got_type != want_type:
                return f"column {table}.{name} has type {got_type!r}, expected {want_type}"
            if want_notnull is not None and int(row[3]) != want_notnull:
                return f"column {table}.{name} has invalid NOT NULL authority"
            if want_pk is not None and int(row[5]) != want_pk:
                return f"column {table}.{name} has invalid primary-key authority"
        return None
    finally:
        con.close()


def _execution_progress_problem_path(path: str) -> Optional[str]:
    problem = _sqlite_table_problem(
        path,
        table="agent_execution_starts",
        required={
            "run_id": ("TEXT", 1, 1),
            "step_index": ("INTEGER", 1, 2),
            "step_sha256": ("TEXT", 1, 3),
            "started_at": ("REAL", 1, 0),
        },
    )
    if problem:
        return problem

    # This sidecar is dedicated execution authority, not a general SQLite
    # extension point. Attesting only visible columns is insufficient: inline
    # constraints such as CHECK(0) can suppress INSERT OR IGNORE, and hostile
    # writable_schema edits can hide active objects behind attacker-selected
    # sqlite_* names. Inspect every catalog row and require the exact canonical
    # CREATE TABLE plus the one SQLite-generated primary-key autoindex.
    try:
        con = _readonly_sqlite(path)
    except sqlite3.Error as exc:
        return f"cannot open SQLite database: {exc}"
    try:
        try:
            schema_rows = list(
                con.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master "
                    "ORDER BY type,name,tbl_name"
                )
            )
            column_rows = list(con.execute("PRAGMA table_xinfo(agent_execution_starts)"))
        except sqlite3.Error as exc:
            return f"cannot inspect SQLite execution-authority schema: {exc}"

        expected_create_sql = (
            "CREATE TABLE agent_execution_starts ("
            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
            "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"
        )
        expected_schema = [
            (
                "index",
                "sqlite_autoindex_agent_execution_starts_1",
                "agent_execution_starts",
                None,
            ),
            (
                "table",
                "agent_execution_starts",
                "agent_execution_starts",
                expected_create_sql,
            ),
        ]
        normalized_schema = [
            (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                None if row[3] is None else " ".join(str(row[3]).split()),
            )
            for row in schema_rows
        ]
        if normalized_schema != expected_schema:
            rendered = [
                f"{row[0]}:{row[1]}->{row[2]} sql={row[3]!r}" for row in normalized_schema
            ]
            return (
                "execution-progress database does not match the canonical authority schema: "
                + (", ".join(rendered) if rendered else "none")
            )

        expected_columns = [
            ("run_id", "TEXT", 1, 1, 0),
            ("step_index", "INTEGER", 1, 2, 0),
            ("step_sha256", "TEXT", 1, 3, 0),
            ("started_at", "REAL", 1, 0, 0),
        ]
        actual_columns = [
            (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]), int(row[6]))
            for row in column_rows
        ]
        if actual_columns != expected_columns:
            return "execution-progress table does not match the exact authority column schema"
        return None
    finally:
        con.close()


def _agent3_runs_row_count_path(path: str) -> tuple[Optional[int], Optional[str]]:
    problem = _sqlite_table_problem(
        path,
        table="agent_runs",
        required={
            "id": ("TEXT", None, 1),
            "state": ("TEXT", 1, 0),
            "payload": ("TEXT", 1, 0),
            "updated_at": ("REAL", 1, 0),
        },
    )
    if problem:
        return None, problem
    con = _readonly_sqlite(path)
    try:
        try:
            row = con.execute("SELECT COUNT(*) FROM agent_runs").fetchone()
        except sqlite3.Error as exc:
            return None, f"cannot count Agent 3 runs: {exc}"
        if row is None:
            return None, "cannot count Agent 3 runs: no result"
        return int(row[0]), None
    finally:
        con.close()


def _with_temp_sqlite(data: bytes, inspector):
    fd, path = tempfile.mkstemp(prefix="kaliv-backup-sqlite-", suffix=".db")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(data)
        return inspector(path)
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _execution_progress_problem_bytes(data: bytes) -> Optional[str]:
    return _with_temp_sqlite(data, _execution_progress_problem_path)


def _agent3_runs_row_count_bytes(data: bytes) -> tuple[Optional[int], Optional[str]]:
    return _with_temp_sqlite(data, _agent3_runs_row_count_path)


def _member_bytes(tar: tarfile.TarFile, name: str) -> Optional[bytes]:
    try:
        f = tar.extractfile(name)
    except KeyError:
        return None
    if f is None:
        return None
    return f.read()


def _agent3_authority_problem(files: dict, *, runs_have_rows: bool) -> Optional[str]:
    if runs_have_rows and AGENT3_EXECUTION_PROGRESS_KEY not in files:
        return (
            "Agent 3 run state is present without execution-progress authority; "
            "restoring it could replay a previously-started non-idempotent step"
        )
    return None


def create(out_dir: str = ".") -> str:
    """Write a timestamped archive. Returns its path."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    archive = os.path.join(out_dir, f"kaliv-backup-{stamp}.tar.gz")

    inventory = items()
    by_key = {item.key: item for item in inventory}
    runs = by_key[AGENT3_RUNS_KEY]
    progress = by_key[AGENT3_EXECUTION_PROGRESS_KEY]
    runs_have_rows = False
    if os.path.exists(runs.path):
        run_count, run_problem = _agent3_runs_row_count_path(runs.path)
        if run_problem:
            raise ValueError(
                "refusing to back up an invalid Agent 3 run store: " + run_problem
            )
        runs_have_rows = bool(run_count)
    if os.path.exists(progress.path):
        progress_problem = _execution_progress_problem_path(progress.path)
        if progress_problem:
            raise ValueError(
                "refusing to back up invalid Agent 3 execution-progress authority: "
                + progress_problem
            )
    if runs_have_rows and not os.path.exists(progress.path):
        raise ValueError(
            "refusing to back up Agent 3 runs without the execution-progress sidecar: "
            + progress.path
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

    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("invalid backup manifest: files must be an object")

    problems: list[str] = []
    checked = 0
    with tarfile.open(archive, "r:gz") as tar:
        runs_have_rows = False
        if AGENT3_RUNS_KEY in files:
            run_bytes = _member_bytes(tar, f"data/{AGENT3_RUNS_KEY}")
            if run_bytes is not None:
                run_count, run_problem = _agent3_runs_row_count_bytes(run_bytes)
                if run_problem:
                    problems.append(f"invalid Agent 3 run store: {run_problem}")
                else:
                    runs_have_rows = bool(run_count)
        authority_problem = _agent3_authority_problem(
            files, runs_have_rows=runs_have_rows
        )
        if authority_problem:
            problems.append(authority_problem)

        if AGENT3_EXECUTION_PROGRESS_KEY in files:
            progress_bytes = _member_bytes(
                tar, f"data/{AGENT3_EXECUTION_PROGRESS_KEY}"
            )
            if progress_bytes is not None:
                progress_problem = _execution_progress_problem_bytes(progress_bytes)
                if progress_problem:
                    problems.append(
                        "invalid Agent 3 execution-progress authority: "
                        + progress_problem
                    )

        for key, meta in files.items():
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
