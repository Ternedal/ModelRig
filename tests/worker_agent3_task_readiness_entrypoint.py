"""T-021: the documented production entrypoint owns task readiness.

The contract module can be perfectly tested and still be absent from the app a
rig actually serves. This suite imports ``app.entrypoint`` in fresh processes,
checks the real route table, calls the guarded production app from a real ASGI
loopback peer, and proves feature-off dormancy plus idempotent mounting.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


PROBE = r"""
import asyncio
import json
import httpx
import app.entrypoint as entrypoint
from app.agent3.production_mount import mount_agent3

routing_app = entrypoint.fastapi_app
first = mount_agent3(routing_app)
second = mount_agent3(routing_app)

pairs = []
for route in routing_app.routes:
    if type(route).__name__ == "_IncludedRouter":
        original = getattr(route, "original_router", None)
        if original is not None:
            for child in getattr(original, "routes", []):
                path = getattr(child, "path", None)
                for method in (getattr(child, "methods", None) or set()):
                    if path is not None:
                        pairs.append(method + " " + path)
    else:
        path = getattr(route, "path", None)
        for method in (getattr(route, "methods", None) or set()):
            if path is not None:
                pairs.append(method + " " + path)

route = "/experimental/agent3/task-readiness"
paths = set(routing_app.openapi().get("paths", {}))
payload = None
status = None
raw = None

async def request():
    # Production serves the hardened outer ASGI app. The netguard checks the
    # actual ASGI peer, not the Host header; ASGITransport is the proven way the
    # existing worker entrypoint suite supplies a genuine loopback client.
    transport = httpx.ASGITransport(
        app=entrypoint.app,
        client=("127.0.0.1", 54321),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
    ) as client:
        return await client.get(route)

if route in paths:
    response = asyncio.run(request())
    status = response.status_code
    raw = response.text[:1000]
    try:
        payload = response.json()
    except Exception:
        payload = None

print(json.dumps({
    "first": first,
    "second": second,
    "mounted": getattr(routing_app.state, "agent3_task_readiness_mounted", False),
    "route_present": route in paths,
    "route_count": pairs.count("GET " + route),
    "status": status,
    "payload": payload,
    "raw": raw,
}))
"""


def probe(flag: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="kaliv-t021-entrypoint-") as temp:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "worker")
        env["KALIV_AGENT3_ENABLED"] = flag
        env["KALIV_AGENT3_TASK_UI"] = "1"
        env.pop("KALIV_AGENT3_PILOT_REPORT", None)
        env.pop("KALIV_AGENT3_VALIDATION_REPORT", None)
        env.pop("KALIV_SCHEDULER", None)
        for name, filename in (
            ("KALIV_AGENT3_DB", "agent3.db"),
            ("KALIV_AGENT3_REVIEW_DB", "reviews.db"),
            ("KALIV_AGENT3_REPLAN_DB", "replans.db"),
            ("KALIV_AGENT3_MEMORY_DB", "memory.db"),
            ("KALIV_AGENT3_PLAN_DB", "plans.db"),
            ("KALIV_SCHEDULES_DB", "schedules.db"),
            ("MODELRIG_JOBS_DB", "jobs.db"),
            ("KALIV_AUDIT_DB", "audit.db"),
        ):
            env[name] = str(Path(temp) / filename)
        process = subprocess.run(
            [sys.executable, "-c", PROBE],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
            cwd=temp,
        )
        if process.returncode != 0:
            raise AssertionError(
                f"production entrypoint probe failed (flag={flag}):\n"
                f"{process.stderr[-1200:]}"
            )
        return json.loads(process.stdout.strip().splitlines()[-1])


on = probe("1")
check(on["first"] is True and on["second"] is True,
      "the production mount is successful and idempotent")
check(on["mounted"] is True and on["route_present"] is True,
      "the documented entrypoint serves task readiness when Agent 3 is enabled")
check(on["route_count"] == 1,
      "repeated mounting creates exactly one GET task-readiness route")
check(on["status"] == 200,
      "the guarded readiness endpoint is callable without invoking a model or "
      f"tool (status={on['status']}, body={on['raw']!r})")
payload = on["payload"] or {}
check(payload.get("schema") == "kaliv-agent3-task-readiness/v1",
      f"the production route returns the typed readiness schema (payload={payload!r})")
check(payload.get("selected_surface") == "agent2"
      and payload.get("reason") == "pilot_report_path_not_configured",
      f"missing physical evidence fails closed to Agent 2 (payload={payload!r})")
check(payload.get("production_activation") is False
      and payload.get("normal_chat_route_unchanged") is True,
      f"mounting readiness cannot activate production or change normal chat "
      f"(payload={payload!r})")

off = probe("0")
check(off["first"] is False and off["second"] is False,
      "the production mount refuses to run when the Agent 3 flag is off")
check(off["mounted"] is False and off["route_present"] is False
      and off["route_count"] == 0,
      "feature-off leaves no task-readiness route or mounted state")

print(f"\n===== AGENT3 TASK READINESS ENTRYPOINT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
