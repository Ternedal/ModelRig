from __future__ import annotations

import asyncio
import os
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_AGENT3_DB"] = os.path.join(tempfile.mkdtemp(prefix="agent3-entry-"), "runs.db")
os.environ["KALIV_AGENT3_PLAN_DB"] = os.path.join(tempfile.mkdtemp(prefix="agent3-plans-"), "plans.db")

import httpx

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


async def request(method: str, path: str, payload: dict | None = None) -> httpx.Response:
    # The worker's security middleware checks request.client.host, not the Host
    # header. ASGITransport lets the test set the actual ASGI peer to loopback;
    # Starlette TestClient always reports `testclient` and is correctly rejected.
    transport = httpx.ASGITransport(app=run_worker.app, client=("127.0.0.1", 54321))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        return await client.request(method, path, json=payload)


def status(method: str, path: str, payload: dict | None = None) -> int:
    return asyncio.run(request(method, path, payload)).status_code


os.environ["KALIV_AGENT3_ENABLED"] = "0"
before_count = len(run_worker.app.routes)
check(run_worker._mount_optional_agent3() is False, "feature remains off without explicit flag")
check(status("GET", "/experimental/agent3/status") == 404, "flag-off worker exposes no Agent 3.0 API")
check(len(run_worker.app.routes) == before_count, "flag-off mount changes no route registrations")

os.environ["KALIV_AGENT3_ENABLED"] = "1"
check(run_worker._mount_optional_agent3() is True, "feature mounts after explicit flag")
check(status("GET", "/experimental/agent3/status") == 200, "run API is reachable")
# Validation errors prove the POST route exists without calling Ollama.
check(status("POST", "/experimental/agent3/plan", {}) == 422, "planner API is reachable")
# A missing single-use plan is a domain conflict, not a missing route.
check(status("POST", "/experimental/agent3/plans/missing/start") == 409, "single-use plan start is reachable")

mounted_count = len(run_worker.app.routes)
check(run_worker._mount_optional_agent3() is True, "second mount call is harmless")
check(len(run_worker.app.routes) == mounted_count, "second mount does not duplicate registrations")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
