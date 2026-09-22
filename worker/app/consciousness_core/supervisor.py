"""C17 bounded, interruptible cognitive supervisor control plane.

This module plans at most one next cognitive cycle at a time. It does not call a
model, schedule work, start threads/tasks, persist SelfState, execute tools, write
Memory 4, or actuate body/voice authorities.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cycle import (
    CognitiveCycleResult,
    CognitiveWorkspace,
    WorkspaceCandidate,
    build_workspace,
    self_state_ref,
    workspace_ref,
)
from .executive import CognitiveExecutiveResult
from .self_state import PersistentSelfState, advance_self_state


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=4096)]
ReasoningMode = Literal["fast", "normal", "deep", "verify"]
SupervisorAction = Literal[
    "COMPLETE",
    "NEXT_CYCLE",
    "PAUSE",
    "BUDGET_EXHAUSTED",
    "INTERRUPTED",
]


class CognitiveSupervisorError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class SupervisorBudget(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-budget/v1"]
    max_cycles: Annotated[int, Field(ge=1, le=32, strict=True)] = 4
    max_verify_cycles: Annotated[int, Field(ge=0, le=16, strict=True)] = 2
    max_requery_cycles: Annotated[int, Field(ge=0, le=16, strict=True)] = 1
    max_decompose_cycles: Annotated[int, Field(ge=0, le=16, strict=True)] = 2
    production_activation: Literal[False] = False


class SupervisorProgress(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-progress/v1"]
    root_cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    last_cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    cycles_consumed: Annotated[int, Field(ge=1, le=32, strict=True)]
    verify_cycles_consumed: Annotated[int, Field(ge=0, le=16, strict=True)]
    requery_cycles_consumed: Annotated[int, Field(ge=0, le=16, strict=True)]
    decompose_cycles_consumed: Annotated[int, Field(ge=0, le=16, strict=True)]
    production_activation: Literal[False]


class SupervisorTransitionCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-transition/v1"]
    transition_id: Annotated[str, Field(pattern=r"^suptrans-[a-f0-9]{32}$")]
    from_cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    next_cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    decision_ref: NonEmptyRef
    from_self_state_ref: NonEmptyRef
    from_workspace_ref: NonEmptyRef
    next_reasoning_mode: ReasoningMode
    next_workspace: CognitiveWorkspace
    next_self_state: PersistentSelfState
    persistence_committed: Literal[False]
    model_invoked: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]


class SupervisorDirective(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-directive/v1"]
    directive_id: Annotated[str, Field(pattern=r"^supdir-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    adjudication_ref: NonEmptyRef
    action: SupervisorAction
    reason: BoundedText
    interrupt_observed: bool
    budget_ref: NonEmptyRef
    progress_before: SupervisorProgress
    progress_if_executed: SupervisorProgress
    transition: SupervisorTransitionCandidate | None
    model_invoked: Literal[False]
    persistence_committed: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def transition_matches_action(self) -> "SupervisorDirective":
        if self.action == "NEXT_CYCLE" and self.transition is None:
            raise ValueError("NEXT_CYCLE requires a transition candidate")
        if self.action != "NEXT_CYCLE" and self.transition is not None:
            raise ValueError("non-NEXT_CYCLE directive cannot carry a transition")
        return self


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:{_digest(value)}"


def supervisor_budget_ref(
    budget: SupervisorBudget | Mapping[str, Any],
) -> str:
    parsed = (
        budget
        if isinstance(budget, SupervisorBudget)
        else SupervisorBudget.model_validate(budget)
    )
    return _ref("supervisor-budget", parsed)


def adjudication_ref(
    result: CognitiveExecutiveResult | Mapping[str, Any],
) -> str:
    parsed = (
        result
        if isinstance(result, CognitiveExecutiveResult)
        else CognitiveExecutiveResult.model_validate(result)
    )
    return _ref("adjudication", parsed.receipt)


def initial_supervisor_progress(*, cycle_id: str) -> SupervisorProgress:
    try:
        return SupervisorProgress(
            schema="kaliv-consciousness-core/supervisor-progress/v1",
            root_cycle_id=cycle_id,
            last_cycle_id=cycle_id,
            cycles_consumed=1,
            verify_cycles_consumed=0,
            requery_cycles_consumed=0,
            decompose_cycles_consumed=0,
            production_activation=False,
        )
    except ValidationError as exc:
        raise CognitiveSupervisorError("invalid initial supervisor cycle id") from exc


def _validate_bindings(
    executive: CognitiveExecutiveResult,
    cycle: CognitiveCycleResult,
    state: PersistentSelfState,
    workspace: CognitiveWorkspace,
    progress: SupervisorProgress,
) -> None:
    receipt = executive.receipt
    cycle_receipt = cycle.receipt

    if receipt.cycle_id != cycle.request.cycle_id:
        raise CognitiveSupervisorError("adjudication belongs to another cycle")
    if receipt.request_id != cycle.request.request_id:
        raise CognitiveSupervisorError("adjudication belongs to another request")
    if receipt.proposal_ref != cycle_receipt.proposal_ref:
        raise CognitiveSupervisorError("adjudication belongs to another proposal")
    if receipt.workspace_ref != cycle_receipt.workspace_ref:
        raise CognitiveSupervisorError("adjudication workspace binding mismatch")
    if workspace.cycle_id != cycle.request.cycle_id:
        raise CognitiveSupervisorError("workspace belongs to another cycle")
    if workspace_ref(workspace) != cycle_receipt.workspace_ref:
        raise CognitiveSupervisorError("workspace does not match cycle receipt")
    if self_state_ref(state) != cycle_receipt.self_state_ref:
        raise CognitiveSupervisorError("SelfState does not match cycle receipt")
    if state.self_id != cycle_receipt.self_id:
        raise CognitiveSupervisorError("SelfState identity mismatch")
    if state.person_revision != cycle_receipt.person_revision:
        raise CognitiveSupervisorError("SelfState Person Revision mismatch")
    if progress.last_cycle_id != cycle.request.cycle_id:
        raise CognitiveSupervisorError("supervisor progress is stale")


def _next_mode(decision: str) -> ReasoningMode:
    if decision == "VERIFY":
        return "verify"
    if decision == "DECOMPOSE":
        return "deep"
    return "normal"


def _budget_exhausted(
    *,
    decision: str,
    progress: SupervisorProgress,
    budget: SupervisorBudget,
) -> str | None:
    if progress.cycles_consumed >= budget.max_cycles:
        return "total cognitive cycle budget exhausted"
    if decision == "VERIFY" and progress.verify_cycles_consumed >= budget.max_verify_cycles:
        return "verification cycle budget exhausted"
    if decision == "REQUERY" and progress.requery_cycles_consumed >= budget.max_requery_cycles:
        return "requery cycle budget exhausted"
    if (
        decision == "DECOMPOSE"
        and progress.decompose_cycles_consumed >= budget.max_decompose_cycles
    ):
        return "decomposition cycle budget exhausted"
    return None


def _progress_after_execution(
    progress: SupervisorProgress,
    *,
    decision: str,
    next_cycle_id: str,
) -> SupervisorProgress:
    return SupervisorProgress(
        schema="kaliv-consciousness-core/supervisor-progress/v1",
        root_cycle_id=progress.root_cycle_id,
        last_cycle_id=next_cycle_id,
        cycles_consumed=progress.cycles_consumed + 1,
        verify_cycles_consumed=(
            progress.verify_cycles_consumed + (1 if decision == "VERIFY" else 0)
        ),
        requery_cycles_consumed=(
            progress.requery_cycles_consumed + (1 if decision == "REQUERY" else 0)
        ),
        decompose_cycles_consumed=(
            progress.decompose_cycles_consumed + (1 if decision == "DECOMPOSE" else 0)
        ),
        production_activation=False,
    )


def _next_workspace(
    *,
    executive: CognitiveExecutiveResult,
    workspace: CognitiveWorkspace,
    next_cycle_id: str,
) -> CognitiveWorkspace:
    decision = executive.receipt.decision
    reasons = "; ".join(executive.receipt.reasons)
    summary = {
        "VERIFY": "Core requires independent verification before accepting cognition.",
        "REQUERY": "Core requires a fresh bounded proposal.",
        "DECOMPOSE": "Core requires decomposition into a more tractable cognitive step.",
    }[decision]
    if reasons:
        summary = f"{summary} Reason: {reasons}"
    summary = summary[:2048]

    seed = {
        "adjudication_id": executive.receipt.adjudication_id,
        "next_cycle_id": next_cycle_id,
        "decision": decision,
    }
    control = WorkspaceCandidate(
        candidate_id="wc-" + _digest(seed)[:32],
        kind="thought_result",
        salience=1.0,
        summary=summary,
        source_ref=f"adjudication:{executive.receipt.adjudication_id}",
    )

    existing = list(workspace.candidates)
    if len(existing) >= 256:
        existing = sorted(
            existing,
            key=lambda item: (-item.salience, item.candidate_id),
        )[:255]

    return build_workspace(
        cycle_id=next_cycle_id,
        candidates=[*existing, control],
        max_active=workspace.max_active,
    )


def plan_supervisor_step(
    executive: CognitiveExecutiveResult | Mapping[str, Any],
    *,
    cycle: CognitiveCycleResult | Mapping[str, Any],
    current_state: PersistentSelfState | Mapping[str, Any],
    workspace: CognitiveWorkspace | Mapping[str, Any],
    progress: SupervisorProgress | Mapping[str, Any],
    budget: SupervisorBudget | Mapping[str, Any] | None = None,
    interrupt_requested: bool = False,
) -> SupervisorDirective:
    """Plan one finite next step. This function never invokes the next cycle."""
    try:
        executive_value = (
            executive
            if isinstance(executive, CognitiveExecutiveResult)
            else CognitiveExecutiveResult.model_validate(executive)
        )
        cycle_value = (
            cycle
            if isinstance(cycle, CognitiveCycleResult)
            else CognitiveCycleResult.model_validate(cycle)
        )
        state = (
            current_state
            if isinstance(current_state, PersistentSelfState)
            else PersistentSelfState.model_validate(current_state)
        )
        workspace_value = (
            workspace
            if isinstance(workspace, CognitiveWorkspace)
            else CognitiveWorkspace.model_validate(workspace)
        )
        progress_value = (
            progress
            if isinstance(progress, SupervisorProgress)
            else SupervisorProgress.model_validate(progress)
        )
        budget_value = (
            SupervisorBudget()
            if budget is None
            else budget
            if isinstance(budget, SupervisorBudget)
            else SupervisorBudget.model_validate(budget)
        )
    except ValidationError as exc:
        raise CognitiveSupervisorError("invalid C17 supervisor input") from exc

    _validate_bindings(
        executive_value,
        cycle_value,
        state,
        workspace_value,
        progress_value,
    )

    adjudication_reference = adjudication_ref(executive_value)
    budget_reference = supervisor_budget_ref(budget_value)
    decision = executive_value.receipt.decision

    action: SupervisorAction
    reason: str
    transition: SupervisorTransitionCandidate | None = None
    progress_after = progress_value

    if interrupt_requested:
        action = "INTERRUPTED"
        reason = "explicit interrupt requested by the caller"
    elif decision == "ACCEPT_COGNITION":
        action = "COMPLETE"
        reason = "cognition accepted; no further cognitive cycle is required"
    elif decision == "HOLD":
        action = "PAUSE"
        reason = "executive placed cognition on hold"
    else:
        exhausted = _budget_exhausted(
            decision=decision,
            progress=progress_value,
            budget=budget_value,
        )
        if exhausted is not None:
            action = "BUDGET_EXHAUSTED"
            reason = exhausted
        else:
            action = "NEXT_CYCLE"
            reason = {
                "VERIFY": "run one bounded verification cycle",
                "REQUERY": "run one bounded fresh-query cycle",
                "DECOMPOSE": "run one bounded decomposition cycle",
            }[decision]

            next_seed = {
                "root_cycle_id": progress_value.root_cycle_id,
                "from_cycle_id": cycle_value.request.cycle_id,
                "adjudication_id": executive_value.receipt.adjudication_id,
                "decision": decision,
                "ordinal": progress_value.cycles_consumed + 1,
            }
            next_cycle_id = "cycle-" + _digest(next_seed)[:32]
            next_workspace = _next_workspace(
                executive=executive_value,
                workspace=workspace_value,
                next_cycle_id=next_cycle_id,
            )
            next_state = advance_self_state(
                state,
                workspace_ref=workspace_ref(next_workspace),
            )
            progress_after = _progress_after_execution(
                progress_value,
                decision=decision,
                next_cycle_id=next_cycle_id,
            )
            transition_seed = {
                "from_cycle_id": cycle_value.request.cycle_id,
                "next_cycle_id": next_cycle_id,
                "adjudication_ref": adjudication_reference,
                "next_state_ref": self_state_ref(next_state),
                "next_workspace_ref": workspace_ref(next_workspace),
            }
            transition = SupervisorTransitionCandidate(
                schema="kaliv-consciousness-core/supervisor-transition/v1",
                transition_id="suptrans-" + _digest(transition_seed)[:32],
                from_cycle_id=cycle_value.request.cycle_id,
                next_cycle_id=next_cycle_id,
                decision_ref=adjudication_reference,
                from_self_state_ref=cycle_value.receipt.self_state_ref,
                from_workspace_ref=cycle_value.receipt.workspace_ref,
                next_reasoning_mode=_next_mode(decision),
                next_workspace=next_workspace,
                next_self_state=next_state,
                persistence_committed=False,
                model_invoked=False,
                execution_authority=False,
                scheduling_authority=False,
                durable_memory_write_authority=False,
                production_activation=False,
            )

    directive_seed = {
        "cycle_id": cycle_value.request.cycle_id,
        "adjudication_ref": adjudication_reference,
        "action": action,
        "reason": reason,
        "interrupt_requested": interrupt_requested,
        "progress_before": progress_value.model_dump(mode="json"),
        "progress_if_executed": progress_after.model_dump(mode="json"),
        "transition_id": transition.transition_id if transition else None,
    }
    return SupervisorDirective(
        schema="kaliv-consciousness-core/supervisor-directive/v1",
        directive_id="supdir-" + _digest(directive_seed)[:32],
        cycle_id=cycle_value.request.cycle_id,
        adjudication_ref=adjudication_reference,
        action=action,
        reason=reason,
        interrupt_observed=interrupt_requested,
        budget_ref=budget_reference,
        progress_before=progress_value,
        progress_if_executed=progress_after,
        transition=transition,
        model_invoked=False,
        persistence_committed=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
