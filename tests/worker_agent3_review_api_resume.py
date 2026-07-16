from __future__ import annotations

import runpy


state = runpy.run_path("tests/worker_agent3_review_api_apply.py")
client = state["client"]
run_id = state["run_id"]
executor = state["executor"]
replacement_id = state["new_read_id"]
write_id = state["write_id"]

resumed = client.post(f"/experimental/agent3/runs/{run_id}/resume")
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

kinds = [
    event["kind"]
    for event in client.get(f"/experimental/agent3/runs/{run_id}/events").json()["events"]
]
assert kinds.count("replan_review_resumed") == 1
assert kinds[-1] == "confirmation_required"

print("15 passed, 0 failed")
