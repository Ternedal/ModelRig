from __future__ import annotations

import runpy


state = runpy.run_path("tests/worker_agent3_review_api_apply.py")
client = state["client"]
run_id = state["run_id"]
executor = state["executor"]
replacement_id = state["new_read_id"]
write_id = state["write_id"]

checkpoint_response = client.get(f"/experimental/agent3/runs/{run_id}")
assert checkpoint_response.status_code == 200, checkpoint_response.text
checkpoint = checkpoint_response.json()["read_review"]
checkpoint_step_id = checkpoint["completed_step_id"]
assert checkpoint["waiting"] is True
assert checkpoint_step_id

missing = client.post(
    f"/experimental/agent3/runs/{run_id}/resume",
    json={},
)
assert missing.status_code == 409, missing.text
assert executor.calls == ["rig_status"]

stale = client.post(
    f"/experimental/agent3/runs/{run_id}/resume",
    json={"completed_step_id": "stale-checkpoint"},
)
assert stale.status_code == 409, stale.text
assert executor.calls == ["rig_status"]

resumed = client.post(
    f"/experimental/agent3/runs/{run_id}/resume",
    json={"completed_step_id": checkpoint_step_id},
)
assert resumed.status_code == 200, resumed.text
payload = resumed.json()
run = payload["run"]
review = payload["read_review"]

assert executor.calls == ["rig_status", "rig_status"]
assert run["state"] == "waiting_confirmation"
assert run["current_step"] == 2
assert run["steps"][1]["id"] == replacement_id
assert run["steps"][1]["state"] == "succeeded"
assert run["steps"][2]["id"] == write_id
assert run["steps"][2]["tool"] == "note_append"
assert run["steps"][2]["state"] == "waiting_confirmation"
assert run["steps"][2]["confirmation_digest"]
assert review["enabled"] is True
assert review["waiting"] is False
assert review["removable_step_ids"] == []
assert "note_append" not in executor.calls

duplicate = client.post(
    f"/experimental/agent3/runs/{run_id}/resume",
    json={"completed_step_id": checkpoint_step_id},
)
assert duplicate.status_code == 409, duplicate.text
assert executor.calls == ["rig_status", "rig_status"]

kinds = [
    event["kind"]
    for event in client.get(f"/experimental/agent3/runs/{run_id}/events").json()["events"]
]
assert kinds.count("replan_review_resumed") == 1
assert kinds[-1] == "confirmation_required"

print("27 passed, 0 failed")