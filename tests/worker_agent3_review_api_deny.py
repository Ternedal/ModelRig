from __future__ import annotations

import runpy


state = runpy.run_path("tests/worker_agent3_review_api_resume.py")
client = state["client"]
run_id = state["run_id"]
executor = state["executor"]
run = state["run"]
write = run["steps"][run["current_step"]]

response = client.post(
    f"/experimental/agent3/runs/{run_id}/confirm",
    json={
        "step_id": write["id"],
        "decision": "deny",
        "digest": write["confirmation_digest"],
    },
)
assert response.status_code == 200, response.text
payload = response.json()
assert payload["run"]["state"] == "cancelled"
assert payload["run"]["steps"][2]["state"] == "denied"
assert payload["read_review"]["waiting"] is False
assert executor.calls == ["rig_status", "rig_status"]
assert "note_append" not in executor.calls

kinds = [
    event["kind"]
    for event in client.get(f"/experimental/agent3/runs/{run_id}/events").json()["events"]
]
assert kinds[-1] == "confirmation_denied"
assert "step_started" in kinds
assert kinds.count("step_succeeded") == 2

print("8 passed, 0 failed")
