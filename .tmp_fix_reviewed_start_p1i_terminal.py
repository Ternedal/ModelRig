from pathlib import Path

p = Path("worker/app/agent3/planner.py")
text = p.read_text(encoding="utf-8")
old = '''        _assert_reviewed_run_identity(existing, reviewed_template)\n        # Only RUNNING snapshots need crash reconciliation. BLOCKED is terminal\n        # authority too (for example route/capability drift before execution),\n        # and advancing it would try to complete a non-RUNNING run forever.\n        if existing.state is not RunState.RUNNING:\n            return existing\n'''
new = '''        # Only RUNNING snapshots can be advanced. BLOCKED is terminal authority\n        # and may legitimately carry a fail-closed route produced by capability\n        # drift rather than the reviewed executable route. Observe terminal state\n        # unchanged; bind identity immediately before any path that could advance.\n        if existing.state is not RunState.RUNNING:\n            return existing\n        _assert_reviewed_run_identity(existing, reviewed_template)\n'''
if text.count(old) != 1:
    raise SystemExit(f"planner terminal identity boundary: expected one match, found {text.count(old)}")
text = text.replace(old, new, 1)

old_accepted = '''                _assert_reviewed_run_identity(existing, reviewed_template)\n                return _reviewed_start_response(plan_id, stored, existing)\n'''
new_accepted = '''                if existing.state is RunState.RUNNING:\n                    _assert_reviewed_run_identity(existing, reviewed_template)\n                return _reviewed_start_response(plan_id, stored, existing)\n'''
if text.count(old_accepted) != 1:
    raise SystemExit(f"accepted identity boundary: expected one match, found {text.count(old_accepted)}")
text = text.replace(old_accepted, new_accepted, 1)
p.write_text(text, encoding="utf-8")
print("P1i terminal identity boundary staged")
