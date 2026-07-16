from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import build_router
from app.agent3.core import Agent3Orchestrator, AgentRunStore


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


root = tempfile.mkdtemp(prefix="agent3-validation-status-")
store = AgentRunStore(os.path.join(root, "runs.db"))
orch = Agent3Orchestrator(store=store, executor=lambda _step: None)
assessment = {
    "configured": True,
    "present": True,
    "eligible_for_developer_preview": True,
    "eligible_for_write_pilot": True,
    "production_activation": False,
    "validated_version": "1.58.38",
    "planner_model": "fake-local-planner",
    "proofs": {"status": True},
    "reasons": [],
}

app = FastAPI(version="1.58.38")
app.include_router(
    build_router(
        orch,
        object(),  # status does not touch the tool adapter
        validation_provider=lambda: assessment,
        worker_version=app.version,
    )
)
client = TestClient(app)

response = client.get("/experimental/agent3/status")
check(response.status_code == 200, "status endpoint succeeds")
payload = response.json()
check(payload["enabled"] is True, "experimental agent remains enabled behind its feature mount")
check(payload["experimental"] is True, "status remains explicitly experimental")
check(payload["production_tools_path_untouched"] is True, "production tools path remains untouched")
check(payload["worker_version"] == "1.58.38", "status binds evidence to the worker version")
check(payload["rig_validation"] == assessment, "status returns the injected redacted assessment")
check(payload["production_activation"] is False, "status cannot activate production")
check(payload["rig_validation"]["production_activation"] is False, "eligible evidence remains advisory")
check("hostname" not in str(payload), "status contains no host identity")
check("base_url" not in str(payload), "status contains no validation target URL")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
