from pathlib import Path

# Temporary qualification helper. Removed before the retained product commit.
path = Path("worker/app/agent3/planner.py")
text = path.read_text(encoding="utf-8")
old = '''            if state == "accepted":
                if existing is None:
                    raise _reviewed_start_error(
                        "reviewed_start_refused",
                        "accepted reviewed Start is missing its bound run",
                    )
                stored = json.loads(
                    plan_store.reviewed_start_materialization(plan_id, reserved_run_id)
                )
                reconciled = _reconcile_reviewed_start_run(reserved_run_id)
                return _reviewed_start_response(plan_id, stored, reconciled)
'''
new = '''            if state == "accepted":
                if existing is None:
                    raise _reviewed_start_error(
                        "reviewed_start_refused",
                        "accepted reviewed Start is missing its bound run",
                    )
                stored = json.loads(
                    plan_store.reviewed_start_materialization(plan_id, reserved_run_id)
                )
                return _reviewed_start_response(plan_id, stored, existing)
'''
if text.count(old) != 1:
    raise SystemExit(f"accepted replay block mismatch: {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("accepted replay remains observation-only; dead-generation pending recovery still reconciles")
