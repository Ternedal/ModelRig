from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .core import (
    AgentRun,
    AgentStep,
    EgressClass,
    RiskClass,
    RunState,
    StepState,
)


class ReplanError(RuntimeError):
    """The proposed plan revision violates an Agent 3.0 invariant."""


@dataclass(frozen=True)
class ReplanWindow:
    """The only replaceable slice in a run.

    The window begins at current_step and contains the contiguous prefix of
    pending read-only steps. The first non-read or non-pending step and every
    step after it are immutable.
    """

    start: int
    end: int
    removable_step_ids: tuple[str, ...]
    immutable_prefix_ids: tuple[str, ...]
    immutable_tail_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReplanReceipt:
    reason: str
    from_revision: int
    to_revision: int
    replan_number: int
    timestamp: float
    start: int
    old_end: int
    new_end: int
    removed_step_ids: tuple[str, ...]
    removed_tools: tuple[str, ...]
    added_step_ids: tuple[str, ...]
    added_tools: tuple[str, ...]
    immutable_prefix_ids: tuple[str, ...]
    immutable_tail_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReadSuffixReplanner:
    """Fail-closed replanning for remaining read-only work.

    This component does not call a model, registry, executor or store. It only
    validates and applies an already registry-validated list of AgentStep
    objects. Persistence and event logging are separate integration steps.

    Safety boundary:
    - completed/currently executing/approved steps are immutable,
    - writes, destructive and admin steps are immutable,
    - a replan can only replace the contiguous pending read prefix beginning at
      current_step,
    - replacement steps must be fresh pending reads on the existing route,
    - the total plan and number of revisions stay bounded.
    """

    def __init__(self, *, max_steps: int = 12, max_replans: int = 3):
        self.max_steps = max(1, max_steps)
        self.max_replans = max(0, max_replans)

    def window(self, run: AgentRun) -> ReplanWindow:
        if run.state != RunState.RUNNING:
            raise ReplanError(f"run state {run.state.value!r} cannot be replanned")
        if run.current_step < 0 or run.current_step >= len(run.steps):
            raise ReplanError("run has no current pending step")

        start = run.current_step
        end = start
        while end < len(run.steps):
            step = run.steps[end]
            if step.state != StepState.PENDING or step.risk != RiskClass.READ:
                break
            end += 1

        if end == start:
            current = run.steps[start]
            raise ReplanError(
                "current step is not a pending read and is therefore immutable "
                f"({current.tool}:{current.risk.value}:{current.state.value})"
            )

        return ReplanWindow(
            start=start,
            end=end,
            removable_step_ids=tuple(step.id for step in run.steps[start:end]),
            immutable_prefix_ids=tuple(step.id for step in run.steps[:start]),
            immutable_tail_ids=tuple(step.id for step in run.steps[end:]),
        )

    def validate(
        self,
        run: AgentRun,
        replacement_steps: Iterable[AgentStep],
        *,
        replan_count: int,
    ) -> tuple[ReplanWindow, list[AgentStep]]:
        if replan_count < 0:
            raise ReplanError("replan_count cannot be negative")
        if replan_count >= self.max_replans:
            raise ReplanError(f"run already reached max_replans ({self.max_replans})")

        window = self.window(run)
        replacement = list(replacement_steps)
        final_count = len(run.steps) - (window.end - window.start) + len(replacement)
        if final_count > self.max_steps:
            raise ReplanError(
                f"replanned run would contain {final_count} steps; max_steps is {self.max_steps}"
            )

        expected_origin = "cloud" if run.route.uses_cloud else "local"
        expected_egress = EgressClass.CLOUD if run.route.uses_cloud else EgressClass.LOCAL
        immutable_ids = {
            *window.immutable_prefix_ids,
            *window.immutable_tail_ids,
        }
        replacement_ids: set[str] = set()

        for index, step in enumerate(replacement, start=1):
            if step.risk != RiskClass.READ:
                raise ReplanError(
                    f"replacement step {index} is {step.risk.value}; replanning may add reads only"
                )
            if step.state != StepState.PENDING:
                raise ReplanError(
                    f"replacement step {index} must be pending, got {step.state.value}"
                )
            if step.result is not None or step.error is not None:
                raise ReplanError(f"replacement step {index} is not fresh")
            if step.confirmation_digest is not None or step.confirmation_expires_at is not None:
                raise ReplanError(f"replacement step {index} carries confirmation state")
            if step.origin != expected_origin or step.egress != expected_egress:
                raise ReplanError(
                    f"replacement step {index} changes route semantics: "
                    f"expected {expected_origin}/{expected_egress.value}"
                )
            if step.conversation_id != run.request.conversation_id:
                raise ReplanError(f"replacement step {index} changes conversation binding")
            if step.id in immutable_ids:
                raise ReplanError(f"replacement step {index} reuses an immutable step id")
            if step.id in replacement_ids:
                raise ReplanError(f"replacement step {index} duplicates a replacement step id")
            replacement_ids.add(step.id)

        return window, replacement

    def apply(
        self,
        run: AgentRun,
        replacement_steps: Iterable[AgentStep],
        *,
        reason: str,
        revision: int,
        replan_count: int,
        now: float | None = None,
    ) -> ReplanReceipt:
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ReplanError("replan reason is required")
        if len(cleaned_reason) > 500:
            raise ReplanError("replan reason exceeds 500 characters")
        if revision < 0:
            raise ReplanError("revision cannot be negative")

        window, replacement = self.validate(
            run,
            replacement_steps,
            replan_count=replan_count,
        )
        removed = list(run.steps[window.start : window.end])
        prefix_ids_before = tuple(step.id for step in run.steps[: window.start])
        tail_ids_before = tuple(step.id for step in run.steps[window.end :])

        run.steps[window.start : window.end] = replacement
        run.current_step = window.start

        prefix_ids_after = tuple(step.id for step in run.steps[: window.start])
        tail_ids_after = tuple(step.id for step in run.steps[window.start + len(replacement) :])
        if prefix_ids_after != prefix_ids_before or tail_ids_after != tail_ids_before:
            raise ReplanError("internal invariant failure: immutable plan region changed")

        return ReplanReceipt(
            reason=cleaned_reason,
            from_revision=revision,
            to_revision=revision + 1,
            replan_number=replan_count + 1,
            timestamp=time.time() if now is None else now,
            start=window.start,
            old_end=window.end,
            new_end=window.start + len(replacement),
            removed_step_ids=tuple(step.id for step in removed),
            removed_tools=tuple(step.tool for step in removed),
            added_step_ids=tuple(step.id for step in replacement),
            added_tools=tuple(step.tool for step in replacement),
            immutable_prefix_ids=prefix_ids_before,
            immutable_tail_ids=tail_ids_before,
        )
