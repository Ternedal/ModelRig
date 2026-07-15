from __future__ import annotations

import os
import tempfile
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.memory import MemoryStore
from app.agent3.memory_api import build_memory_router

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


store = MemoryStore(os.path.join(tempfile.mkdtemp(prefix="agent3-memory-api-"), "memory.db"))
app = FastAPI()
app.include_router(build_memory_router(store))
client = TestClient(app)
headers = {"X-Request-ID": "req-memory-test"}

created_resp = client.post(
    "/experimental/agent3/memory",
    headers=headers,
    json={
        "subject": "anders",
        "predicate": "foretrækker_mad",
        "value": "ingen fisk",
        "kind": "preference",
        "sensitivity": "private",
    },
)
check(created_resp.status_code == 200, "explicit memory can be created through API")
created = created_resp.json()["memory"]
memory_id = created["id"]
check(created["review_status"] == "confirmed", "API-created memory is explicit and confirmed")
check(created["source_ref"] == "memory-api:req-memory-test", "API provenance is server-owned request id")

listed = client.get("/experimental/agent3/memory?subject=anders").json()["memories"]
check([item["id"] for item in listed] == [memory_id], "memory list supports subject filter")
searched = client.get("/experimental/agent3/memory/search?q=fisk").json()["memories"]
check([item["id"] for item in searched] == [memory_id], "memory search returns confirmed match")
check(client.get(f"/experimental/agent3/memory/{memory_id}").json()["memory"]["value"] == "ingen fisk", "memory get returns value")

corrected_resp = client.post(
    f"/experimental/agent3/memory/{memory_id}/correct",
    headers={"X-Request-ID": "req-correction"},
    json={"value": "ingen fisk eller sushi"},
)
check(corrected_resp.status_code == 200, "memory can be corrected through API")
corrected = corrected_resp.json()["memory"]
check(corrected["supersedes_id"] == memory_id, "correction creates a new version")
check(corrected["source_ref"] == "memory-api:req-correction", "correction has fresh provenance")
history = client.get(f"/experimental/agent3/memory/{corrected['id']}/history").json()["memories"]
check([item["lifecycle_status"] for item in history] == ["superseded", "active"], "history exposes both versions")

pending = store.create(
    subject="anders",
    predicate="mulig_præference",
    value="qwen",
    source_type="inferred",
    sensitivity="operational",
)
check(client.post(f"/experimental/agent3/memory/{pending.id}/confirm").status_code == 200, "pending internal proposal can be confirmed")
check(store.get(pending.id).review_status == "confirmed", "confirm endpoint changes review state")

pending_reject = store.create(
    subject="anders",
    predicate="forkert_præference",
    value="fisk",
    source_type="tool_observation",
)
check(client.post(f"/experimental/agent3/memory/{pending_reject.id}/reject").status_code == 200, "pending proposal can be rejected")
check(store.get(pending_reject.id).review_status == "rejected", "reject endpoint changes review state")

secret_create = client.post(
    "/experimental/agent3/memory",
    json={
        "subject": "anders",
        "predicate": "password",
        "value": "do-not-store-remotely",
        "sensitivity": "secret",
    },
)
check(secret_create.status_code == 422, "remote API refuses new secret memories")
secret = store.create(
    subject="anders",
    predicate="local_secret",
    value="hidden",
    sensitivity="secret",
)
secret_get = client.get(f"/experimental/agent3/memory/{secret.id}").json()["memory"]
check(secret_get["value"] == "[redacted]" and secret_get["source_ref"] is None, "existing local secret is redacted over API")
check(secret.id not in {item["id"] for item in client.get("/experimental/agent3/memory").json()["memories"]}, "secret rows are excluded from API listing")

expired = store.create(
    subject="anders",
    predicate="temporary",
    value="old",
    sensitivity="operational",
    expires_at=time.time() - 1,
)
normal_ids = {item["id"] for item in client.get("/experimental/agent3/memory").json()["memories"]}
check(expired.id not in normal_ids, "expired rows are excluded by default")
all_ids = {item["id"] for item in client.get("/experimental/agent3/memory?include_expired=true").json()["memories"]}
check(expired.id in all_ids, "expired rows require explicit include flag")

deleted_resp = client.delete(f"/experimental/agent3/memory/{corrected['id']}")
check(deleted_resp.status_code == 200, "memory can be deleted through API")
deleted = deleted_resp.json()["memory"]
check(deleted["lifecycle_status"] == "deleted" and deleted["value"] == "", "delete response is a redacted tombstone")
check(client.get("/experimental/agent3/memory/missing").status_code == 404, "missing memory returns 404")
check(client.post(f"/experimental/agent3/memory/{pending.id}/confirm").status_code == 409, "reconfirming a confirmed memory returns conflict")

store.close()
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
