from __future__ import annotations

import os
import tempfile

from app.agent3.core import (
    AgentRun,
    AgentStep,
    RiskClass,
    RouteKind,
    RoutePlan,
    StepState,
    TurnRequest,
)
from app.agent3.review_binding import rebind_waiting_review
from app.agent3.review_orchestrator import ReadReviewStore


def step(name: str, risk: RiskClass = RiskClass.READ) -> AgentStep:
    return AgentStep(tool=name, args={}, risk=risk, state=StepState.PENDING)


def run_with(steps: list[AgentStep], *, current_step: int = 1) -> AgentRun:
    return AgentRun(
        request=TurnRequest("review binding", tools=True),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=False,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=steps,
        current_step=current_step,
    )


root = tempfile.mkdtemp(prefix="agent3-review-binding-")
store = ReadReviewStore(os.path.join(root, "reviews.db"))

# A committed replan replaces the old pending read ids. The waiting checkpoint
# must follow the new authoritative read window without resuming the run.
completed = step("completed")
completed.state = StepState.SUCCEEDED
old_one = step("old_one")
old_two = step("old_two")
write = step("write", RiskClass.WRITE)
run = run_with([completed, old_one, old_two, write])
store.configure(run.id, True)
store.set_waiting(
    run.id,
    completed_step_id=completed.id,
    completed_tool=completed.tool,
    window_start=1,
    window_end=3,
    removable_step_ids=[old_one.id, old_two.id],
)
replacement = step("replacement")
run.steps[1:3] = [replacement]
updated = rebind_waiting_review(store, run)
assert updated["enabled"] is True
assert updated["waiting"] is True
assert updated["window_start"] == 1
assert updated["window_end"] == 2
assert updated["removable_step_ids"] == [replacement.id]
assert updated["completed_step_id"] == completed.id
assert updated["completed_tool"] == completed.tool
assert run.current_step == 1

# Removing the complete pending read window clears only the stale checkpoint.
# The immutable write tail remains pending and the run is not advanced.
empty = run_with([completed, write])
store.configure(empty.id, True)
store.set_waiting(
    empty.id,
    completed_step_id=completed.id,
    completed_tool=completed.tool,
    window_start=1,
    window_end=2,
    removable_step_ids=[old_one.id],
)
cleared = rebind_waiting_review(store, empty)
assert cleared["enabled"] is True
assert cleared["waiting"] is False
assert cleared["removable_step_ids"] == []
assert empty.current_step == 1
assert empty.steps[1].risk == RiskClass.WRITE

# Disabled or non-waiting review state is a strict no-op.
plain = run_with([completed, step("plain")])
store.configure(plain.id, False)
before = store.get(plain.id)
after = rebind_waiting_review(store, plain)
assert after == before

print("16 passed, 0 failed")
