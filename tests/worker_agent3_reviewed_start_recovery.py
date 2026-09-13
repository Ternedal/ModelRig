from __future__ import annotations

import os
import tempfile

from app.agent3.plan_store import PlanStore, PlanStoreError

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-recovery-")
path = os.path.join(root, "plans.db")
first = PlanStore(path, ttl_seconds=30)
plan_id, _ = first.save("reviewed-payload")
first.claim_reviewed_start(plan_id, "reviewed-run")
old_owner = first.start_owner
check(
    first.reviewed_start_recovery(plan_id) == ("pending", "reviewed-run", old_owner),
    "first worker durably binds the exact reserved run before execution",
)
first.close()

second = PlanStore(path, ttl_seconds=30)
check(second.start_owner != old_owner, "worker restart creates a new reviewed-Start generation")
check(
    second.reviewed_start_recovery(plan_id) == ("pending", "reviewed-run", old_owner),
    "restart preserves pending plan-to-run authority from the dead generation",
)
check(
    second.claim_reviewed_start_recovery(plan_id, "reviewed-run", old_owner),
    "new generation can claim only the exact pending reviewed run",
)
check(
    second.reviewed_start_materialization(plan_id, "reviewed-run") == "reviewed-payload",
    "recovery retains the immutable reviewed plan payload",
)
second.mark_reviewed_start_accepted(plan_id, "reviewed-run")
check(
    second.reviewed_start_recovery(plan_id)[0:2] == ("accepted", "reviewed-run"),
    "accepted reviewed Start remains bound to the same run",
)
try:
    second.claim_task_start(plan_id, "task-run", "task-payload")
    cross_surface = True
except PlanStoreError:
    cross_surface = False
check(not cross_surface, "reviewed Start cannot be replayed through the task surface")
second.close()

other = PlanStore(os.path.join(root, "other.db"), ttl_seconds=30)
task_plan, _ = other.save("task")
other.claim_task_start(task_plan, "task-run", "prepared")
try:
    other.claim_reviewed_start(task_plan, "reviewed-run")
    reverse_cross_surface = True
except PlanStoreError:
    reverse_cross_surface = False
check(not reverse_cross_surface, "task Start cannot be replayed through reviewed Start")
other.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
