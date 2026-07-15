from __future__ import annotations

import os
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_AGENT3_DB"] = os.path.join(tempfile.mkdtemp(prefix="agent3-entry-"), "runs.db")
os.environ["KALIV_AGENT3_PLAN_DB"] = os.path.join(tempfile.mkdtemp(prefix="agent3-plans-"), "plans.db")

from fastapi.testclient import TestClient

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


def client() -> TestClient:
    # The worker deliberately rejects non-loopback hosts. Starlette's default
    # TestClient host is `testclient`, so use the same loopback origin as the
    # real Go backend -> worker connection.
    return TestClient(run_worker.app, base_url="http://127.0.0.1")


os.environ["KALIV_AGENT3_ENABLED"] = "0"
before_count = len(run_worker.app.routes)
check(run_worker._mount_optional_agent3() is False, "feature remains off without explicit flag")
with client() as c:
    check(c.get("/experimental/agent3/status").status_code == 404, "flag-off worker exposes no Agent 3.0 API")
check(len(run_worker.app.routes) == before_count, "flag-off mount changes no route registrations")

os.environ["KALIV_AGENT3_ENABLED"] = "1"
check(run_worker._mount_optional_agent3() is True, "feature mounts after explicit flag")
with client() as c:
    check(c.get("/experimental/agent3/status").status_code == 200, "run API is reachable")
    # Validation errors prove the POST route exists without calling Ollama.
    check(c.post("/experimental/agent3/plan", json={}).status_code == 422, "planner API is reachable")
    # A missing single-use plan is a domain conflict, not a missing route.
    check(c.post("/experimental/agent3/plans/missing/start").status_code == 409, "single-use plan start is reachable")

mounted_count = len(run_worker.app.routes)
check(run_worker._mount_optional_agent3() is True, "second mount call is harmless")
check(len(run_worker.app.routes) == mounted_count, "second mount does not duplicate registrations")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
