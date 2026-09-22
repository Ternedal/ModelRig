"""C20-A provenance-bound epistemic WorldState reducer.

World evidence is admitted by strict Core policy. The reducer does not ask a
model whether evidence is true and never infers epistemic status from free text.
It only records the caller-declared bounded evidence with exact provenance.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cycle import (
    RuntimeWorldState,
    WorldObservation,
    self_state_ref,
    world_state_ref,
)
from .self_state import PersistentSelfState, advance_self_state


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
WorldEvidenceId = Annotated[str, Field(pattern=r"^wevt-[a-f0-9]{32}$")]
EpistemicStatus = Literal["observed", "reported", "inferred", "predicted"]

_MAX_WORLD_OBSERVATIONS = 512


class WorldReducerError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class WorldEvidenceEvent(StrictModel):
    schema: Literal["kaliv-consciousness-core/world-evidence-event/v1"]
    event_id: WorldEvidenceId
    subject_ref: NonEmptyRef
    proposition: BoundedText
    confidence: UnitInterval
    epistemic_status: EpistemicStatus
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def unique_sources(self) -> "WorldEvidenceEvent":
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("WorldEvidenceEvent source_refs must be unique")
        return self


class WorldTransitionReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/world-transition-receipt/v1"]
    event_id: WorldEvidenceId
    observation_id: Annotated[str, Field(pattern=r"^obs-[a-f0-9]{32}$")]
    previous_world_state_ref: NonEmptyRef
    next_world_state_ref: NonEmptyRef
    previous_self_state_ref: NonEmptyRef
    next_self_state_ref: NonEmptyRef
    world_revision_before: Annotated[int, Field(ge=1, strict=True)]
    world_revision_after: Annotated[int, Field(ge=1, strict=True)]
    self_revision_before: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after: Annotated[int, Field(ge=1, strict=True)]
    world_changed: bool
    idempotent_replay: bool
    evicted_observation_ids: Annotated[
        list[str],
        Field(max_length=1),
    ]
    identity_unchanged: Literal[True]
    workspace_binding_unchanged: Literal[True]
    personality_binding_unchanged: Literal[True]
    goal_bindings_unchanged: Literal[True]
    intention_bindings_unchanged: Literal[True]
    affect_unchanged: Literal[True]
    durable_memory_binding_unchanged: Literal[True]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def transition_shape(self) -> "WorldTransitionReceipt":
        if self.idempotent_replay:
            if self.world_changed:
                raise ValueError("idempotent replay cannot change world")
            if self.world_revision_after != self.world_revision_before:
                raise ValueError("idempotent replay cannot advance world revision")
            if self.self_revision_after != self.self_revision_before:
                raise ValueError("idempotent replay cannot advance self revision")
            if self.evicted_observation_ids:
                raise ValueError("idempotent replay cannot evict observations")
        else:
            if not self.world_changed:
                raise ValueError("new evidence must change world")
            if self.world_revision_after != self.world_revision_before + 1:
                raise ValueError("world revision must advance exactly by one")
            if self.self_revision_after != self.self_revision_before + 1:
                raise ValueError("SelfState revision must advance exactly by one")
        return self


class WorldTransitionResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/world-transition-result/v1"]
    world: RuntimeWorldState
    state: PersistentSelfState
    receipt: WorldTransitionReceipt
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


def _observation_id(event_id: str) -> str:
    return "obs-" + _digest(
        {"world_evidence_event_id": event_id}
    )[:32]


def _to_observation(event: WorldEvidenceEvent) -> WorldObservation:
    return WorldObservation(
        observation_id=_observation_id(event.event_id),
        subject_ref=event.subject_ref,
        proposition=event.proposition,
        confidence=event.confidence,
        epistemic_status=event.epistemic_status,
        source_refs=event.source_refs,
    )


def _verify_preserved(
    before: PersistentSelfState,
    after: PersistentSelfState,
) -> None:
    if after.self_id != before.self_id or after.person_id != before.person_id:
        raise WorldReducerError("world transition changed identity")
    if after.person_revision != before.person_revision:
        raise WorldReducerError("world transition changed Person Revision")
    if after.workspace_ref != before.workspace_ref:
        raise WorldReducerError("world transition changed workspace binding")
    if after.personality_state_ref != before.personality_state_ref:
        raise WorldReducerError("world transition changed personality binding")
    if after.active_goal_refs != before.active_goal_refs:
        raise WorldReducerError("world transition changed active goals")
    if after.active_intention_refs != before.active_intention_refs:
        raise WorldReducerError("world transition changed active intentions")
    if after.affect != before.affect:
        raise WorldReducerError("world transition changed affect")
    if after.known_uncertainties != before.known_uncertainties:
        raise WorldReducerError("world transition changed durable uncertainties")
    if after.last_experience_ref != before.last_experience_ref:
        raise WorldReducerError("world transition changed memory binding")


def reduce_world_evidence(
    *,
    state: PersistentSelfState | Mapping[str, Any],
    world: RuntimeWorldState | Mapping[str, Any],
    evidence: WorldEvidenceEvent | Mapping[str, Any],
) -> WorldTransitionResult:
    """Admit one provenance-bound evidence item into live WorldState."""
    try:
        current_state = (
            state
            if isinstance(state, PersistentSelfState)
            else PersistentSelfState.model_validate(state)
        )
        current_world = (
            world
            if isinstance(world, RuntimeWorldState)
            else RuntimeWorldState.model_validate(world)
        )
        event = (
            evidence
            if isinstance(evidence, WorldEvidenceEvent)
            else WorldEvidenceEvent.model_validate(evidence)
        )
    except ValidationError as exc:
        raise WorldReducerError("invalid world-reducer input") from exc

    previous_world_ref = world_state_ref(current_world)
    previous_self_ref = self_state_ref(current_state)
    if current_state.world_state_ref != previous_world_ref:
        raise WorldReducerError(
            "SelfState is not bound to the supplied RuntimeWorldState"
        )

    projected = _to_observation(event)
    existing = next(
        (
            item
            for item in current_world.observations
            if item.observation_id == projected.observation_id
        ),
        None,
    )

    if existing is not None:
        if existing != projected:
            raise WorldReducerError(
                "world evidence event id reused with conflicting evidence"
            )
        receipt = WorldTransitionReceipt(
            schema="kaliv-consciousness-core/world-transition-receipt/v1",
            event_id=event.event_id,
            observation_id=projected.observation_id,
            previous_world_state_ref=previous_world_ref,
            next_world_state_ref=previous_world_ref,
            previous_self_state_ref=previous_self_ref,
            next_self_state_ref=previous_self_ref,
            world_revision_before=current_world.revision,
            world_revision_after=current_world.revision,
            self_revision_before=current_state.revision,
            self_revision_after=current_state.revision,
            world_changed=False,
            idempotent_replay=True,
            evicted_observation_ids=[],
            identity_unchanged=True,
            workspace_binding_unchanged=True,
            personality_binding_unchanged=True,
            goal_bindings_unchanged=True,
            intention_bindings_unchanged=True,
            affect_unchanged=True,
            durable_memory_binding_unchanged=True,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
        return WorldTransitionResult(
            schema="kaliv-consciousness-core/world-transition-result/v1",
            world=current_world,
            state=current_state,
            receipt=receipt,
            production_activation=False,
        )

    observations = [*current_world.observations, projected]
    evicted: list[str] = []
    if len(observations) > _MAX_WORLD_OBSERVATIONS:
        removed = observations.pop(0)
        evicted = [removed.observation_id]

    next_world = RuntimeWorldState(
        schema=current_world.schema,
        world_id=current_world.world_id,
        revision=current_world.revision + 1,
        observations=observations,
        production_activation=False,
    )
    next_world_ref = world_state_ref(next_world)
    next_state = advance_self_state(
        current_state,
        world_state_ref=next_world_ref,
    )
    _verify_preserved(current_state, next_state)

    receipt = WorldTransitionReceipt(
        schema="kaliv-consciousness-core/world-transition-receipt/v1",
        event_id=event.event_id,
        observation_id=projected.observation_id,
        previous_world_state_ref=previous_world_ref,
        next_world_state_ref=next_world_ref,
        previous_self_state_ref=previous_self_ref,
        next_self_state_ref=self_state_ref(next_state),
        world_revision_before=current_world.revision,
        world_revision_after=next_world.revision,
        self_revision_before=current_state.revision,
        self_revision_after=next_state.revision,
        world_changed=True,
        idempotent_replay=False,
        evicted_observation_ids=evicted,
        identity_unchanged=True,
        workspace_binding_unchanged=True,
        personality_binding_unchanged=True,
        goal_bindings_unchanged=True,
        intention_bindings_unchanged=True,
        affect_unchanged=True,
        durable_memory_binding_unchanged=True,
        model_calls=0,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
    return WorldTransitionResult(
        schema="kaliv-consciousness-core/world-transition-result/v1",
        world=next_world,
        state=next_state,
        receipt=receipt,
        production_activation=False,
    )
