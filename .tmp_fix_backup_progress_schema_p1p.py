from pathlib import Path

backup_path = Path("worker/app/backup.py")
text = backup_path.read_text(encoding="utf-8")

old = '''def _execution_progress_problem_path(path: str) -> Optional[str]:
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
'''
new = '''def _execution_progress_problem_path(path: str) -> Optional[str]:
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

    # This sidecar is a dedicated execution-authority database, not a general
    # extension point. Column/PK checks alone are insufficient: SQLite triggers
    # can silently erase a just-inserted watermark while integrity_check remains
    # "ok". Fail closed unless the complete user-defined schema is exactly the
    # canonical watermark table and exactly its four visible columns.
    try:
        con = _readonly_sqlite(path)
    except sqlite3.Error as exc:
        return f"cannot open SQLite database: {exc}"
    try:
        try:
            schema_rows = list(
                con.execute(
                    "SELECT type,name,tbl_name FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
                )
            )
            column_rows = list(con.execute("PRAGMA table_xinfo(agent_execution_starts)"))
        except sqlite3.Error as exc:
            return f"cannot inspect SQLite execution-authority schema: {exc}"

        expected_schema = [("table", "agent_execution_starts", "agent_execution_starts")]
        if schema_rows != expected_schema:
            rendered = [f"{row[0]}:{row[1]}->{row[2]}" for row in schema_rows]
            return (
                "execution-progress database has unexpected user-defined schema objects: "
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
'''
if old not in text:
    raise SystemExit("execution-progress validation anchor missing")
text = text.replace(old, new, 1)
backup_path.write_text(text, encoding="utf-8")


test_path = Path("tests/worker_backup.py")
test = test_path.read_text(encoding="utf-8")

archive_anchor = '''def archive_with_schema(
    source: str,
    destination: str,
    schema: int,
    drop_keys=(),
    replace_files=None,
) -> None:
'''
if archive_anchor not in test:
    raise SystemExit("archive helper anchor missing")

# Add a helper immediately before inventory tests.
insert_anchor = '''

# --- inventory --------------------------------------------------------------
'''
helper = '''

def execution_progress_bytes_with_erasing_trigger() -> bytes:
    fd, path = tempfile.mkstemp(prefix="kaliv-trigger-progress-", suffix=".db")
    os.close(fd)
    try:
        _seed_sqlite(path, backup.AGENT3_EXECUTION_PROGRESS_KEY)
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TRIGGER erase_execution_start AFTER INSERT ON agent_execution_starts "
            "BEGIN DELETE FROM agent_execution_starts "
            "WHERE run_id=NEW.run_id AND step_index=NEW.step_index "
            "AND step_sha256=NEW.step_sha256; END"
        )
        con.commit()
        con.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


# --- inventory --------------------------------------------------------------
'''
if insert_anchor not in test:
    raise SystemExit("inventory insertion anchor missing")
test = test.replace(insert_anchor, helper, 1)

invalid_anchor = '''check(snapshot() == pre_invalid_restore, "restore: invalid authority refusal writes NOTHING")

future = os.path.join(_root, "unsupported-schema.tar.gz")
'''
trigger_tests = '''check(snapshot() == pre_invalid_restore, "restore: invalid authority refusal writes NOTHING")

# A syntactically valid sidecar can still be unsafe if extra schema objects can
# mutate watermark semantics. In particular, an AFTER INSERT trigger can erase
# the just-inserted execution marker while all expected columns/PKs and
# integrity_check remain valid. The dedicated authority DB therefore admits no
# user-defined object other than the canonical table.
trigger_progress_bytes = execution_progress_bytes_with_erasing_trigger()
trigger_progress = os.path.join(_root, "trigger-execution-progress.tar.gz")
archive_with_schema(
    archive,
    trigger_progress,
    3,
    replace_files={backup.AGENT3_EXECUTION_PROGRESS_KEY: trigger_progress_bytes},
)
trigger_verify = backup.verify(trigger_progress)
check(
    not trigger_verify["ok"],
    "verify: trigger-bearing execution-progress sidecar is refused with matching manifest hash",
)
check(
    any("unexpected user-defined schema objects" in problem for problem in trigger_verify["problems"]),
    "verify: trigger-bearing sidecar names the closed-schema authority failure",
)
pre_trigger_restore = snapshot()
try:
    backup.restore(trigger_progress, force=True)
    check(False, "restore: trigger-bearing execution-progress authority is refused")
except ValueError:
    check(True, "restore: trigger-bearing execution-progress authority is refused")
check(
    snapshot() == pre_trigger_restore,
    "restore: trigger-bearing authority refusal writes NOTHING",
)

future = os.path.join(_root, "unsupported-schema.tar.gz")
'''
if invalid_anchor not in test:
    raise SystemExit("invalid authority regression anchor missing")
test = test.replace(invalid_anchor, trigger_tests, 1)

create_anchor = '''# A non-empty run database without its execution authority must never produce a new backup.
_seed_sqlite(runs_item.path, runs_item.key)
'''
create_trigger = '''# A structurally correct live sidecar with an erasing trigger must also be
# rejected before create can publish a backup.
_seed_sqlite(runs_item.path, runs_item.key)
os.makedirs(os.path.dirname(progress_item.path), exist_ok=True)
with open(progress_item.path, "wb") as f:
    f.write(trigger_progress_bytes)
try:
    backup.create(os.path.join(_root, "trigger-progress-create"))
    check(False, "create: trigger-bearing execution-progress authority is refused")
except ValueError:
    check(True, "create: trigger-bearing execution-progress authority is refused")
wipe()

# A non-empty run database without its execution authority must never produce a new backup.
_seed_sqlite(runs_item.path, runs_item.key)
'''
if create_anchor not in test:
    raise SystemExit("create trigger regression anchor missing")
test = test.replace(create_anchor, create_trigger, 1)

test_path.write_text(test, encoding="utf-8")
print("applied closed execution-progress schema P1p fix")
