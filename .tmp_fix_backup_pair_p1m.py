from pathlib import Path

backup_path = Path("worker/app/backup.py")
text = backup_path.read_text(encoding="utf-8")

text = text.replace("import time\n", "import time\nimport uuid\n", 1)
text = text.replace(
    'BACKUP_SCHEMA = 3\nSUPPORTED_BACKUP_SCHEMAS = frozenset({1, 2, BACKUP_SCHEMA})\nAGENT3_RUNS_KEY = "agent3-runs.db"\nAGENT3_EXECUTION_PROGRESS_KEY = "agent3-execution-progress.db"\n',
    'BACKUP_SCHEMA = 4\nSUPPORTED_BACKUP_SCHEMAS = frozenset({1, 2, 3, BACKUP_SCHEMA})\nAGENT3_RUNS_KEY = "agent3-runs.db"\nAGENT3_EXECUTION_PROGRESS_KEY = "agent3-execution-progress.db"\nAGENT3_AUTHORITY_PAIR_TABLE = "agent3_backup_pair"\nAGENT3_AUTHORITY_PAIR_CREATE_SQL = (\n    "CREATE TABLE agent3_backup_pair ("\n    "snapshot_id TEXT NOT NULL, runs_sha256 TEXT NOT NULL, progress_sha256 TEXT NOT NULL)"\n)\n',
    1,
)
text = text.replace(
    'Schema 3 adds the separate Agent 3 execution-progress authority introduced to\nfence rollback/replay of non-idempotent steps. New code can read schemas 1/2/3,\nbut a legacy archive that contains Agent 3 runs without the matching progress\nsidecar is refused as unsafe rather than silently restoring weaker authority.\nNew archives use schema 3 so older code fails closed instead of accepting a\nbackup whose execution-authority key it would silently skip.\n',
    'Schema 3 added the separate Agent 3 execution-progress authority introduced to\nfence rollback/replay of non-idempotent steps. Schema 4 binds the run database\nand progress sidecar to the same staged backup snapshot and restores that pair\nunder a persistent fail-closed fence. New code can read schemas 1/2/3/4, but\nlegacy archives that cannot prove safe Agent 3 authority remain refused. New\narchives use schema 4 so older code fails closed instead of accepting stronger\nauthority it does not understand.\n',
    1,
)
text = text.replace(
    'from . import tools as _tools  # noqa: E402\n',
    'from . import tools as _tools  # noqa: E402\nfrom .agent3.core import agent3_authority_restore_fence_path  # noqa: E402\n',
    1,
)

anchor = '''def _readonly_sqlite(path: str) -> sqlite3.Connection:\n    uri = Path(path).resolve().as_uri() + "?mode=ro"\n    return sqlite3.connect(uri, uri=True)\n\n\n'''
insert = r'''def _readonly_sqlite(path: str) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _sqlite_snapshot_copy(source: str, destination: str) -> None:
    """Create a transactionally consistent SQLite copy without mutating live authority."""
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    src = _readonly_sqlite(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


def _rows_sha256(rows) -> str:
    payload = json.dumps(
        [list(row) for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _agent3_runs_authority_sha256_path(path: str) -> str:
    con = _readonly_sqlite(path)
    try:
        rows = con.execute(
            "SELECT id,state,payload,updated_at FROM agent_runs ORDER BY id"
        ).fetchall()
        return _rows_sha256(rows)
    finally:
        con.close()


def _execution_progress_authority_sha256_path(path: str) -> str:
    con = _readonly_sqlite(path)
    try:
        rows = con.execute(
            "SELECT run_id,step_index,step_sha256,started_at "
            "FROM agent_execution_starts ORDER BY run_id,step_index,step_sha256"
        ).fetchall()
        return _rows_sha256(rows)
    finally:
        con.close()


def _authority_pair_row_path(path: str) -> tuple[Optional[tuple[str, str, str]], Optional[str]]:
    try:
        con = _readonly_sqlite(path)
    except sqlite3.Error as exc:
        return None, f"cannot open SQLite database: {exc}"
    try:
        try:
            schema = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (AGENT3_AUTHORITY_PAIR_TABLE,),
            ).fetchone()
            if schema is None:
                return None, "backup snapshot binding table is missing"
            got_sql = " ".join(str(schema[0]).split()) if schema[0] is not None else None
            want_sql = " ".join(AGENT3_AUTHORITY_PAIR_CREATE_SQL.split())
            if got_sql != want_sql:
                return None, "backup snapshot binding table has non-canonical schema"
            columns = list(con.execute(f"PRAGMA table_xinfo({AGENT3_AUTHORITY_PAIR_TABLE})"))
            actual = [
                (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]), int(row[6]))
                for row in columns
            ]
            expected = [
                ("snapshot_id", "TEXT", 1, 0, 0),
                ("runs_sha256", "TEXT", 1, 0, 0),
                ("progress_sha256", "TEXT", 1, 0, 0),
            ]
            if actual != expected:
                return None, "backup snapshot binding columns are non-canonical"
            rows = con.execute(
                f"SELECT snapshot_id,runs_sha256,progress_sha256 FROM {AGENT3_AUTHORITY_PAIR_TABLE}"
            ).fetchall()
        except sqlite3.Error as exc:
            return None, f"cannot inspect backup snapshot binding: {exc}"
        if len(rows) != 1:
            return None, "backup snapshot binding must contain exactly one row"
        row = tuple(str(value) for value in rows[0])
        if len(row[0]) != 32 or any(ch not in "0123456789abcdef" for ch in row[0]):
            return None, "backup snapshot id is invalid"
        for digest in row[1:]:
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                return None, "backup snapshot digest is invalid"
        return row, None
    finally:
        con.close()


def _write_authority_pair_row(path: str, row: tuple[str, str, str]) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(f"DROP TABLE IF EXISTS {AGENT3_AUTHORITY_PAIR_TABLE}")
        con.execute(AGENT3_AUTHORITY_PAIR_CREATE_SQL)
        con.execute(
            f"INSERT INTO {AGENT3_AUTHORITY_PAIR_TABLE}(snapshot_id,runs_sha256,progress_sha256) "
            "VALUES(?,?,?)",
            row,
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _agent3_pair_problem_path(runs_path: str, progress_path: str) -> Optional[str]:
    run_row, run_problem = _authority_pair_row_path(runs_path)
    if run_problem:
        return "run-store " + run_problem
    progress_row, progress_problem = _authority_pair_row_path(progress_path)
    if progress_problem:
        return "execution-progress " + progress_problem
    if run_row != progress_row:
        return "run-store and execution-progress snapshot bindings do not match"
    assert run_row is not None
    try:
        actual_runs = _agent3_runs_authority_sha256_path(runs_path)
        actual_progress = _execution_progress_authority_sha256_path(progress_path)
    except sqlite3.Error as exc:
        return f"cannot recompute Agent 3 authority snapshot digests: {exc}"
    if actual_runs != run_row[1]:
        return "run-store contents do not match their bound backup snapshot digest"
    if actual_progress != run_row[2]:
        return "execution-progress contents do not match their bound backup snapshot digest"
    return None


def _prepare_agent3_pair_snapshot(runs_source: str, progress_source: str, directory: str) -> tuple[str, str]:
    runs_copy = os.path.join(directory, AGENT3_RUNS_KEY)
    progress_copy = os.path.join(directory, AGENT3_EXECUTION_PROGRESS_KEY)
    _sqlite_snapshot_copy(runs_source, runs_copy)
    _sqlite_snapshot_copy(progress_source, progress_copy)
    snapshot_id = uuid.uuid4().hex
    row = (
        snapshot_id,
        _agent3_runs_authority_sha256_path(runs_copy),
        _execution_progress_authority_sha256_path(progress_copy),
    )
    _write_authority_pair_row(runs_copy, row)
    _write_authority_pair_row(progress_copy, row)
    problem = _agent3_pair_problem_path(runs_copy, progress_copy)
    if problem:
        raise ValueError("cannot stage bound Agent 3 backup authority: " + problem)
    return runs_copy, progress_copy


'''
if anchor not in text:
    raise SystemExit("missing readonly sqlite anchor")
text = text.replace(anchor, insert, 1)

old_schema = '''        expected_create_sql = (\n            "CREATE TABLE agent_execution_starts ("\n            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n            "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"\n        )\n        expected_schema = [\n            (\n                "index",\n                "sqlite_autoindex_agent_execution_starts_1",\n                "agent_execution_starts",\n                None,\n            ),\n            (\n                "table",\n                "agent_execution_starts",\n                "agent_execution_starts",\n                expected_create_sql,\n            ),\n        ]\n        normalized_schema = [\n            (\n                str(row[0]),\n                str(row[1]),\n                str(row[2]),\n                None if row[3] is None else " ".join(str(row[3]).split()),\n            )\n            for row in schema_rows\n        ]\n        if normalized_schema != expected_schema:\n            rendered = [\n                f"{row[0]}:{row[1]}->{row[2]} sql={row[3]!r}" for row in normalized_schema\n            ]\n            return (\n                "execution-progress database does not match the canonical authority schema: "\n                + (", ".join(rendered) if rendered else "none")\n            )\n'''
new_schema = '''        expected_create_sql = (\n            "CREATE TABLE agent_execution_starts ("\n            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n            "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"\n        )\n        normalized_schema = [\n            (\n                str(row[0]),\n                str(row[1]),\n                str(row[2]),\n                None if row[3] is None else " ".join(str(row[3]).split()),\n            )\n            for row in schema_rows\n        ]\n        required_schema = {\n            (\n                "index",\n                "sqlite_autoindex_agent_execution_starts_1",\n                "agent_execution_starts",\n                None,\n            ),\n            (\n                "table",\n                "agent_execution_starts",\n                "agent_execution_starts",\n                expected_create_sql,\n            ),\n        }\n        optional_pair = (\n            "table",\n            AGENT3_AUTHORITY_PAIR_TABLE,\n            AGENT3_AUTHORITY_PAIR_TABLE,\n            " ".join(AGENT3_AUTHORITY_PAIR_CREATE_SQL.split()),\n        )\n        got_schema = set(normalized_schema)\n        if (\n            not required_schema.issubset(got_schema)\n            or not got_schema.issubset(required_schema | {optional_pair})\n            or len(got_schema) != len(normalized_schema)\n        ):\n            rendered = [\n                f"{row[0]}:{row[1]}->{row[2]} sql={row[3]!r}" for row in normalized_schema\n            ]\n            return (\n                "execution-progress database does not match the canonical authority schema: "\n                + (", ".join(rendered) if rendered else "none")\n            )\n'''
if old_schema not in text:
    raise SystemExit("missing execution-progress schema block")
text = text.replace(old_schema, new_schema, 1)

anchor = '''def _agent3_runs_row_count_bytes(data: bytes) -> tuple[Optional[int], Optional[str]]:\n    return _with_temp_sqlite(data, _agent3_runs_row_count_path)\n\n\n'''
insert = r'''def _agent3_runs_row_count_bytes(data: bytes) -> tuple[Optional[int], Optional[str]]:
    return _with_temp_sqlite(data, _agent3_runs_row_count_path)


def _agent3_pair_problem_bytes(runs_data: bytes, progress_data: bytes) -> Optional[str]:
    with tempfile.TemporaryDirectory(prefix="kaliv-backup-pair-") as root:
        runs_path = os.path.join(root, AGENT3_RUNS_KEY)
        progress_path = os.path.join(root, AGENT3_EXECUTION_PROGRESS_KEY)
        with open(runs_path, "wb") as f:
            f.write(runs_data)
        with open(progress_path, "wb") as f:
            f.write(progress_data)
        return _agent3_pair_problem_path(runs_path, progress_path)


'''
if anchor not in text:
    raise SystemExit("missing bytes helper anchor")
text = text.replace(anchor, insert, 1)

old_create_tail = '''    manifest: dict = {"schema": BACKUP_SCHEMA, "created": stamp, "files": {}}\n\n    # Build the archive in a temp path, then atomically rename: a reader must\n    # never see a half-written backup and mistake it for a whole one.\n    tmp = archive + ".tmp"\n    with tarfile.open(tmp, "w:gz") as tar:\n        for it in inventory:\n            if it.kind == "file":\n                if not os.path.exists(it.path):\n                    continue\n                digest = _sha256_file(it.path)\n                manifest["files"][it.key] = {"sha256": digest, "kind": "file"}\n                tar.add(it.path, arcname=f"data/{it.key}")\n            else:  # dir\n                if not os.path.isdir(it.path):\n                    continue\n                filed: dict = {}\n                for f in _walk(it.path):\n                    rel = os.path.relpath(f, it.path)\n                    arc = f"data/{it.key}/{rel}"\n                    filed[rel] = _sha256_file(f)\n                    tar.add(f, arcname=arc)\n                manifest["files"][it.key] = {"kind": "dir", "files": filed}\n\n        payload = json.dumps(manifest, indent=2, sort_keys=True).encode()\n        info = tarfile.TarInfo("manifest.json")\n        info.size = len(payload)\n        tar.addfile(info, io.BytesIO(payload))\n\n    os.replace(tmp, archive)\n    return archive\n'''
new_create_tail = '''    manifest: dict = {"schema": BACKUP_SCHEMA, "created": stamp, "files": {}}\n    staged_sources: dict[str, str] = {}\n    pair_stage = None\n    if runs_exists and progress_exists:\n        pair_stage = tempfile.TemporaryDirectory(prefix="kaliv-backup-agent3-pair-")\n        staged_runs, staged_progress = _prepare_agent3_pair_snapshot(\n            runs.path, progress.path, pair_stage.name\n        )\n        staged_sources[AGENT3_RUNS_KEY] = staged_runs\n        staged_sources[AGENT3_EXECUTION_PROGRESS_KEY] = staged_progress\n\n    # Build the archive in a temp path, then atomically rename: a reader must\n    # never see a half-written backup and mistake it for a whole one.\n    tmp = archive + ".tmp"\n    try:\n        with tarfile.open(tmp, "w:gz") as tar:\n            for it in inventory:\n                if it.kind == "file":\n                    source = staged_sources.get(it.key, it.path)\n                    if not os.path.exists(source):\n                        continue\n                    digest = _sha256_file(source)\n                    manifest["files"][it.key] = {"sha256": digest, "kind": "file"}\n                    tar.add(source, arcname=f"data/{it.key}")\n                else:  # dir\n                    if not os.path.isdir(it.path):\n                        continue\n                    filed: dict = {}\n                    for f in _walk(it.path):\n                        rel = os.path.relpath(f, it.path)\n                        arc = f"data/{it.key}/{rel}"\n                        filed[rel] = _sha256_file(f)\n                        tar.add(f, arcname=arc)\n                    manifest["files"][it.key] = {"kind": "dir", "files": filed}\n\n            payload = json.dumps(manifest, indent=2, sort_keys=True).encode()\n            info = tarfile.TarInfo("manifest.json")\n            info.size = len(payload)\n            tar.addfile(info, io.BytesIO(payload))\n\n        os.replace(tmp, archive)\n        return archive\n    finally:\n        try:\n            os.remove(tmp)\n        except FileNotFoundError:\n            pass\n        if pair_stage is not None:\n            pair_stage.cleanup()\n'''
if old_create_tail not in text:
    raise SystemExit("missing create archive tail")
text = text.replace(old_create_tail, new_create_tail, 1)

text = text.replace(
    '    with tarfile.open(archive, "r:gz") as tar:\n        runs_have_rows = False\n',
    '    with tarfile.open(archive, "r:gz") as tar:\n        runs_have_rows = False\n        run_bytes = None\n        progress_bytes = None\n',
    1,
)
verify_anchor = '''        if AGENT3_EXECUTION_PROGRESS_KEY in files:\n            progress_bytes = _member_bytes(\n                tar, f"data/{AGENT3_EXECUTION_PROGRESS_KEY}"\n            )\n            if progress_bytes is not None:\n                progress_problem = _execution_progress_problem_bytes(progress_bytes)\n                if progress_problem:\n                    problems.append(\n                        "invalid Agent 3 execution-progress authority: "\n                        + progress_problem\n                    )\n\n        for key, meta in files.items():\n'''
verify_replacement = '''        if AGENT3_EXECUTION_PROGRESS_KEY in files:\n            progress_bytes = _member_bytes(\n                tar, f"data/{AGENT3_EXECUTION_PROGRESS_KEY}"\n            )\n            if progress_bytes is not None:\n                progress_problem = _execution_progress_problem_bytes(progress_bytes)\n                if progress_problem:\n                    problems.append(\n                        "invalid Agent 3 execution-progress authority: "\n                        + progress_problem\n                    )\n\n        if run_bytes is not None and progress_bytes is not None:\n            pair_problem = _agent3_pair_problem_bytes(run_bytes, progress_bytes)\n            if pair_problem:\n                problems.append("invalid Agent 3 bound authority pair: " + pair_problem)\n\n        for key, meta in files.items():\n'''
if verify_anchor not in text:
    raise SystemExit("missing verify progress block")
text = text.replace(verify_anchor, verify_replacement, 1)

member_anchor = '''def _member_sha(tar: tarfile.TarFile, name: str) -> Optional[str]:\n    try:\n        f = tar.extractfile(name)\n    except KeyError:\n        return None\n    if f is None:\n        return None\n    return _sha256_bytes(f.read())\n\n\n'''
member_insert = r'''def _member_sha(tar: tarfile.TarFile, name: str) -> Optional[str]:
    try:
        f = tar.extractfile(name)
    except KeyError:
        return None
    if f is None:
        return None
    return _sha256_bytes(f.read())


def _write_durable_file(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _restore_agent3_authority_pair(
    tar: tarfile.TarFile,
    runs: Item,
    progress: Item,
    restored: list[str],
) -> None:
    runs_data = _member_bytes(tar, f"data/{AGENT3_RUNS_KEY}")
    progress_data = _member_bytes(tar, f"data/{AGENT3_EXECUTION_PROGRESS_KEY}")
    if runs_data is None or progress_data is None:
        raise ValueError("cannot read the complete Agent 3 authority pair from archive")
    pair_problem = _agent3_pair_problem_bytes(runs_data, progress_data)
    if pair_problem:
        raise ValueError("refusing to restore invalid Agent 3 bound authority pair: " + pair_problem)

    token = f"{os.getpid()}-{time.time_ns()}-{uuid.uuid4().hex}"
    runs_tmp = runs.path + f".restore-{token}.tmp"
    progress_tmp = progress.path + f".restore-{token}.tmp"
    fence = agent3_authority_restore_fence_path(runs.path)
    fence_tmp = fence + f".tmp-{token}"
    try:
        _write_durable_file(runs_tmp, runs_data)
        _write_durable_file(progress_tmp, progress_data)
        staged_problem = _agent3_pair_problem_path(runs_tmp, progress_tmp)
        if staged_problem:
            raise ValueError("staged Agent 3 authority pair failed verification: " + staged_problem)

        fence_payload = json.dumps(
            {
                "schema": 1,
                "runs_sha256": _sha256_bytes(runs_data),
                "progress_sha256": _sha256_bytes(progress_data),
                "created_ns": time.time_ns(),
            },
            sort_keys=True,
        ).encode("utf-8")
        _write_durable_file(fence_tmp, fence_payload)
        os.replace(fence_tmp, fence)

        # There is no portable primitive that replaces two arbitrary files in one
        # filesystem operation. The persistent fence is therefore the authority:
        # AgentRunStore refuses to open while either replacement may be partial.
        os.replace(runs_tmp, runs.path)
        os.replace(progress_tmp, progress.path)
        live_problem = _agent3_pair_problem_path(runs.path, progress.path)
        if live_problem:
            raise ValueError("restored Agent 3 authority pair failed verification: " + live_problem)
        os.remove(fence)
        restored.extend([runs.path, progress.path])
    finally:
        for leftover in (runs_tmp, progress_tmp, fence_tmp):
            try:
                os.remove(leftover)
            except FileNotFoundError:
                pass


'''
if member_anchor not in text:
    raise SystemExit("missing member sha anchor")
text = text.replace(member_anchor, member_insert, 1)

restore_targets = '''    manifest = _read_manifest(archive)\n    targets = {it.key: it for it in items()}\n\n    # Pre-flight: without --force, refuse if any destination already exists.\n'''
restore_targets_new = '''    manifest = _read_manifest(archive)\n    targets = {it.key: it for it in items()}\n    has_agent3_pair = (\n        AGENT3_RUNS_KEY in manifest["files"]\n        and AGENT3_EXECUTION_PROGRESS_KEY in manifest["files"]\n    )\n    restore_fence = agent3_authority_restore_fence_path(targets[AGENT3_RUNS_KEY].path)\n    if os.path.exists(restore_fence) and not has_agent3_pair:\n        raise RuntimeError(\n            "Agent 3 authority restore is already incomplete; repair requires a complete bound run/progress pair"\n        )\n\n    # Pre-flight: without --force, refuse if any destination already exists.\n'''
if restore_targets not in text:
    raise SystemExit("missing restore targets anchor")
text = text.replace(restore_targets, restore_targets_new, 1)

restore_loop = '''    restored: list[str] = []\n    with tarfile.open(archive, "r:gz") as tar:\n        for key, meta in manifest["files"].items():\n            it = targets.get(key)\n            if it is None:\n                continue  # older archives may contain keys not known here\n            if meta["kind"] == "file":\n                _extract_to(tar, f"data/{key}", it.path)\n                restored.append(it.path)\n            else:\n                os.makedirs(it.path, exist_ok=True)\n                for rel in meta["files"]:\n                    dest = os.path.join(it.path, rel)\n                    _extract_to(tar, f"data/{key}/{rel}", dest)\n                    restored.append(dest)\n    return {"restored": restored}\n'''
restore_loop_new = '''    restored: list[str] = []\n    with tarfile.open(archive, "r:gz") as tar:\n        if has_agent3_pair:\n            _restore_agent3_authority_pair(\n                tar,\n                targets[AGENT3_RUNS_KEY],\n                targets[AGENT3_EXECUTION_PROGRESS_KEY],\n                restored,\n            )\n        for key, meta in manifest["files"].items():\n            if has_agent3_pair and key in {AGENT3_RUNS_KEY, AGENT3_EXECUTION_PROGRESS_KEY}:\n                continue\n            it = targets.get(key)\n            if it is None:\n                continue  # older archives may contain keys not known here\n            if meta["kind"] == "file":\n                _extract_to(tar, f"data/{key}", it.path)\n                restored.append(it.path)\n            else:\n                os.makedirs(it.path, exist_ok=True)\n                for rel in meta["files"]:\n                    dest = os.path.join(it.path, rel)\n                    _extract_to(tar, f"data/{key}/{rel}", dest)\n                    restored.append(dest)\n    return {"restored": restored}\n'''
if restore_loop not in text:
    raise SystemExit("missing restore loop")
text = text.replace(restore_loop, restore_loop_new, 1)
backup_path.write_text(text, encoding="utf-8")

core_path = Path("worker/app/agent3/core.py")
core = core_path.read_text(encoding="utf-8")
core_anchor = 'from typing import Any, Callable, Iterable\n\n\nclass StrEnum(str, Enum):\n'
core_insert = '''from typing import Any, Callable, Iterable\n\n\nAGENT3_AUTHORITY_RESTORE_FENCE_SUFFIX = ".authority-restore-in-progress"\n\n\ndef agent3_authority_restore_fence_path(path: str) -> str:\n    return f"{path}{AGENT3_AUTHORITY_RESTORE_FENCE_SUFFIX}"\n\n\nclass StrEnum(str, Enum):\n'''
if core_anchor not in core:
    raise SystemExit("missing core import anchor")
core = core.replace(core_anchor, core_insert, 1)
init_anchor = '''class AgentRunStore:\n    def __init__(self, path: str):\n        Path(path).parent.mkdir(parents=True, exist_ok=True)\n'''
init_insert = '''class AgentRunStore:\n    def __init__(self, path: str):\n        if path != ":memory:":\n            fence = Path(agent3_authority_restore_fence_path(path))\n            if fence.exists():\n                raise RuntimeError(\n                    "Agent 3 authority restore is incomplete; refusing to open run/progress stores until the bound restore finishes"\n                )\n        Path(path).parent.mkdir(parents=True, exist_ok=True)\n'''
if init_anchor not in core:
    raise SystemExit("missing AgentRunStore init anchor")
core = core.replace(init_anchor, init_insert, 1)
core_path.write_text(core, encoding="utf-8")

# Current backup tests should expect the new writer schema while still exercising
# explicitly relabelled legacy schema fixtures.
test_path = Path("tests/worker_backup.py")
test = test_path.read_text(encoding="utf-8")
test = test.replace('manifest["schema"] == 3, "schema: execution-authority inventory writes schema 3"', 'manifest["schema"] == 4, "schema: bound execution-authority inventory writes schema 4"', 1)
test = test.replace('backup._read_manifest(empty)["schema"] == 3, "create: empty rig still emits current schema 3"', 'backup._read_manifest(empty)["schema"] == 4, "create: empty rig still emits current schema 4"', 1)
test_path.write_text(test, encoding="utf-8")

focused = Path("tests/worker_backup_pair_authority.py")
if focused.exists():
    raise SystemExit("focused P1m regression already exists")
focused.write_text(r'''from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile

_root = tempfile.mkdtemp(prefix="kaliv-backup-pair-authority-")
os.environ["KALIV_DATA_DIR"] = os.path.join(_root, "data-root")
os.environ["MODELRIG_DATA"] = os.path.join(_root, "backend", "modelrig-data.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_root, "notes")

from app import backup  # noqa: E402
from app.agent3.core import AgentRunStore, agent3_authority_restore_fence_path  # noqa: E402


def seed_pair(run_payload: str, progress_digest: str = "a" * 64) -> None:
    runs = next(it for it in backup.items() if it.key == backup.AGENT3_RUNS_KEY)
    progress = next(it for it in backup.items() if it.key == backup.AGENT3_EXECUTION_PROGRESS_KEY)
    os.makedirs(os.path.dirname(runs.path), exist_ok=True)
    for path in (runs.path, progress.path, agent3_authority_restore_fence_path(runs.path)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    con = sqlite3.connect(runs.path)
    con.execute(
        "CREATE TABLE agent_runs (id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
    )
    con.execute(
        "INSERT INTO agent_runs(id,state,payload,updated_at) VALUES(?,?,?,?)",
        ("pair-run", "running", run_payload, 1.0),
    )
    con.commit(); con.close()
    con = sqlite3.connect(progress.path)
    con.execute(
        "CREATE TABLE agent_execution_starts ("
        "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
        "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"
    )
    con.execute(
        "INSERT INTO agent_execution_starts(run_id,step_index,step_sha256,started_at) VALUES(?,?,?,?)",
        ("pair-run", 0, progress_digest, 1.0),
    )
    con.commit(); con.close()


def member_bytes(archive: str, key: str) -> bytes:
    with tarfile.open(archive, "r:gz") as tar:
        f = tar.extractfile(f"data/{key}")
        assert f is not None
        return f.read()


def replace_member(source: str, destination: str, key: str, data: bytes) -> None:
    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:
        for member in src.getmembers():
            f = src.extractfile(member)
            raw = f.read() if f else b""
            if member.name == f"data/{key}":
                raw = data
            if member.name == "manifest.json":
                manifest = json.loads(raw)
                manifest["files"][key]["sha256"] = hashlib.sha256(data).hexdigest()
                raw = json.dumps(manifest, indent=2, sort_keys=True).encode()
            out = tarfile.TarInfo(member.name)
            out.size = len(raw)
            dst.addfile(out, io.BytesIO(raw))


seed_pair('{"snapshot":"A"}')
archive_a = backup.create(os.path.join(_root, "backups-a"))
assert backup._read_manifest(archive_a)["schema"] == 4
assert backup.verify(archive_a)["ok"], backup.verify(archive_a)

seed_pair('{"snapshot":"B"}', "b" * 64)
archive_b = backup.create(os.path.join(_root, "backups-b"))
assert backup.verify(archive_b)["ok"], backup.verify(archive_b)

# Independently valid SQLite files plus independently updated manifest hashes are
# not enough. Mixing the B run snapshot with the A progress snapshot must fail
# their embedded shared snapshot attestation.
mixed = os.path.join(_root, "mixed-valid-pair.tar.gz")
replace_member(archive_a, mixed, backup.AGENT3_RUNS_KEY, member_bytes(archive_b, backup.AGENT3_RUNS_KEY))
mixed_result = backup.verify(mixed)
assert not mixed_result["ok"], mixed_result
assert any("bound authority pair" in item for item in mixed_result["problems"]), mixed_result

runs = next(it for it in backup.items() if it.key == backup.AGENT3_RUNS_KEY)
progress = next(it for it in backup.items() if it.key == backup.AGENT3_EXECUTION_PROGRESS_KEY)
fence = agent3_authority_restore_fence_path(runs.path)

# Force the failure window after the run DB replacement but before progress
# publication. The persistent fence must survive and prevent AgentRunStore from
# opening the mismatched authority until a complete retry repairs both files.
real_replace = backup.os.replace
failed = False

def fail_second_pair_replace(src: str, dst: str) -> None:
    global failed
    if dst == progress.path and ".restore-" in src and not failed:
        failed = True
        raise OSError("simulated second authority replacement failure")
    real_replace(src, dst)

backup.os.replace = fail_second_pair_replace
try:
    try:
        backup.restore(archive_a, force=True)
        raise AssertionError("partial pair restore unexpectedly succeeded")
    except OSError as exc:
        assert "simulated second authority replacement failure" in str(exc)
finally:
    backup.os.replace = real_replace

assert os.path.exists(fence), "partial pair restore must leave the fail-closed fence"
try:
    AgentRunStore(runs.path)
    raise AssertionError("AgentRunStore opened while pair restore fence was present")
except RuntimeError as exc:
    assert "restore is incomplete" in str(exc)

repaired = backup.restore(archive_a, force=True)
assert runs.path in repaired["restored"] and progress.path in repaired["restored"]
assert not os.path.exists(fence), "successful bound restore must remove the fence"
assert backup._agent3_pair_problem_path(runs.path, progress.path) is None
store = AgentRunStore(runs.path)
store._conn.close()
store._progress_conn.close()

print("P1m: bound Agent3 backup snapshots and failure-atomic restore fence passed")
''', encoding="utf-8")

print("applied P1m bound backup pair + restore fence fix")
