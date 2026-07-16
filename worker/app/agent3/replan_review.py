from __future__ import annotations

from typing import Any

from .core import AgentRun, RiskClass, StepState
from .replan_preview import ReplanPreviewService, StoredReplanPreview
from .review_orchestrator import ReadReviewError, ReadReviewStore


class ReviewAwareReplanPreviewService(ReplanPreviewService):
    """Rebind a persisted read-review checkpoint after a committed replan.

    Applying a reviewed preview changes only the pending read window. It never
    advances the run. When replacement reads exist, the existing checkpoint is
    rebound to their fresh server-generated step IDs. When the replacement is
    empty, the now-empty checkpoint is cleared, but execution still requires a
    separate explicit resume call.
    """

    def __init__(self, *args, review_store: ReadReviewStore, **kwargs):
        super().__init__(*args, **kwargs)
        self.review_store = review_store

    @staticmethod
    def _pending_read_window(run: AgentRun) -> tuple[int, int] | None:
        start = run.current_step
        end = start
        while end < len(run.steps):
            step = run.steps[end]
            if step.state != StepState.PENDING or step.risk != RiskClass.READ:
                break
            end += 1
        return (start, end) if end > start else None

    def _rebind_review(
        self,
        run: AgentRun,
        *,
        preview_id: str,
        stored: StoredReplanPreview,
    ) -> dict[str, Any]:
        review = self.review_store.get(run.id)
        if not review["enabled"] or not review["waiting"]:
            return review

        window = self._pending_read_window(run)
        if window is None:
            previous = self.review_store.resume(run.id)
            self.run_store.event(
                run.id,
                "replan_review_cleared_after_apply",
                {
                    "preview_id": preview_id,
                    "from_window_start": stored.window_start,
                    "from_window_end": stored.window_end,
                    "previous_removable_step_ids": list(stored.removable_step_ids),
                    "execution_resumed": False,
                },
            )
            if previous is None:
                raise ReadReviewError("read review checkpoint disappeared during replan apply")
            return self.review_store.get(run.id)

        start, end = window
        removable_ids = [step.id for step in run.steps[start:end]]
        completed_step_id = review.get("completed_step_id")
        completed_tool = review.get("completed_tool")
        if not completed_step_id or not completed_tool:
            raise ReadReviewError("read review checkpoint is missing completed-step provenance")

        self.review_store.set_waiting(
            run.id,
            completed_step_id=completed_step_id,
            completed_tool=completed_tool,
            window_start=start,
            window_end=end,
            removable_step_ids=removable_ids,
        )
        self.run_store.event(
            run.id,
            "replan_review_rebound",
            {
                "preview_id": preview_id,
                "from_window_start": stored.window_start,
                "from_window_end": stored.window_end,
                "previous_removable_step_ids": list(stored.removable_step_ids),
                "window_start": start,
                "window_end": end,
                "removable_step_ids": removable_ids,
                "execution_resumed": False,
            },
        )
        return self.review_store.get(run.id)

    def apply(self, preview_id: str):
        run, receipt, stored = super().apply(preview_id)
        try:
            self._rebind_review(run, preview_id=preview_id, stored=stored)
        except ReadReviewError:
            # The replan is already journaled and persisted. Fail loudly rather
            # than returning a stale checkpoint; the journal remains authoritative.
            raise
        return run, receipt, stored
