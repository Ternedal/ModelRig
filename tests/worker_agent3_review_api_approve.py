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
        "decision": "approve",
        "digest": write["confirmation_digest"],
    },
)
assert response.status_code == 200, response.text
payload = response.json()
assert payload["run"]["state"] == "completed"
assert payload["run"]["steps"][2]["state"] == "succeeded"
assert payload["read_review"]["waiting"] is False
assert executor.calls == ["rig_status", "rig_status", "note_append"]
assert executor.calls.count("note_append") == 1

kinds = [
    event["kind"]
    for event in client.get(f"/experimental/agent3/runs/{run_id}/events").json()["events"]
]
assert "confirmation_approved" in kinds
assert kinds[-1] == "run_completed"
assert kinds.count("step_succeeded") == 3

print("8 passed, 0 failed")
