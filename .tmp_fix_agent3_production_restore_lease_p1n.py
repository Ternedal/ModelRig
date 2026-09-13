from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one anchor, got {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


core = Path("worker/app/agent3/core.py")
replace_once(
    core,
    "from typing import Any, Callable, Iterable\n\nfrom .runtime_restore_guard import acquire_agent3_runtime_lease\n\n\nclass StrEnum",
    "from typing import Any, Callable, Iterable\n\n\nclass StrEnum",
    "remove store-owned lease import",
)
old_init = '''class AgentRunStore:\n    def __init__(self, path: str):\n        Path(path).parent.mkdir(parents=True, exist_ok=True)\n        self._lock = threading.RLock()\n        self._runtime_restore_lease = None\n        if path != ":memory:":\n            # Acquire cross-process runtime authority before opening either live\n            # SQLite store. A restore-in-progress/incomplete marker therefore\n            # blocks startup even when runs_path currently contains the durable\n            # non-SQLite restore fence.\n            self._runtime_restore_lease = acquire_agent3_runtime_lease(path)\n        try:\n            self._conn = sqlite3.connect(path, check_same_thread=False)\n            self._conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_runs ("\n                "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"\n            )\n            self._conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_events ("\n                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "\n                "kind TEXT NOT NULL, payload TEXT NOT NULL)"\n            )\n            self._conn.commit()\n\n            # Execution-start evidence deliberately lives in a separate SQLite file.\n            # A stale/partially-restored agent_runs payload must never be able to roll\n            # this watermark backwards and make a side effect look PENDING again.\n            progress_path = ":memory:" if path == ":memory:" else f"{path}.execution-progress"\n            self._progress_conn = sqlite3.connect(progress_path, check_same_thread=False)\n            self._progress_conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_execution_starts ("\n                "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n                "started_at REAL NOT NULL, "\n                "PRIMARY KEY(run_id,step_index,step_sha256))"\n            )\n            self._progress_conn.commit()\n        except Exception:\n            progress = getattr(self, "_progress_conn", None)\n            if progress is not None:\n                progress.close()\n            connection = getattr(self, "_conn", None)\n            if connection is not None:\n                connection.close()\n            if self._runtime_restore_lease is not None:\n                self._runtime_restore_lease.close()\n                self._runtime_restore_lease = None\n            raise\n'''
new_init = '''class AgentRunStore:\n    def __init__(self, path: str):\n        Path(path).parent.mkdir(parents=True, exist_ok=True)\n        self._lock = threading.RLock()\n        try:\n            self._conn = sqlite3.connect(path, check_same_thread=False)\n            self._conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_runs ("\n                "id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL)"\n            )\n            self._conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_events ("\n                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "\n                "kind TEXT NOT NULL, payload TEXT NOT NULL)"\n            )\n            self._conn.commit()\n\n            # Execution-start evidence deliberately lives in a separate SQLite file.\n            # A stale/partially-restored agent_runs payload must never be able to roll\n            # this watermark backwards and make a side effect look PENDING again.\n            progress_path = ":memory:" if path == ":memory:" else f"{path}.execution-progress"\n            self._progress_conn = sqlite3.connect(progress_path, check_same_thread=False)\n            self._progress_conn.execute(\n                "CREATE TABLE IF NOT EXISTS agent_execution_starts ("\n                "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n                "started_at REAL NOT NULL, "\n                "PRIMARY KEY(run_id,step_index,step_sha256))"\n            )\n            self._progress_conn.commit()\n        except Exception:\n            progress = getattr(self, "_progress_conn", None)\n            if progress is not None:\n                progress.close()\n            connection = getattr(self, "_conn", None)\n            if connection is not None:\n                connection.close()\n            raise\n'''
replace_once(core, old_init, new_init, "AgentRunStore init ownership")
replace_once(
    core,
    '''    def close(self) -> None:\n        """Release both authority stores and the process-wide restore lease."""\n        with self._lock:\n            progress = getattr(self, "_progress_conn", None)\n            if progress is not None:\n                progress.close()\n                self._progress_conn = None\n            connection = getattr(self, "_conn", None)\n            if connection is not None:\n                connection.close()\n                self._conn = None\n            lease = self._runtime_restore_lease\n            if lease is not None:\n                lease.close()\n                self._runtime_restore_lease = None\n''',
    '''    def close(self) -> None:\n        """Release both SQLite authority stores owned by this store."""\n        with self._lock:\n            progress = getattr(self, "_progress_conn", None)\n            if progress is not None:\n                progress.close()\n                self._progress_conn = None\n            connection = getattr(self, "_conn", None)\n            if connection is not None:\n                connection.close()\n                self._conn = None\n''',
    "AgentRunStore close ownership",
)

prod = Path("worker/app/agent3/production_mount.py")
replace_once(
    prod,
    "from .replan_preview_api import (\n    build_default_replan_preview_service,\n    build_replan_preview_router,\n)\n",
    "from .replan_preview_api import (\n    build_default_replan_preview_service,\n    build_replan_preview_router,\n)\nfrom .runtime_restore_guard import acquire_agent3_runtime_lease\n",
    "production lease import",
)
replace_once(
    prod,
    '''    "agent3_replan_preview_service",\n)\n''',
    '''    "agent3_replan_preview_service",\n    "agent3_runtime_restore_lease",\n)\n''',
    "clear-state lease name",
)
replace_once(
    prod,
    '''        orchestrator = getattr(app.state, "agent3_orchestrator", None)\n        _close_owned_resource(getattr(orchestrator, "review_store", None), seen)\n        _close_owned_resource(getattr(orchestrator, "store", None), seen)\n\n        for name in _CLEAR_STATE_NAMES:\n''',
    '''        orchestrator = getattr(app.state, "agent3_orchestrator", None)\n        _close_owned_resource(getattr(orchestrator, "review_store", None), seen)\n        _close_owned_resource(getattr(orchestrator, "store", None), seen)\n\n        # Keep restore exclusion until the live run/progress handles are closed.\n        # Releasing this lease first would reopen the exact shutdown race the\n        # restore guard exists to prevent.\n        _close_owned_resource(\n            getattr(app.state, "agent3_runtime_restore_lease", None), seen\n        )\n\n        for name in _CLEAR_STATE_NAMES:\n''',
    "shutdown lease order",
)
replace_once(
    prod,
    '''    app.state.agent3_resources_closed = False\n    try:\n        if not _mount_agent3_core(app):\n            return False\n\n        orchestrator = app.state.agent3_orchestrator\n''',
    '''    app.state.agent3_resources_closed = False\n    try:\n        runtime_lease = None\n        if os.getenv("KALIV_AGENT3_ENABLED", "0") == "1":\n            run_db_path = _paths.resolve(\n                "./kaliv-agent3.db", env="KALIV_AGENT3_DB"\n            )\n            runtime_lease = acquire_agent3_runtime_lease(str(run_db_path))\n            app.state.agent3_runtime_restore_lease = runtime_lease\n\n        if not _mount_agent3_core(app):\n            # Environment mutation between the lease preflight and the private\n            # core guard is unlikely but must not leak restore exclusion.\n            _close_owned_resource(runtime_lease, set())\n            app.state.agent3_runtime_restore_lease = None\n            return False\n\n        orchestrator = app.state.agent3_orchestrator\n''',
    "production lease acquisition",
)

# Replace targeted test with utility-level + actual production ownership proof.
test = Path("tests/worker_agent3_restore_guard.py")
test.write_text(r'''from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI

from app.agent3.production_mount import close_agent3, mount_agent3
from app.agent3.runtime_restore_guard import (
    acquire_agent3_restore_lease,
    acquire_agent3_runtime_lease,
    agent3_restore_guard,
)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


with tempfile.TemporaryDirectory(prefix="agent3-restore-guard-") as root:
    run_path = os.path.join(root, "agent3-runs.db")

    runtime = acquire_agent3_runtime_lease(run_path)
    try:
        acquire_agent3_restore_lease(run_path)
        check(False, "live runtime lease blocks exclusive restore authority")
    except RuntimeError as exc:
        check("runtime is active" in str(exc), "live runtime lease blocks exclusive restore authority")
    finally:
        runtime.close()

    with agent3_restore_guard(run_path):
        try:
            acquire_agent3_runtime_lease(run_path)
            check(False, "active restore blocks fresh runtime lease")
        except RuntimeError as exc:
            check("restore is in progress" in str(exc), "active restore blocks fresh runtime lease")

    after_success = acquire_agent3_runtime_lease(run_path)
    after_success.close()
    check(True, "successful restore clears startup guard")

    try:
        with agent3_restore_guard(run_path):
            raise OSError("injected restore failure")
    except OSError:
        check(True, "injected restore failure propagates")

    try:
        acquire_agent3_runtime_lease(run_path)
        check(False, "failed restore leaves durable startup blocker")
    except RuntimeError as exc:
        check("restore is incomplete" in str(exc), "failed restore leaves durable startup blocker")

    with agent3_restore_guard(run_path):
        pass
    repaired = acquire_agent3_runtime_lease(run_path)
    repaired.close()
    check(True, "complete retry clears durable failed-restore blocker")

    first = acquire_agent3_runtime_lease(run_path)
    second = acquire_agent3_runtime_lease(run_path)
    try:
        try:
            acquire_agent3_restore_lease(run_path)
            check(False, "two shared runtime leases exclude restore")
        except RuntimeError:
            check(True, "two shared runtime leases exclude restore")
        first.close()
        try:
            acquire_agent3_restore_lease(run_path)
            check(False, "one remaining runtime lease still excludes restore")
        except RuntimeError:
            check(True, "one remaining runtime lease still excludes restore")
    finally:
        first.close()
        second.close()

    with agent3_restore_guard(run_path):
        pass
    check(True, "restore authority succeeds after final runtime lease closes")

# Production mount, not every bare AgentRunStore, owns the process-wide lease.
# This keeps ordinary/unit stores resource-local while protecting the deployed
# worker for exactly its mounted lifecycle.
with tempfile.TemporaryDirectory(prefix="agent3-production-lease-") as root:
    env_names = (
        "KALIV_AGENT3_ENABLED",
        "KALIV_DATA_DIR",
        "KALIV_AGENT3_DB",
    )
    previous = {name: os.environ.get(name) for name in env_names}
    production_run_path = str(Path(root) / "production-runs.db")
    try:
        os.environ["KALIV_AGENT3_ENABLED"] = "1"
        os.environ["KALIV_DATA_DIR"] = root
        os.environ["KALIV_AGENT3_DB"] = production_run_path
        app = FastAPI()
        check(mount_agent3(app) is True, "production Agent3 mount succeeds under runtime lease")
        check(
            getattr(app.state, "agent3_runtime_restore_lease", None) is not None,
            "production mount owns explicit restore-exclusion lease",
        )
        try:
            acquire_agent3_restore_lease(production_run_path)
            check(False, "production mount excludes restore for its live lifecycle")
        except RuntimeError as exc:
            check(
                "runtime is active" in str(exc),
                "production mount excludes restore for its live lifecycle",
            )
        close_agent3(app)
        check(
            getattr(app.state, "agent3_runtime_restore_lease", None) is None,
            "production shutdown releases and clears restore-exclusion lease",
        )
        with agent3_restore_guard(production_run_path):
            pass
        check(True, "restore becomes available only after production shutdown")
    finally:
        try:
            close_agent3(app)
        except NameError:
            pass
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

print(f"\n===== AGENT3 RESTORE GUARD: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
''', encoding="utf-8")

print("applied production-owned restore lease P1n")
