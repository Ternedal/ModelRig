from __future__ import annotations

from .core import AgentRun, RiskClass, StepState
from .review_orchestrator import ReadReviewStore


def rebind_waiting_review(review_store: ReadReviewStore, run: AgentRun) -> dict:
    """Bind an existing waiting review checkpoint to the run's current read window.

    This helper is intentionally independent of the HTTP and LLM layers. It only
    updates already-enabled, already-waiting review state after an authoritative
    replan has replaced the pending read suffix.

    If the replan removes all pending reads before the immutable tail, the stale
    review checkpoint is cleared. The run itself is not advanced.
    """

    current = review_store.get(run.id)
    if not current["enabled"] or not current["waiting"]:
        return current

    start = run.current_step
    end = start
    while end < len(run.steps):
        step = run.steps[end]
        if step.state != StepState.PENDING or step.risk != RiskClass.READ:
            break
        end += 1

    if end == start:
        review_store.resume(run.id)
        return review_store.get(run.id)

    review_store.set_waiting(
        run.id,
        completed_step_id=current["completed_step_id"],
        completed_tool=current["completed_tool"],
        window_start=start,
        window_end=end,
        removable_step_ids=[step.id for step in run.steps[start:end]],
    )
    return review_store.get(run.id)
