"""C18 exactly-one-cycle runtime runner for Consciousness Core.

This module consumes one C17 NEXT_CYCLE directive, requires an injected state
committer to commit the exact transition, runs exactly one C15 cognitive cycle,
adjudicates it once through C16, plans once through C17, and returns control.

It owns no scheduler, retry loop, background task, tool executor, Memory 4 writer,
BodyRig/VoiceRig actuator, or production SelfStateStore implementation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import CognitiveProfile, PersonalitySnapshot
from .cycle import (
    CognitiveCycleCoordinator,
    CognitiveCycleResult,
    RuntimeWorldState,
    proposal_ref,
    self_state_ref,
    workspace_ref,
)
from .executive import (
    CognitiveExecutiveResult,
    ExecutivePolicy,
    adjudicate_cycle,
)
from .goals import GoalRecord
from .metacognition import MetacognitiveState
from .runtime import ConsciousnessCoreRuntime
from .supervisor import (
    SupervisorBudget,
    SupervisorDirective,
    SupervisorTransitionCandidate,
    adjudication_ref,
    plan_supervisor_step,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class CognitiveSingleStepError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class StateTransitionCommitReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/state-transition-commit-receipt/v1"]
    transition_id: Annotated[str, Field(pattern=r"^suptrans-[a-f0-9]{32}$")]
    from_self_state_ref: NonEmptyRef
    committed_self_state_ref: NonEmptyRef
    committed_revision: Annotated[int, Field(ge=1, strict=True)]
    commit_ref: NonEmptyRef
    persisted: Literal[True]
    production_activation: Literal[False]


class StateTransitionCommitter(Protocol):
    """Narrow injected persistence authority.

    C18 intentionally does not implement this against SelfStateStore yet.
    """

    def commit(
        self,
        transition: SupervisorTransitionCandidate,
    ) -> StateTransitionCommitReceipt | Mapping[str, Any]: ...


class CognitiveSingleStepReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/single-step-receipt/v1"]
    step_id: Annotated[str, Field(pattern=r"^cstep-[a-f0-9]{32}$")]
    input_directive_ref: NonEmptyRef
    transition_id: Annotated[str, Field(pattern=r"^suptrans-[a-f0-9]{32}$")]
    commit_ref: NonEmptyRef
    committed_self_state_ref: NonEmptyRef
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    request_id: Annotated[str, Field(pattern=r"^thinkreq-[a-f0-9]{32}$")]
    proposal_ref: NonEmptyRef
    adjudication_ref: NonEmptyRef
    next_directive_ref: NonEmptyRef
    model_invocations: Literal[1]
    adjudications: Literal[1]
    supervisor_plans: Literal[1]
    state_committed_before_cognition: Literal[True]
    recursive_loop: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    body_actuation_authority: Literal[False]
    voice_actuation_authority: Literal[False]
    production_activation: Literal[False]


class CognitiveSingleStepResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/single-step-result/v1"]
    commit: StateTransitionCommitReceipt
    cycle: CognitiveCycleResult
    executive: CognitiveExecutiveResult
    next_directive: SupervisorDirective
    receipt: CognitiveSingleStepReceipt
    production_activation: Literal[False]


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


def supervisor_directive_ref(
    directive: SupervisorDirective | Mapping[str, Any],
) -> str:
    parsed = (
        directive
        if isinstance(directive, SupervisorDirective)
        else SupervisorDirective.model_validate(directive)
    )
    return _ref("supervisor-directive", parsed)


def _validate_transition(
    directive: SupervisorDirective,
) -> SupervisorTransitionCandidate:
    if directive.action != "NEXT_CYCLE" or directive.transition is None:
        raise CognitiveSingleStepError(
            "C18 accepts only a C17 NEXT_CYCLE directive"
        )
    transition = directive.transition
    if transition.next_workspace.cycle_id != transition.next_cycle_id:
        raise CognitiveSingleStepError("transition workspace cycle binding mismatch")
    if transition.next_self_state.workspace_ref != workspace_ref(
        transition.next_workspace
    ):
        raise CognitiveSingleStepError(
            "transition SelfState is not bound to the next workspace"
        )
    if transition.from_cycle_id != directive.cycle_id:
        raise CognitiveSingleStepError("transition source cycle binding mismatch")
    if transition.decision_ref != directive.adjudication_ref:
        raise CognitiveSingleStepError("transition adjudication binding mismatch")
    if directive.progress_if_executed.last_cycle_id != transition.next_cycle_id:
        raise CognitiveSingleStepError("directive progress does not bind the next cycle")
    if transition.model_invoked:
        raise CognitiveSingleStepError("C17 transition already claims a model call")
    if transition.persistence_committed:
        raise CognitiveSingleStepError(
            "C17 transition must be uncommitted before C18"
        )
    return transition


def _commit_transition(
    committer: StateTransitionCommitter,
    transition: SupervisorTransitionCandidate,
) -> StateTransitionCommitReceipt:
    try:
        raw = committer.commit(transition)
    except Exception as exc:
        raise CognitiveSingleStepError(
            "state transition commit failed before cognition"
        ) from exc

    try:
        receipt = (
            raw
            if isinstance(raw, StateTransitionCommitReceipt)
            else StateTransitionCommitReceipt.model_validate(raw)
        )
    except ValidationError as exc:
        raise CognitiveSingleStepError("invalid state transition commit receipt") from exc

    expected_state_ref = self_state_ref(transition.next_self_state)
    if receipt.transition_id != transition.transition_id:
        raise CognitiveSingleStepError("commit receipt belongs to another transition")
    if receipt.from_self_state_ref != transition.from_self_state_ref:
        raise CognitiveSingleStepError("commit receipt source state mismatch")
    if receipt.committed_self_state_ref != expected_state_ref:
        raise CognitiveSingleStepError("commit receipt committed the wrong SelfState")
    if receipt.committed_revision != transition.next_self_state.revision:
        raise CognitiveSingleStepError("commit receipt revision mismatch")
    return receipt


async def run_single_cognitive_step(
    directive: SupervisorDirective | Mapping[str, Any],
    *,
    committer: StateTransitionCommitter,
    runtime: ConsciousnessCoreRuntime,
    world: RuntimeWorldState | Mapping[str, Any],
    personality_snapshot: PersonalitySnapshot | Mapping[str, Any],
    profile: CognitiveProfile | Mapping[str, Any],
    metacognition: MetacognitiveState | Mapping[str, Any],
    relevant_memory_refs: list[str] | None = None,
    embodiment_state_ref: str | None = None,
    active_goal: GoalRecord | Mapping[str, Any] | None = None,
    executive_policy: ExecutivePolicy | Mapping[str, Any] | None = None,
    supervisor_budget: SupervisorBudget | Mapping[str, Any] | None = None,
    interrupt_requested_after_cycle: bool = False,
) -> CognitiveSingleStepResult:
    """Commit and run exactly one next cognitive cycle, then return control."""
    try:
        directive_value = (
            directive
            if isinstance(directive, SupervisorDirective)
            else SupervisorDirective.model_validate(directive)
        )
        world_value = (
            world
            if isinstance(world, RuntimeWorldState)
            else RuntimeWorldState.model_validate(world)
        )
        personality = (
            personality_snapshot
            if isinstance(personality_snapshot, PersonalitySnapshot)
            else PersonalitySnapshot.model_validate(personality_snapshot)
        )
        profile_value = (
            profile
            if isinstance(profile, CognitiveProfile)
            else CognitiveProfile.model_validate(profile)
        )
        meta = (
            metacognition
            if isinstance(metacognition, MetacognitiveState)
            else MetacognitiveState.model_validate(metacognition)
        )
    except ValidationError as exc:
        raise CognitiveSingleStepError("invalid C18 runtime input") from exc

    if not isinstance(runtime, ConsciousnessCoreRuntime):
        raise CognitiveSingleStepError(
            "runtime must be an explicit ConsciousnessCoreRuntime"
        )
    if not isinstance(interrupt_requested_after_cycle, bool):
        raise CognitiveSingleStepError("interrupt flag must be boolean")

    transition = _validate_transition(directive_value)

    # Transaction ordering is deliberate: if this fails or returns the wrong
    # receipt, the ThoughtEngine has not been invoked.
    commit_receipt = _commit_transition(committer, transition)

    cycle = await CognitiveCycleCoordinator(runtime).run(
        state=transition.next_self_state,
        world=world_value,
        workspace=transition.next_workspace,
        personality_snapshot=personality,
        profile=profile_value,
        relevant_memory_refs=relevant_memory_refs,
        embodiment_state_ref=embodiment_state_ref,
        requested_reasoning_mode=transition.next_reasoning_mode,
    )

    if cycle.request.cycle_id != transition.next_cycle_id:
        raise CognitiveSingleStepError("C15 returned the wrong cognitive cycle")
    if cycle.receipt.self_state_ref != commit_receipt.committed_self_state_ref:
        raise CognitiveSingleStepError(
            "C15 cycle is not bound to the committed SelfState"
        )

    executive = adjudicate_cycle(
        cycle,
        workspace=transition.next_workspace,
        metacognition=meta,
        active_goal=active_goal,
        policy=executive_policy,
    )

    next_directive = plan_supervisor_step(
        executive,
        cycle=cycle,
        current_state=transition.next_self_state,
        workspace=transition.next_workspace,
        progress=directive_value.progress_if_executed,
        budget=supervisor_budget,
        interrupt_requested=interrupt_requested_after_cycle,
    )

    input_ref = supervisor_directive_ref(directive_value)
    executive_ref = adjudication_ref(executive)
    next_ref = supervisor_directive_ref(next_directive)
    receipt_seed = {
        "input_directive_ref": input_ref,
        "transition_id": transition.transition_id,
        "commit_ref": commit_receipt.commit_ref,
        "cycle_id": cycle.request.cycle_id,
        "request_id": cycle.request.request_id,
        "proposal_ref": cycle.receipt.proposal_ref,
        "adjudication_ref": executive_ref,
        "next_directive_ref": next_ref,
    }
    receipt = CognitiveSingleStepReceipt(
        schema="kaliv-consciousness-core/single-step-receipt/v1",
        step_id="cstep-" + _digest(receipt_seed)[:32],
        input_directive_ref=input_ref,
        transition_id=transition.transition_id,
        commit_ref=commit_receipt.commit_ref,
        committed_self_state_ref=commit_receipt.committed_self_state_ref,
        cycle_id=cycle.request.cycle_id,
        request_id=cycle.request.request_id,
        proposal_ref=proposal_ref(cycle.proposal),
        adjudication_ref=executive_ref,
        next_directive_ref=next_ref,
        model_invocations=1,
        adjudications=1,
        supervisor_plans=1,
        state_committed_before_cognition=True,
        recursive_loop=False,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        body_actuation_authority=False,
        voice_actuation_authority=False,
        production_activation=False,
    )
    return CognitiveSingleStepResult(
        schema="kaliv-consciousness-core/single-step-result/v1",
        commit=commit_receipt,
        cycle=cycle,
        executive=executive,
        next_directive=next_directive,
        receipt=receipt,
        production_activation=False,
    )
