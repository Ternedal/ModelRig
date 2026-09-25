"""C31-A bounded lived-continuity loop contract.

This slice joins existing temporal, wake, cognitive-cycle and episode references
without creating a new state, memory, scheduling, model, or execution authority.
It is deliberately reference-only so later C31 slices can compose existing
authoritative components without duplicating them.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
SelfId = Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
PersonRevision = Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]


class LivedContinuityError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class LivedContinuityInputs(StrictModel):
    schema: Literal["kaliv-consciousness-core/lived-continuity-inputs/v1"]
    self_id: SelfId
    person_revision: PersonRevision
    cycle_id: CycleId
    self_state_ref: NonEmptyRef
    temporal_state_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    thought_proposal_ref: NonEmptyRef
    active_episode_ref: NonEmptyRef | None = None
    post_wake_continuity_ref: NonEmptyRef | None = None
    wake_orientation_ref: NonEmptyRef | None = None
    episode_closure_evidence_ref: NonEmptyRef | None = None
    episode_review_ref: NonEmptyRef | None = None
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_optional_bindings(self) -> "LivedContinuityInputs":
        if (self.post_wake_continuity_ref is None) != (
            self.wake_orientation_ref is None
        ):
            raise ValueError(
                "post-wake continuity and wake orientation refs must be paired"
            )
        if (
            self.episode_review_ref is not None
            and self.episode_closure_evidence_ref is None
        ):
            raise ValueError(
                "episode review requires closure evidence reference"
            )
        return self


class LivedContinuityReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/lived-continuity-receipt/v1"]
    continuity_loop_id: Annotated[
        str, Field(pattern=r"^lived-[a-f0-9]{32}$")
    ]
    self_id: SelfId
    person_revision: PersonRevision
    cycle_id: CycleId
    self_state_ref: NonEmptyRef
    temporal_state_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    thought_proposal_ref: NonEmptyRef
    active_episode_ref: NonEmptyRef | None
    post_wake_continuity_ref: NonEmptyRef | None
    wake_orientation_ref: NonEmptyRef | None
    episode_closure_evidence_ref: NonEmptyRef | None
    episode_review_ref: NonEmptyRef | None
    reference_only: Literal[True]
    raw_chain_of_thought_persisted: Literal[False]
    cognition_during_gap_claimed: Literal[False]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    model_authority: Literal[False]
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


def build_lived_continuity_receipt(
    inputs: LivedContinuityInputs | Mapping[str, Any],
) -> LivedContinuityReceipt:
    """Join already-authoritative refs into one bounded continuity receipt."""
    try:
        value = (
            inputs
            if isinstance(inputs, LivedContinuityInputs)
            else LivedContinuityInputs.model_validate(inputs)
        )
    except ValidationError as exc:
        raise LivedContinuityError("invalid lived-continuity inputs") from exc

    loop_id = "lived-" + _digest(value)[:32]
    return LivedContinuityReceipt(
        schema="kaliv-consciousness-core/lived-continuity-receipt/v1",
        continuity_loop_id=loop_id,
        self_id=value.self_id,
        person_revision=value.person_revision,
        cycle_id=value.cycle_id,
        self_state_ref=value.self_state_ref,
        temporal_state_ref=value.temporal_state_ref,
        workspace_ref=value.workspace_ref,
        thought_proposal_ref=value.thought_proposal_ref,
        active_episode_ref=value.active_episode_ref,
        post_wake_continuity_ref=value.post_wake_continuity_ref,
        wake_orientation_ref=value.wake_orientation_ref,
        episode_closure_evidence_ref=value.episode_closure_evidence_ref,
        episode_review_ref=value.episode_review_ref,
        reference_only=True,
        raw_chain_of_thought_persisted=False,
        cognition_during_gap_claimed=False,
        identity_authority=False,
        persistent_state_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        model_authority=False,
        production_activation=False,
    )
