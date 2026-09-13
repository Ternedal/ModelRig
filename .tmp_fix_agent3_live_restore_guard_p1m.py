from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    if text.count(old) != 1:
        raise SystemExit(f"non-unique anchor {label}: {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# A tiny cross-process lease database gives us portable shared-runtime /
# exclusive-restore coordination without platform-specific file locking.
guard_path = Path("worker/app/agent3/runtime_restore_guard.py")
if guard_path.exists():
    raise SystemExit("runtime_restore_guard.py already exists")
guard_path.write_text(
    '''from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_GUARD_TABLE = "agent3_runtime_restore_guard"
_GUARD_SQL = (
    "CREATE TABLE agent3_runtime_restore_guard ("
    "id INTEGER PRIMARY KEY CHECK(id=1), "
    "restore_in_progress INTEGER NOT NULL CHECK(restore_in_progress IN (0,1)))"
)


def _guard_path(run_db_path: str) -> str:
    return f"{run_db_path}.runtime-restore-guard.db"


def _open_guard(run_db_path: str) -> sqlite3.Connection:
    path = _guard_path(run_db_path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
    try:
        try:
            row = con.execute(
                f"SELECT restore_in_progress FROM {_GUARD_TABLE} WHERE id=1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            con.execute(_GUARD_SQL)
            con.execute(
                f"INSERT INTO {_GUARD_TABLE}(id,restore_in_progress) VALUES(1,0)"
            )
            row = (0,)
        if row is None or int(row[0]) not in (0, 1):
            raise RuntimeError("Agent3 runtime/restore guard is corrupt")
        con.execute("PRAGMA busy_timeout=0")
        return con
    except Exception:
        con.close()
        raise


class Agent3RuntimeLease:
    """A long-lived shared SQLite read transaction owned by one runtime store."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._connection.in_transaction:
                self._connection.rollback()
        finally:
            self._connection.close()


class Agent3RestoreLease:
    """Exclusive restore lease plus a durable fail-closed incomplete marker."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._closed = False

    def complete(self) -> None:
        if self._closed:
            return
        try:
            self._connection.execute(
                f"UPDATE {_GUARD_TABLE} SET restore_in_progress=0 WHERE id=1"
            )
            self._connection.commit()
        finally:
            self._closed = True
            self._connection.close()

    def abort(self) -> None:
        if self._closed:
            return
        # restore_in_progress=1 was committed before the exclusive restore
        # transaction began. Rolling this transaction back therefore leaves the
        # durable marker set so a partial restore cannot boot Agent3.
        try:
            if self._connection.in_transaction:
                self._connection.rollback()
        finally:
            self._closed = True
            self._connection.close()


def acquire_agent3_runtime_lease(run_db_path: str) -> Agent3RuntimeLease:
    """Acquire shared runtime authority, refusing incomplete/active restore."""
    con = _open_guard(run_db_path)
    try:
        con.execute("BEGIN")
        row = con.execute(
            f"SELECT restore_in_progress FROM {_GUARD_TABLE} WHERE id=1"
        ).fetchone()
        if row != (0,):
            con.rollback()
            raise RuntimeError(
                "Agent3 restore is incomplete; rerun a verified restore before starting Agent3"
            )
        # Keep this read transaction open for the lifetime of AgentRunStore. In
        # rollback-journal mode it owns a SHARED lock, so BEGIN EXCLUSIVE in the
        # restore process cannot succeed while this runtime is alive.
        return Agent3RuntimeLease(con)
    except sqlite3.OperationalError as exc:
        try:
            if con.in_transaction:
                con.rollback()
        finally:
            con.close()
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 restore is in progress; runtime startup is blocked"
            ) from exc
        raise
    except Exception:
        try:
            if con.in_transaction:
                con.rollback()
        finally:
            con.close()
        raise


def acquire_agent3_restore_lease(run_db_path: str) -> Agent3RestoreLease:
    """Acquire exclusive restore authority or fail immediately if runtime is live."""
    con = _open_guard(run_db_path)
    try:
        # First exclusive transaction is deliberately non-blocking. Any live
        # AgentRunStore owns a shared transaction and makes this fail before a
        # single live restore destination is touched.
        con.execute("PRAGMA busy_timeout=0")
        con.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as exc:
        con.close()
        if "locked" in str(exc).lower():
            raise RuntimeError(
                "Agent3 runtime is active; stop the worker before restoring persistent state"
            ) from exc
        raise

    try:
        # Make restore intent durable BEFORE publishing anything. If the process
        # crashes later, fresh Agent3 startup sees this marker and fails closed.
        con.execute(
            f"UPDATE {_GUARD_TABLE} SET restore_in_progress=1 WHERE id=1"
        )
        con.commit()

        # New runtime attempts now read marker=1 and immediately retire. Give
        # those brief probes room to release their read lock, then hold EXCLUSIVE
        # for the entire restore so no runtime can enter mid-publication.
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("BEGIN EXCLUSIVE")
        row = con.execute(
            f"SELECT restore_in_progress FROM {_GUARD_TABLE} WHERE id=1"
        ).fetchone()
        if row != (1,):
            raise RuntimeError("Agent3 restore guard lost its durable marker")
        return Agent3RestoreLease(con)
    except Exception:
        try:
            if con.in_transaction:
                con.rollback()
        finally:
            con.close()
        # The committed marker intentionally remains 1 on every failure after
        # restore authority was acquired.
        raise


@contextmanager
def agent3_restore_guard(run_db_path: str) -> Iterator[None]:
    lease = acquire_agent3_restore_lease(run_db_path)
    try:
        yield
    except BaseException:
        lease.abort()
        raise
    else:
        lease.complete()
''',
    encoding="utf-8",
)

core = Path("worker/app/agent3/core.py")
replace_once(
    core,
    "from typing import Any, Callable, Iterable\n\n\nclass StrEnum",
    "from typing import Any, Callable, Iterable\n\nfrom .runtime_restore_guard import acquire_agent3_runtime_lease\n\n\nclass StrEnum",
    "core import",
)
old_init = '''class AgentRunStore:\n    def __init__(self, path: str):\n        Path(path).parent.mkdir(parents=True, exist_ok=True)\n        self._lock = threading.RLock()\n        self._conn = sqlite3.connect(path, check_same_thread=False)\n        self._conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_runs ("\n            "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"\n        )\n        self._conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_events ("\n            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "\n            "kind TEXT NOT NULL, payload TEXT NOT NULL)"\n        )\n        self._conn.commit()\n\n        # Execution-start evidence deliberately lives in a separate SQLite file.\n        # A stale/partially-restored agent_runs payload must never be able to roll\n        # this watermark backwards and make a side effect look PENDING again.\n        progress_path = ":memory:" if path == ":memory:" else f"{path}.execution-progress"\n        self._progress_conn = sqlite3.connect(progress_path, check_same_thread=False)\n        self._progress_conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_execution_starts ("\n            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n            "started_at REAL NOT NULL, "\n            "PRIMARY KEY(run_id,step_index,step_sha256))"\n        )\n        self._progress_conn.commit()\n'''
new_init = '''class AgentRunStore:\n    def __init__(self, path: str):\n        Path(path).parent.mkdir(parents=True, exist_ok=True)\n        self._lock = threading.RLock()\n        self._runtime_restore_lease = None\n        if path != ":memory:":\n            # Acquire cross-process runtime authority before opening either live\n            # SQLite store. A restore-in-progress/incomplete marker therefore\n            # blocks startup even when runs_path currently contains the durable\n            # non-SQLite restore fence.\n            self._runtime_restore_lease = acquire_agent3_runtime_lease(path)\n        try:\n            self._conn = sqlite3.connect(path, check_same_thread=False)\n            self._conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_runs ("\n                "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"\n            )\n            self._conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_events ("\n                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "\n                "kind TEXT NOT NULL, payload TEXT NOT NULL)"\n            )\n            self._conn.commit()\n\n            # Execution-start evidence deliberately lives in a separate SQLite file.\n            # A stale/partially-restored agent_runs payload must never be able to roll\n            # this watermark backwards and make a side effect look PENDING again.\n            progress_path = ":memory:" if path == ":memory:" else f"{path}.execution-progress"\n            self._progress_conn = sqlite3.connect(progress_path, check_same_thread=False)\n            self._progress_conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_execution_starts ("\n                "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n                "started_at REAL NOT NULL, "\n                "PRIMARY KEY(run_id,step_index,step_sha256))"\n            )\n            self._progress_conn.commit()\n        except Exception:\n            progress = getattr(self, "_progress_conn", None)\n            if progress is not None:\n                progress.close()\n            connection = getattr(self, "_conn", None)\n            if connection is not None:\n                connection.close()\n            if self._runtime_restore_lease is not None:\n                self._runtime_restore_lease.close()\n                self._runtime_restore_lease = None\n            raise\n'''
replace_once(core, old_init, new_init, "AgentRunStore init")
close_anchor = '''            if run.current_step == step_index:\n                if step.state in {StepState.APPROVED, StepState.WAITING_CONFIRMATION}:\n                    return False\n                if step.state == StepState.PENDING and not step.idempotent:\n                    return False\n        return True\n\n    def save(self, run: AgentRun) -> None:\n'''
close_replacement = '''            if run.current_step == step_index:\n                if step.state in {StepState.APPROVED, StepState.WAITING_CONFIRMATION}:\n                    return False\n                if step.state == StepState.PENDING and not step.idempotent:\n                    return False\n        return True\n\n    def close(self) -> None:\n        """Release both authority stores and the process-wide restore lease."""\n        with self._lock:\n            progress = getattr(self, "_progress_conn", None)\n            if progress is not None:\n                progress.close()\n                self._progress_conn = None\n            connection = getattr(self, "_conn", None)\n            if connection is not None:\n                connection.close()\n                self._conn = None\n            lease = self._runtime_restore_lease\n            if lease is not None:\n                lease.close()\n                self._runtime_restore_lease = None\n\n    def save(self, run: AgentRun) -> None:\n'''
replace_once(core, close_anchor, close_replacement, "AgentRunStore close")

backup = Path("worker/app/backup.py")
replace_once(
    backup,
    "from . import paths as _paths  # noqa: E402\nfrom . import tools as _tools  # noqa: E402",
    "from . import paths as _paths  # noqa: E402\nfrom . import tools as _tools  # noqa: E402\nfrom .agent3.runtime_restore_guard import agent3_restore_guard  # noqa: E402",
    "backup guard import",
)
restore_header = '''def restore(archive: str, force: bool = False) -> dict:\n    """Restore an archive after complete verification.\n'''
restore_wrapper = '''def restore(archive: str, force: bool = False) -> dict:\n    """Restore only while Agent3 runtime is quiescent.\n\n    Verification and the normal no-clobber preflight happen before restore\n    authority is acquired. Once the exclusive guard is entered, any failure\n    leaves a durable incomplete marker so no Agent3 runtime can boot against\n    partially restored cross-store state. A successful complete retry clears it.\n    """\n    check = verify(archive)\n    if not check["ok"]:\n        raise ValueError(\n            f"archive failed verification, refusing to restore: {check['problems']}"\n        )\n    manifest = _read_manifest(archive)\n    targets = {item.key: item for item in items()}\n    files = manifest["files"]\n    if not force:\n        clashes = []\n        for key in files:\n            item = targets.get(key)\n            if item and os.path.exists(item.path):\n                clashes.append(item.path)\n        if clashes:\n            raise FileExistsError(\n                "these already exist (use --force to overwrite): " + ", ".join(clashes)\n            )\n\n    run_path = targets[AGENT3_RUNS_KEY].path\n    with agent3_restore_guard(run_path):\n        return _restore_under_runtime_guard(archive, force=force)\n\n\ndef _restore_under_runtime_guard(archive: str, force: bool = False) -> dict:\n    """Restore an archive after complete verification.\n'''
replace_once(backup, restore_header, restore_wrapper, "restore wrapper")

# Tests exercise both directions of the lease and the durable failed-restore marker.
test = Path("tests/worker_backup.py")
replace_once(
    test,
    "from app import backup  # noqa: E402\n",
    "from app import backup  # noqa: E402\nfrom app.agent3.core import AgentRunStore  # noqa: E402\n",
    "backup test import",
)
forced_anchor = '''forced = backup.restore(archive, force=True)\ncheck(len(forced["restored"]) == len(before), "restore --force: overwrites cleanly")\n\n# Paired restore is failure-atomic from Agent3's point of view. Inject a failure\n'''
forced_replacement = '''forced = backup.restore(archive, force=True)\ncheck(len(forced["restored"]) == len(before), "restore --force: overwrites cleanly")\n\n# A live AgentRunStore owns a shared runtime lease. Restore must fail before any\n# destination is touched instead of relying on os.replace against open SQLite\n# handles (which is unsafe on Unix and may fail differently on Windows).\nlive_store = AgentRunStore(runs_item.path)\nlive_before = snapshot()\ntry:\n    backup.restore(archive, force=True)\n    check(False, "restore guard: live Agent3 runtime is refused")\nexcept RuntimeError as exc:\n    check(\n        "runtime is active" in str(exc),\n        "restore guard: live Agent3 runtime is refused before publication",\n    )\nfinally:\n    live_store.close()\ncheck(\n    snapshot() == live_before,\n    "restore guard: live-runtime refusal writes NOTHING to portable state",\n)\nforced_after_close = backup.restore(archive, force=True)\ncheck(\n    len(forced_after_close["restored"]) == len(before),\n    "restore guard: restore succeeds after AgentRunStore closes its lease",\n)\n\n# Paired restore is failure-atomic from Agent3's point of view. Inject a failure\n'''
replace_once(test, forced_anchor, forced_replacement, "live restore test")
fence_anchor = '''check(\n    snapshot()[backup.AGENT3_EXECUTION_PROGRESS_KEY] == progress_before_failure,\n    "restore fence: failed second publish did not replace live progress authority",\n)\ntry:\n    fenced = sqlite3.connect(runs_item.path)\n'''
fence_replacement = '''check(\n    snapshot()[backup.AGENT3_EXECUTION_PROGRESS_KEY] == progress_before_failure,\n    "restore fence: failed second publish did not replace live progress authority",\n)\ntry:\n    AgentRunStore(runs_item.path)\n    check(False, "restore guard: failed restore blocks fresh Agent3 startup")\nexcept RuntimeError as exc:\n    check(\n        "restore is incomplete" in str(exc),\n        "restore guard: failed restore leaves durable startup blocker",\n    )\ntry:\n    fenced = sqlite3.connect(runs_item.path)\n'''
replace_once(test, fence_anchor, fence_replacement, "failed restore marker test")
retry_anchor = '''check(\n    backup._agent3_runs_row_count_path(runs_item.path)[1] is None\n    and backup._execution_progress_problem_path(progress_item.path) is None,\n    "restore fence: retry removes the fence and restores canonical live authority",\n)\n\n# A valid progress sidecar without its paired run store is unsafe source state.\n'''
retry_replacement = '''check(\n    backup._agent3_runs_row_count_path(runs_item.path)[1] is None\n    and backup._execution_progress_problem_path(progress_item.path) is None,\n    "restore fence: retry removes the fence and restores canonical live authority",\n)\nprobe_store = AgentRunStore(runs_item.path)\nprobe_store.close()\ncheck(True, "restore guard: successful retry clears durable startup blocker")\n\n# A failure AFTER the Agent3 pair itself has published must still block startup:\n# otherwise a valid run/progress pair could boot beside only partially restored\n# plan/review/approval state. The persistent guard spans the complete archive.\naudit_item = next(it for it in backup.items() if it.key == "audit.db")\nreal_replace = backup.os.replace\n\ndef fail_unrelated_publish(source, destination):\n    if (\n        os.path.abspath(destination) == os.path.abspath(audit_item.path)\n        and str(source).endswith(".tmp")\n    ):\n        raise OSError("injected unrelated-store publication failure")\n    return real_replace(source, destination)\n\nbackup.os.replace = fail_unrelated_publish\ntry:\n    try:\n        backup.restore(archive, force=True)\n        check(False, "restore guard: post-pair unrelated publication failure propagates")\n    except OSError:\n        check(True, "restore guard: post-pair unrelated publication failure propagates")\nfinally:\n    backup.os.replace = real_replace\ncheck(\n    backup._agent3_runs_row_count_path(runs_item.path)[1] is None,\n    "restore guard: post-pair failure may leave a valid run DB path",\n)\ntry:\n    AgentRunStore(runs_item.path)\n    check(False, "restore guard: partial whole-archive restore cannot boot Agent3")\nexcept RuntimeError as exc:\n    check(\n        "restore is incomplete" in str(exc),\n        "restore guard: durable marker blocks valid-looking partial whole-archive state",\n    )\nbackup.restore(archive, force=True)\npost_failure_store = AgentRunStore(runs_item.path)\npost_failure_store.close()\ncheck(True, "restore guard: complete retry re-authorizes Agent3 startup")\n\n# A valid progress sidecar without its paired run store is unsafe source state.\n'''
replace_once(test, retry_anchor, retry_replacement, "post-pair failure test")

docs = Path("scripts/BACKUP.md")
docs_anchor = '''scripts\\kaliv-backup.bat restore FILE /f REM restore, overwriting live data\n```\n\nSchedule a daily 03:00 backup (run once, elevated):\n'''
docs_replacement = '''scripts\\kaliv-backup.bat restore FILE /f REM restore, overwriting live data\n```\n\nRestore is intentionally offline for Agent 3. A running `AgentRunStore` holds a\nshared runtime lease, so restore refuses before touching live state until the\nworker is stopped. Restore then commits a durable `restore_in_progress` guard\nbefore publication and clears it only after the complete archive succeeds. If a\nrestore is interrupted or fails after publication begins, Agent 3 startup remains\nblocked until a complete verified retry finishes; this prevents a valid-looking\nrun database from booting beside only partially restored companion stores.\n\nSchedule a daily 03:00 backup (run once, elevated):\n'''
replace_once(docs, docs_anchor, docs_replacement, "backup docs")

print("applied P1m live restore guard")
