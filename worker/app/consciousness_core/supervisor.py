"""C18-A event-driven cognition supervisor kernel.

The supervisor has no thread, timer, polling loop, scheduler, persistence or
execution authority. An external caller supplies bounded events and a trusted
C11 ClockSample, asks for a deterministic plan, and may explicitly run at most
one cognitive cycle.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import CognitiveProfile, PersonalitySnapshot
from .continuity import PostWakeContinuityState
from .cycle import (
    CognitiveCycleCoordinator,
    CognitiveCycleResult,
    CognitiveWorkspace,
    RuntimeWorldState,
    WorkspaceCandidate,
    build_workspace,
    self_state_ref,
    workspace_ref,
)
from .reducer import PostCycleReductionResult, reduce_post_cycle
from .runtime import ConsciousnessCoreRuntime
from .self_state import PersistentSelfState, advance_self_state
from .temporal import ClockSample


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
EventId = Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]
SupervisorId = Annotated[str, Field(pattern=r"^csup-[a-f0-9]{32}$")]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]

EventKind = Literal[
    "user_turn",
    "world_change",
    "embodiment_change",
    "tool_result",
    "memory_recall",
    "prediction_error",
    "wake_followup",
    "operator_signal",
]
Decision = Literal["RUN", "WAIT", "IDLE"]

_MAX_PENDING_EVENTS = 64
_MAX_PRIOR_CANDIDATES = 31


class SupervisorContractError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CognitionEvent(StrictModel):
    schema: Literal["kaliv-consciousness-core/cognition-event/v1"]
    event_id: EventId
    kind: EventKind
    source_ref: NonEmptyRef
    summary: BoundedText
    salience: UnitInterval
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    production_activation: Literal[False]


class SupervisorPolicy(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-policy/v1"]
    min_cycle_interval_ms: Annotated[int, Field(ge=0, le=60000, strict=True)]
    max_events_per_cycle: Annotated[int, Field(ge=1, le=16, strict=True)]
    production_activation: Literal[False]


class SupervisorState(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-state/v1"]
    supervisor_id: SupervisorId
    revision: Annotated[int, Field(ge=1, strict=True)]
    runtime_epoch_id: Annotated[str, Field(pattern=r"^epoch-[a-f0-9]{32}$")]
    pending_events: Annotated[list[CognitionEvent], Field(max_length=64)]
    epoch_started_monotonic_ms: Annotated[int, Field(ge=0, strict=True)]
    epoch_started_clock_sequence: Annotated[int, Field(ge=0, strict=True)]
    last_cycle_id: CycleId | None
    last_cycle_monotonic_ms: Annotated[int | None, Field(ge=0, strict=True)]
    last_cycle_clock_sequence: Annotated[int | None, Field(ge=0, strict=True)]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def unique_events(self) -> "SupervisorState":
        ids = [item.event_id for item in self.pending_events]
        if len(ids) != len(set(ids)):
            raise ValueError("SupervisorState pending event ids must be unique")
        return self


class SupervisorPlan(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-plan/v1"]
    supervisor_id: SupervisorId
    supervisor_revision: Annotated[int, Field(ge=1, strict=True)]
    clock_sample_ref: NonEmptyRef
    policy_ref: NonEmptyRef
    decision: Decision
    selected_event_ids: Annotated[list[EventId], Field(max_length=16)]
    wait_remaining_ms: Annotated[int | None, Field(ge=0, strict=True)]
    thought_engine_calls_authorized: Literal[0, 1]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def decision_shape(self) -> "SupervisorPlan":
        if self.decision == "RUN":
            if not self.selected_event_ids:
                raise ValueError("RUN plan requires selected events")
            if self.wait_remaining_ms is not None:
                raise ValueError("RUN plan cannot have wait_remaining_ms")
            if self.thought_engine_calls_authorized != 1:
                raise ValueError("RUN plan authorizes exactly one ThoughtEngine call")
        else:
            if self.selected_event_ids:
                raise ValueError("WAIT/IDLE plan cannot select events")
            if self.thought_engine_calls_authorized != 0:
                raise ValueError("WAIT/IDLE plan authorizes no ThoughtEngine call")
            if self.decision == "WAIT" and self.wait_remaining_ms is None:
                raise ValueError("WAIT plan requires wait_remaining_ms")
            if self.decision == "IDLE" and self.wait_remaining_ms is not None:
                raise ValueError("IDLE plan cannot wait")
        return self


class SupervisorCycleReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-cycle-receipt/v1"]
    supervisor_id: SupervisorId
    policy_ref: NonEmptyRef
    clock_sample_ref: NonEmptyRef
    selected_event_ids: Annotated[list[EventId], Field(min_length=1, max_length=16)]
    pending_event_count_before: Annotated[int, Field(ge=1, le=64, strict=True)]
    pending_event_count_after: Annotated[int, Field(ge=0, le=64, strict=True)]
    supervisor_revision_before: Annotated[int, Field(ge=1, strict=True)]
    supervisor_revision_after: Annotated[int, Field(ge=2, strict=True)]
    self_revision_before: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after_orientation: Annotated[int, Field(ge=2, strict=True)]
    self_revision_after_cycle: Annotated[int, Field(ge=3, strict=True)]
    cognitive_cycle_id: CycleId
    thought_engine_calls: Literal[1]
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    automatic_repeat: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]


class SupervisorCycleResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-cycle-result/v1"]
    oriented_workspace: CognitiveWorkspace
    oriented_self_state: PersistentSelfState
    cognitive_cycle: CognitiveCycleResult
    reduction: PostCycleReductionResult
    next_supervisor_state: SupervisorState
    receipt: SupervisorCycleReceipt
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


def clock_sample_ref(sample: ClockSample | Mapping[str, Any]) -> str:
    try:
        value = (
            sample
            if isinstance(sample, ClockSample)
            else ClockSample.model_validate(sample)
        )
    except ValidationError as exc:
        raise SupervisorContractError("invalid ClockSample") from exc
    return _ref("clock-sample", value)


def supervisor_policy_ref(policy: SupervisorPolicy | Mapping[str, Any]) -> str:
    try:
        value = (
            policy
            if isinstance(policy, SupervisorPolicy)
            else SupervisorPolicy.model_validate(policy)
        )
    except ValidationError as exc:
        raise SupervisorContractError("invalid SupervisorPolicy") from exc
    return _ref("supervisor-policy", value)


def bootstrap_supervisor(
    *,
    supervisor_id: str,
    clock_sample: ClockSample | Mapping[str, Any],
) -> SupervisorState:
    try:
        clock = (
            clock_sample
            if isinstance(clock_sample, ClockSample)
            else ClockSample.model_validate(clock_sample)
        )
        return SupervisorState(
            schema="kaliv-consciousness-core/supervisor-state/v1",
            supervisor_id=supervisor_id,
            revision=1,
            runtime_epoch_id=clock.runtime_epoch_id,
            pending_events=[],
            epoch_started_monotonic_ms=clock.monotonic_ms,
            epoch_started_clock_sequence=clock.sampled_sequence,
            last_cycle_id=None,
            last_cycle_monotonic_ms=None,
            last_cycle_clock_sequence=None,
            production_activation=False,
        )
    except ValidationError as exc:
        raise SupervisorContractError("invalid supervisor bootstrap") from exc


def queue_cognition_event(
    state: SupervisorState | Mapping[str, Any],
    event: CognitionEvent | Mapping[str, Any],
) -> SupervisorState:
    try:
        current = (
            state
            if isinstance(state, SupervisorState)
            else SupervisorState.model_validate(state)
        )
        incoming = (
            event
            if isinstance(event, CognitionEvent)
            else CognitionEvent.model_validate(event)
        )
    except ValidationError as exc:
        raise SupervisorContractError("invalid supervisor event admission") from exc

    for existing in current.pending_events:
        if existing.event_id == incoming.event_id:
            if existing != incoming:
                raise SupervisorContractError("event id reused with conflicting content")
            return current

    if len(current.pending_events) >= _MAX_PENDING_EVENTS:
        raise SupervisorContractError("supervisor pending-event bound exceeded")

    payload = current.model_dump(mode="python")
    payload["revision"] = current.revision + 1
    payload["pending_events"] = [*current.pending_events, incoming]
    try:
        return SupervisorState.model_validate(payload)
    except ValidationError as exc:
        raise SupervisorContractError("invalid queued supervisor state") from exc


def plan_supervisor_step(
    *,
    state: SupervisorState | Mapping[str, Any],
    clock_sample: ClockSample | Mapping[str, Any],
    policy: SupervisorPolicy | Mapping[str, Any],
) -> SupervisorPlan:
    try:
        current = (
            state
            if isinstance(state, SupervisorState)
            else SupervisorState.model_validate(state)
        )
        clock = (
            clock_sample
            if isinstance(clock_sample, ClockSample)
            else ClockSample.model_validate(clock_sample)
        )
        active_policy = (
            policy
            if isinstance(policy, SupervisorPolicy)
            else SupervisorPolicy.model_validate(policy)
        )
    except ValidationError as exc:
        raise SupervisorContractError("invalid supervisor planning input") from exc

    if clock.runtime_epoch_id != current.runtime_epoch_id:
        raise SupervisorContractError(
            "supervisor cannot cross runtime epochs; wake/bootstrap is required"
        )
    sequence_floor = (
        current.last_cycle_clock_sequence
        if current.last_cycle_clock_sequence is not None
        else current.epoch_started_clock_sequence
    )
    monotonic_floor = (
        current.last_cycle_monotonic_ms
        if current.last_cycle_monotonic_ms is not None
        else current.epoch_started_monotonic_ms
    )
    if clock.sampled_sequence <= sequence_floor:
        raise SupervisorContractError("stale supervisor ClockSample")
    if clock.monotonic_ms < monotonic_floor:
        raise SupervisorContractError("supervisor monotonic clock moved backwards")

    clock_ref = clock_sample_ref(clock)
    policy_ref = supervisor_policy_ref(active_policy)

    if not current.pending_events:
        return SupervisorPlan(
            schema="kaliv-consciousness-core/supervisor-plan/v1",
            supervisor_id=current.supervisor_id,
            supervisor_revision=current.revision,
            clock_sample_ref=clock_ref,
            policy_ref=policy_ref,
            decision="IDLE",
            selected_event_ids=[],
            wait_remaining_ms=None,
            thought_engine_calls_authorized=0,
            execution_authority=False,
            scheduling_authority=False,
            durable_memory_write_authority=False,
            production_activation=False,
        )

    if current.last_cycle_monotonic_ms is not None:
        elapsed = clock.monotonic_ms - current.last_cycle_monotonic_ms
        if elapsed < active_policy.min_cycle_interval_ms:
            return SupervisorPlan(
                schema="kaliv-consciousness-core/supervisor-plan/v1",
                supervisor_id=current.supervisor_id,
                supervisor_revision=current.revision,
                clock_sample_ref=clock_ref,
                policy_ref=policy_ref,
                decision="WAIT",
                selected_event_ids=[],
                wait_remaining_ms=active_policy.min_cycle_interval_ms - elapsed,
                thought_engine_calls_authorized=0,
                execution_authority=False,
                scheduling_authority=False,
                durable_memory_write_authority=False,
                production_activation=False,
            )

    ordered = sorted(
        current.pending_events,
        key=lambda item: (-item.salience, item.observed_sequence, item.event_id),
    )
    selected = ordered[: active_policy.max_events_per_cycle]
    return SupervisorPlan(
        schema="kaliv-consciousness-core/supervisor-plan/v1",
        supervisor_id=current.supervisor_id,
        supervisor_revision=current.revision,
        clock_sample_ref=clock_ref,
        policy_ref=policy_ref,
        decision="RUN",
        selected_event_ids=[item.event_id for item in selected],
        wait_remaining_ms=None,
        thought_engine_calls_authorized=1,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )


def _event_workspace_kind(event: CognitionEvent) -> str:
    return {
        "user_turn": "perception",
        "world_change": "perception",
        "embodiment_change": "body",
        "tool_result": "tool_result",
        "memory_recall": "memory",
        "wake_followup": "perception",
        "prediction_error": "perception",
        "operator_signal": "perception",
    }[event.kind]


def _event_candidate_id(event: CognitionEvent, cycle_id: str) -> str:
    return "wc-" + _digest(
        {
            "event_id": event.event_id,
            "cycle_id": cycle_id,
            "kind": event.kind,
        }
    )[:32]


def _orientation_cycle_id(
    *,
    supervisor_id: str,
    prior_cycle_id: str,
    clock_ref: str,
    event_ids: list[str],
) -> str:
    return "cycle-" + _digest(
        {
            "supervisor_id": supervisor_id,
            "prior_cycle_id": prior_cycle_id,
            "clock_sample_ref": clock_ref,
            "event_ids": event_ids,
            "transition": "supervisor-event-orientation-v1",
        }
    )[:32]


class CognitionSupervisorKernel:
    """Explicit one-shot orchestration only; no hidden continuous runner."""

    def __init__(self, runtime: ConsciousnessCoreRuntime) -> None:
        if not isinstance(runtime, ConsciousnessCoreRuntime):
            raise TypeError("runtime must be ConsciousnessCoreRuntime")
        self._cycle = CognitiveCycleCoordinator(runtime)

    async def run_once(
        self,
        *,
        supervisor_state: SupervisorState | Mapping[str, Any],
        plan: SupervisorPlan | Mapping[str, Any],
        clock_sample: ClockSample | Mapping[str, Any],
        policy: SupervisorPolicy | Mapping[str, Any],
        current_state: PersistentSelfState | Mapping[str, Any],
        current_world: RuntimeWorldState | Mapping[str, Any],
        current_workspace: CognitiveWorkspace | Mapping[str, Any],
        personality_snapshot: PersonalitySnapshot | Mapping[str, Any],
        profile: CognitiveProfile | Mapping[str, Any],
        relevant_memory_refs: list[str] | None = None,
        embodiment_state_ref: str | None = None,
        continuity_state: PostWakeContinuityState | Mapping[str, Any] | None = None,
    ) -> SupervisorCycleResult:
        try:
            sup = (
                supervisor_state
                if isinstance(supervisor_state, SupervisorState)
                else SupervisorState.model_validate(supervisor_state)
            )
            active_plan = (
                plan
                if isinstance(plan, SupervisorPlan)
                else SupervisorPlan.model_validate(plan)
            )
            clock = (
                clock_sample
                if isinstance(clock_sample, ClockSample)
                else ClockSample.model_validate(clock_sample)
            )
            active_policy = (
                policy
                if isinstance(policy, SupervisorPolicy)
                else SupervisorPolicy.model_validate(policy)
            )
            state = (
                current_state
                if isinstance(current_state, PersistentSelfState)
                else PersistentSelfState.model_validate(current_state)
            )
            workspace = (
                current_workspace
                if isinstance(current_workspace, CognitiveWorkspace)
                else CognitiveWorkspace.model_validate(current_workspace)
            )
        except ValidationError as exc:
            raise SupervisorContractError("invalid supervisor run input") from exc

        expected_plan = plan_supervisor_step(
            state=sup,
            clock_sample=clock,
            policy=active_policy,
        )
        if active_plan != expected_plan:
            raise SupervisorContractError("supervisor plan is stale or not canonical")
        if active_plan.decision != "RUN":
            raise SupervisorContractError("run_once requires a RUN supervisor plan")
        if state.workspace_ref != workspace_ref(workspace):
            raise SupervisorContractError(
                "SelfState is not bound to current supervisor workspace"
            )

        selected_ids = set(active_plan.selected_event_ids)
        selected = [item for item in sup.pending_events if item.event_id in selected_ids]
        if len(selected) != len(active_plan.selected_event_ids):
            raise SupervisorContractError("supervisor plan references missing event")

        carried = sorted(
            workspace.candidates,
            key=lambda item: (-item.salience, item.candidate_id),
        )[:_MAX_PRIOR_CANDIDATES]
        orientation_cycle_id = _orientation_cycle_id(
            supervisor_id=sup.supervisor_id,
            prior_cycle_id=workspace.cycle_id,
            clock_ref=active_plan.clock_sample_ref,
            event_ids=active_plan.selected_event_ids,
        )
        event_candidates = [
            WorkspaceCandidate(
                candidate_id=_event_candidate_id(item, orientation_cycle_id),
                kind=_event_workspace_kind(item),
                salience=item.salience,
                summary=item.summary,
                source_ref=item.source_ref,
            )
            for item in selected
        ]
        oriented_workspace = build_workspace(
            cycle_id=orientation_cycle_id,
            candidates=[*event_candidates, *carried],
            max_active=workspace.max_active,
        )
        oriented_state = advance_self_state(
            state,
            workspace_ref=workspace_ref(oriented_workspace),
        )

        if oriented_state.self_id != state.self_id:
            raise SupervisorContractError("supervisor orientation changed self identity")
        if oriented_state.person_id != state.person_id:
            raise SupervisorContractError("supervisor orientation changed person identity")
        if oriented_state.person_revision != state.person_revision:
            raise SupervisorContractError("supervisor orientation changed Person Revision")
        if oriented_state.personality_state_ref != state.personality_state_ref:
            raise SupervisorContractError("supervisor orientation changed personality")
        if oriented_state.world_state_ref != state.world_state_ref:
            raise SupervisorContractError("supervisor orientation changed world binding")
        if oriented_state.active_goal_refs != state.active_goal_refs:
            raise SupervisorContractError("supervisor orientation changed active goals")
        if oriented_state.active_intention_refs != state.active_intention_refs:
            raise SupervisorContractError("supervisor orientation changed intentions")
        if oriented_state.affect != state.affect:
            raise SupervisorContractError("supervisor orientation changed affect")
        if oriented_state.known_uncertainties != state.known_uncertainties:
            raise SupervisorContractError("supervisor orientation changed uncertainties")
        if oriented_state.last_experience_ref != state.last_experience_ref:
            raise SupervisorContractError("supervisor orientation changed memory binding")

        cycle_result = await self._cycle.run(
            state=oriented_state,
            world=current_world,
            workspace=oriented_workspace,
            personality_snapshot=personality_snapshot,
            profile=profile,
            relevant_memory_refs=relevant_memory_refs,
            embodiment_state_ref=embodiment_state_ref,
            continuity_state=continuity_state,
            requested_reasoning_mode="normal",
        )
        reduction = reduce_post_cycle(
            cycle_result,
            current_state=oriented_state,
            current_workspace=oriented_workspace,
        )

        remaining = [
            item for item in sup.pending_events
            if item.event_id not in selected_ids
        ]
        next_sup_payload = sup.model_dump(mode="python")
        next_sup_payload.update(
            {
                "revision": sup.revision + 1,
                "pending_events": remaining,
                "last_cycle_id": cycle_result.receipt.cycle_id,
                "last_cycle_monotonic_ms": clock.monotonic_ms,
                "last_cycle_clock_sequence": clock.sampled_sequence,
            }
        )
        try:
            next_sup = SupervisorState.model_validate(next_sup_payload)
        except ValidationError as exc:
            raise SupervisorContractError("invalid next supervisor state") from exc

        receipt = SupervisorCycleReceipt(
            schema="kaliv-consciousness-core/supervisor-cycle-receipt/v1",
            supervisor_id=sup.supervisor_id,
            policy_ref=active_plan.policy_ref,
            clock_sample_ref=active_plan.clock_sample_ref,
            selected_event_ids=active_plan.selected_event_ids,
            pending_event_count_before=len(sup.pending_events),
            pending_event_count_after=len(next_sup.pending_events),
            supervisor_revision_before=sup.revision,
            supervisor_revision_after=next_sup.revision,
            self_revision_before=state.revision,
            self_revision_after_orientation=oriented_state.revision,
            self_revision_after_cycle=reduction.next_self_state.revision,
            cognitive_cycle_id=cycle_result.receipt.cycle_id,
            thought_engine_calls=1,
            internal_thread_created=False,
            internal_timer_created=False,
            automatic_repeat=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            raw_chain_of_thought_persisted=False,
            production_activation=False,
        )
        return SupervisorCycleResult(
            schema="kaliv-consciousness-core/supervisor-cycle-result/v1",
            oriented_workspace=oriented_workspace,
            oriented_self_state=oriented_state,
            cognitive_cycle=cycle_result,
            reduction=reduction,
            next_supervisor_state=next_sup,
            receipt=receipt,
            production_activation=False,
        )
