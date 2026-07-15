from __future__ import annotations

import os
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_AGENT3_DB"] = os.path.join(tempfile.mkdtemp(prefix="agent3-entry-"), "runs.db")
os.environ["KALIV_AGENT3_PLAN_DB"] = os.path.join(tempfile.mkdtemp(prefix="agent3-plans-"), "plans.db")

import run_worker

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


os.environ["KALIV_AGENT3_ENABLED"] = "0"
before = [r.path for r in run_worker.app.routes]
check(run_worker._mount_optional_agent3() is False, "feature remains off without explicit flag")
check([r.path for r in run_worker.app.routes] == before, "flag-off mount changes no routes")

os.environ["KALIV_AGENT3_ENABLED"] = "1"
check(run_worker._mount_optional_agent3() is True, "feature mounts after explicit flag")
paths = [r.path for r in run_worker.app.routes]
check("/experimental/agent3/status" in paths, "run API is mounted")
check("/experimental/agent3/plan" in paths, "planner API is mounted")
check("/experimental/agent3/plans/{plan_id}/start" in paths, "single-use plan start is mounted")

count = len(paths)
check(run_worker._mount_optional_agent3() is True, "second mount call is harmless")
check(len(run_worker.app.routes) == count, "second mount does not duplicate routes")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
