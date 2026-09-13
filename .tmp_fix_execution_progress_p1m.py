from pathlib import Path

backup_path = Path("worker/app/backup.py")
text = backup_path.read_text(encoding="utf-8")
text = text.replace(
    '"SELECT type,name,tbl_name FROM sqlite_master "',
    '"SELECT type,name,tbl_name,sql FROM sqlite_master "',
    1,
)
old = '''        expected_schema = [("table", "agent_execution_starts", "agent_execution_starts")]
        if schema_rows != expected_schema:
            rendered = [f"{row[0]}:{row[1]}->{row[2]}" for row in schema_rows]
            return (
                "execution-progress database has unexpected user-defined schema objects: "
                + (", ".join(rendered) if rendered else "none")
            )

        expected_columns = [
'''
new = '''        expected_schema = [("table", "agent_execution_starts", "agent_execution_starts")]
        schema_objects = [(str(row[0]), str(row[1]), str(row[2])) for row in schema_rows]
        if schema_objects != expected_schema:
            rendered = [f"{row[0]}:{row[1]}->{row[2]}" for row in schema_rows]
            return (
                "execution-progress database has unexpected user-defined schema objects: "
                + (", ".join(rendered) if rendered else "none")
            )

        # sqlite_master.sql is execution authority too. table_xinfo cannot expose
        # inline CHECK/UNIQUE/FOREIGN KEY clauses, and INSERT OR IGNORE means a
        # hostile CHECK can silently suppress every watermark while preserving
        # the expected columns and PK. Accept only the exact table definition
        # emitted by AgentRunStore for this dedicated sidecar.
        expected_create_sql = (
            "CREATE TABLE agent_execution_starts ("
            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
            "started_at REAL NOT NULL, PRIMARY KEY(run_id,step_index,step_sha256))"
        )
        actual_create_sql = " ".join(str(schema_rows[0][3] or "").split())
        if actual_create_sql != expected_create_sql:
            return "execution-progress table does not match the canonical CREATE TABLE authority"

        expected_columns = [
'''
if old not in text:
    raise SystemExit("backup schema anchor not found")
text = text.replace(old, new, 1)
backup_path.write_text(text, encoding="utf-8")

test_path = Path("tests/worker_backup.py")
test = test_path.read_text(encoding="utf-8")
anchor = '''def execution_progress_bytes_with_erasing_trigger() -> bytes:
'''
idx = test.find(anchor)
if idx < 0:
    raise SystemExit("trigger helper anchor not found")
# Insert the CHECK helper after the existing trigger helper, immediately before inventory.
marker = '''\n\n# --- inventory --------------------------------------------------------------\n'''
pos = test.find(marker, idx)
if pos < 0:
    raise SystemExit("inventory marker not found")
helper = r'''


def execution_progress_bytes_with_rejecting_check() -> bytes:
    fd, path = tempfile.mkstemp(prefix="kaliv-check-progress-", suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE agent_execution_starts ("
            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "
            "started_at REAL NOT NULL, "
            "PRIMARY KEY(run_id,step_index,step_sha256), CHECK(0))"
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
'''
test = test[:pos] + helper + test[pos:]

trigger_end = '''check(
    snapshot() == pre_trigger_restore,
    "restore: trigger-bearing authority refusal writes NOTHING",
)

future = os.path.join(_root, "unsupported-schema.tar.gz")
'''
constraint_block = '''check(
    snapshot() == pre_trigger_restore,
    "restore: trigger-bearing authority refusal writes NOTHING",
)

# Inline constraints are part of execution authority even though they do not
# appear as separate sqlite_master objects and table_xinfo exposes the same
# visible columns/PK. CHECK(0) combined with INSERT OR IGNORE can silently drop
# every execution watermark, so only the canonical CREATE TABLE SQL is accepted.
check_progress_bytes = execution_progress_bytes_with_rejecting_check()
check_progress = os.path.join(_root, "check-constrained-execution-progress.tar.gz")
archive_with_schema(
    archive,
    check_progress,
    3,
    replace_files={backup.AGENT3_EXECUTION_PROGRESS_KEY: check_progress_bytes},
)
check_verify = backup.verify(check_progress)
check(
    not check_verify["ok"],
    "verify: CHECK-constrained execution-progress sidecar is refused with matching manifest hash",
)
check(
    any("canonical CREATE TABLE authority" in problem for problem in check_verify["problems"]),
    "verify: inline constraint failure names canonical table authority",
)
pre_check_restore = snapshot()
try:
    backup.restore(check_progress, force=True)
    check(False, "restore: CHECK-constrained execution-progress authority is refused")
except ValueError:
    check(True, "restore: CHECK-constrained execution-progress authority is refused")
check(
    snapshot() == pre_check_restore,
    "restore: CHECK-constrained authority refusal writes NOTHING",
)

future = os.path.join(_root, "unsupported-schema.tar.gz")
'''
if trigger_end not in test:
    raise SystemExit("trigger regression insertion anchor not found")
test = test.replace(trigger_end, constraint_block, 1)

create_anchor = '''# A non-empty run database without its execution authority must never produce a new backup.
'''
create_block = '''# A structurally correct live sidecar with an inline constraint that suppresses
# watermark insertion must be rejected before create can publish a backup.
_seed_sqlite(runs_item.path, runs_item.key)
os.makedirs(os.path.dirname(progress_item.path), exist_ok=True)
with open(progress_item.path, "wb") as f:
    f.write(check_progress_bytes)
try:
    backup.create(os.path.join(_root, "check-progress-create"))
    check(False, "create: CHECK-constrained execution-progress authority is refused")
except ValueError:
    check(True, "create: CHECK-constrained execution-progress authority is refused")
wipe()

# A non-empty run database without its execution authority must never produce a new backup.
'''
if create_anchor not in test:
    raise SystemExit("create regression insertion anchor not found")
test = test.replace(create_anchor, create_block, 1)
test_path.write_text(test, encoding="utf-8")
print("applied P1m canonical CREATE TABLE authority fix")
