from pathlib import Path

path = Path("tests/worker_agent3_planner_review.py")
text = path.read_text(encoding="utf-8")
old = '''assert client.post(\n    f"/experimental/agent3/plans/{preview_body['plan_id']}/start"\n).status_code == 409\n'''
new = '''replayed = client.post(\n    f"/experimental/agent3/plans/{preview_body['plan_id']}/start"\n)\nassert replayed.status_code == 200, replayed.text\nassert replayed.json()["run"]["id"] == body["run"]["id"]\nassert replayed.json()["read_review"]["waiting"] is True\nassert executed == ["rig_status"]\n'''
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one stale single-use assertion, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
