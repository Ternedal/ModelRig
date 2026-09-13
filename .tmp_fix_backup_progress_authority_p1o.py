from pathlib import Path

backup_path = Path("worker/app/backup.py")
text = backup_path.read_text(encoding="utf-8")

old_imports = "import os\nimport sys\nimport tarfile\nimport time\nfrom dataclasses import dataclass\nfrom typing import Optional\n"
new_imports = "import os\nimport sqlite3\nimport sys\nimport tarfile\nimport tempfile\nimport time\nfrom dataclasses import dataclass\nfrom pathlib import Path\nfrom typing import Optional\n"
if old_imports not in text:
    raise SystemExit("backup import anchor missing")
text = text.replace(old_imports, new_imports, 1)

walk_anchor = '''def _walk(path: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(path):
        for fn in sorted(files):
            out.append(os.path.join(root, fn))
    return sorted(out)


def _agent3_authority_problem(files: dict) -> Optional[str]:
    if AGENT3_RUNS_KEY in files and AGENT3_EXECUTION_PROGRESS_KEY not in files:
        return (
            "Agent 3 run state is present without execution-progress authority; "
            "restoring it could replay a previously-started non-idempotent step"
        )
    return None
'''
helpers = '''def _walk(path: str) -> list[str]:
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
    return _sqlite_table_problem(
        path,
        table="agent_execution_starts",
        required={
            "run_id": ("TEXT", 1, 1),
            "step_index": ("INTEGER", 1, 2),
            "step_sha256": ("TEXT", 1, 3),
            "started_at": ("REAL", 1, 0),
        },
    )


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
'''
if walk_anchor not in text:
    raise SystemExit("backup helper anchor missing")
text = text.replace(walk_anchor, helpers, 1)

create_anchor = '''    runs = by_key[AGENT3_RUNS_KEY]
    progress = by_key[AGENT3_EXECUTION_PROGRESS_KEY]
    if os.path.exists(runs.path) and not os.path.exists(progress.path):
        raise ValueError(
            "refusing to back up Agent 3 runs without the execution-progress sidecar: "
            + progress.path
        )

    manifest: dict = {"schema": BACKUP_SCHEMA, "created": stamp, "files": {}}
'''
create_replacement = '''    runs = by_key[AGENT3_RUNS_KEY]
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
'''
if create_anchor not in text:
    raise SystemExit("backup create anchor missing")
text = text.replace(create_anchor, create_replacement, 1)

verify_anchor = '''    problems: list[str] = []
    authority_problem = _agent3_authority_problem(manifest.get("files", {}))
    if authority_problem:
        problems.append(authority_problem)

    checked = 0
    with tarfile.open(archive, "r:gz") as tar:
        for key, meta in manifest["files"].items():
'''
verify_replacement = '''    files = manifest.get("files", {})
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
'''
if verify_anchor not in text:
    raise SystemExit("backup verify anchor missing")
text = text.replace(verify_anchor, verify_replacement, 1)

backup_path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Regression coverage
# ---------------------------------------------------------------------------
test_path = Path("tests/worker_backup.py")
test = test_path.read_text(encoding="utf-8")

seed_anchor = '''def _seed_sqlite(path: str, key: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    if key == "rag.db":
        con.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT)")
        con.executemany(
            "INSERT INTO docs (body) VALUES (?)",
            [("chunk %d" % i,) for i in range(200)],
        )
    else:
        con.execute("CREATE TABLE state (name TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO state(name, value) VALUES (?, ?)", (key, "seeded"))
    con.commit()
    con.close()
'''
seed_replacement = '''def _seed_sqlite(path: str, key: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    if key == "rag.db":
        con.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT)")
        con.executemany(
            "INSERT INTO docs (body) VALUES (?)",
            [("chunk %d" % i,) for i in range(200)],
        )
    elif key == backup.AGENT3_RUNS_KEY:
        con.execute(
            "CREATE TABLE agent_runs ("
            "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        con.execute(
            "INSERT INTO agent_runs(id,state,payload,updated_at) VALUES(?,?,?,?)",
            ("backup-run", "running", "{}", 1.0),
        )
    elif key == backup.AGENT3_EXECUTION_PROGRESS_KEY:
        con.execute(
            "CREATE TABLE agent_execution_starts ("
            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
            "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"
        )
        con.execute(
            "INSERT INTO agent_execution_starts(run_id,step_index,step_sha256,started_at) "
            "VALUES(?,?,?,?)",
            ("backup-run", 0, "a" * 64, 1.0),
        )
    else:
        con.execute("CREATE TABLE state (name TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO state(name, value) VALUES (?, ?)", (key, "seeded"))
    con.commit()
    con.close()
'''
if seed_anchor not in test:
    raise SystemExit("backup test seed anchor missing")
test = test.replace(seed_anchor, seed_replacement, 1)

archive_sig = 'def archive_with_schema(source: str, destination: str, schema: int, drop_keys=()) -> None:\n'
if archive_sig not in test:
    raise SystemExit("backup archive helper signature missing")
test = test.replace(
    archive_sig,
    'def archive_with_schema(\n    source: str,\n    destination: str,\n    schema: int,\n    drop_keys=(),\n    replace_files=None,\n) -> None:\n',
    1,
)
test = test.replace(
    '    drop_keys = set(drop_keys)\n    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:\n',
    '    drop_keys = set(drop_keys)\n    replace_files = dict(replace_files or {})\n    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:\n',
    1,
)
test = test.replace(
    '            data = extracted.read() if extracted else b""\n            if member.name == "manifest.json":\n',
    '            data = extracted.read() if extracted else b""\n            data_key = member.name.removeprefix("data/") if member.name.startswith("data/") else None\n            if data_key in replace_files:\n                data = replace_files[data_key]\n            if member.name == "manifest.json":\n',
    1,
)
test = test.replace(
    '                for key in drop_keys:\n                    manifest["files"].pop(key, None)\n                data = json.dumps(manifest, indent=2, sort_keys=True).encode()\n',
    '                for key in drop_keys:\n                    manifest["files"].pop(key, None)\n                for key, replacement in replace_files.items():\n                    if key in manifest["files"]:\n                        manifest["files"][key]["sha256"] = hashlib.sha256(replacement).hexdigest()\n                data = json.dumps(manifest, indent=2, sort_keys=True).encode()\n',
    1,
)

unsafe_anchor = '''check(snapshot() == pre_unsafe_restore, "restore: unsafe legacy refusal writes NOTHING")

future = os.path.join(_root, "unsupported-schema.tar.gz")
'''
unsafe_insert = '''check(snapshot() == pre_unsafe_restore, "restore: unsafe legacy refusal writes NOTHING")

# A sidecar whose bytes hash correctly but which is not the execution-authority
# SQLite schema must still fail verification. Hashes prove transport integrity,
# not authority semantics.
invalid_progress = os.path.join(_root, "invalid-execution-progress.tar.gz")
archive_with_schema(
    archive,
    invalid_progress,
    3,
    replace_files={backup.AGENT3_EXECUTION_PROGRESS_KEY: b""},
)
invalid_progress_verify = backup.verify(invalid_progress)
check(
    not invalid_progress_verify["ok"],
    "verify: empty execution-progress sidecar is refused even when its manifest hash matches",
)
check(
    any("execution-progress authority" in problem for problem in invalid_progress_verify["problems"]),
    "verify: invalid execution-progress sidecar names the authority failure",
)
pre_invalid_restore = snapshot()
try:
    backup.restore(invalid_progress, force=True)
    check(False, "restore: invalid execution-progress authority is refused")
except ValueError:
    check(True, "restore: invalid execution-progress authority is refused")
check(snapshot() == pre_invalid_restore, "restore: invalid authority refusal writes NOTHING")

future = os.path.join(_root, "unsupported-schema.tar.gz")
'''
if unsafe_anchor not in test:
    raise SystemExit("backup unsafe test anchor missing")
test = test.replace(unsafe_anchor, unsafe_insert, 1)

missing_anchor = '''# A run database without its execution authority must never produce a new backup.
wipe()
_seed_sqlite(runs_item.path, runs_item.key)
try:
    backup.create(os.path.join(_root, "missing-progress"))
    check(False, "create: Agent3 runs without execution-progress sidecar are refused")
except ValueError:
    check(True, "create: Agent3 runs without execution-progress sidecar are refused")
wipe()

# An empty rig is still a valid backup.
'''
missing_replacement = '''# A malformed execution sidecar must be refused before a backup is created.
wipe()
_seed_sqlite(runs_item.path, runs_item.key)
os.makedirs(os.path.dirname(progress_item.path), exist_ok=True)
with open(progress_item.path, "wb") as f:
    f.write(b"")
try:
    backup.create(os.path.join(_root, "invalid-progress-create"))
    check(False, "create: invalid execution-progress authority is refused")
except ValueError:
    check(True, "create: invalid execution-progress authority is refused")
wipe()

# A non-empty run database without its execution authority must never produce a new backup.
_seed_sqlite(runs_item.path, runs_item.key)
try:
    backup.create(os.path.join(_root, "missing-progress"))
    check(False, "create: Agent3 runs without execution-progress sidecar are refused")
except ValueError:
    check(True, "create: Agent3 runs without execution-progress sidecar are refused")
wipe()

# Legacy schema 1/2 archives may legitimately contain an initialized but empty
# Agent3 run store: no execution has crossed the boundary, so no progress
# sidecar authority exists yet and no replay risk is introduced.
os.makedirs(os.path.dirname(runs_item.path), exist_ok=True)
con = sqlite3.connect(runs_item.path)
con.execute(
    "CREATE TABLE agent_runs ("
    "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
)
con.commit()
con.close()
empty_runs_archive = backup.create(os.path.join(_root, "empty-agent3-runs"))
check(
    backup.verify(empty_runs_archive)["ok"],
    "create: initialized empty Agent3 run store does not require a progress sidecar",
)
legacy_empty_runs = os.path.join(_root, "legacy-schema-2-empty-agent3-runs.tar.gz")
archive_with_schema(empty_runs_archive, legacy_empty_runs, 2)
check(
    backup.verify(legacy_empty_runs)["ok"],
    "schema: legacy empty Agent3 run store remains compatible without a progress sidecar",
)
wipe()

# An empty rig is still a valid backup.
'''
if missing_anchor not in test:
    raise SystemExit("backup missing-progress test anchor missing")
test = test.replace(missing_anchor, missing_replacement, 1)

test_path.write_text(test, encoding="utf-8")
print("applied backup execution-authority P1/P2 fix")
