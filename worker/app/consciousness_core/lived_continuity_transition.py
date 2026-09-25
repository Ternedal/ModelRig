"""C31-C reference-only post-cycle lived-continuity reducer.

This seam records that one already-authorized C16 cognitive transition followed a
C31 lived-continuity moment. It does not mutate SelfState, Memory4, identity,
execution, scheduling, or model state.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .lived_continuity import LivedContinuityReceipt
from .reducer import CognitiveTransitionReceipt


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]


class LivedContinuityTransitionError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class LivedContinuityTransitionReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/lived-continuity-transition/v1"]
    transition_id: Annotated[str, Field(pattern=r"^lived-transition-[a-f0-9]{32}$")]
    previous_lived_continuity_ref: NonEmptyRef
    cognitive_transition_ref: NonEmptyRef
    from_cycle_id: CycleId
    to_cycle_id: CycleId
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    previous_self_state_ref: NonEmptyRef
    next_self_state_ref: NonEmptyRef
    previous_workspace_ref: NonEmptyRef
    next_workspace_ref: NonEmptyRef
    proposal_ref: NonEmptyRef
    temporal_state_ref: NonEmptyRef
    active_episode_ref: NonEmptyRef | None
    episode_closure_evidence_ref: NonEmptyRef | None
    episode_review_ref: NonEmptyRef | None
    reference_only: Literal[True]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    model_authority: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def reduce_lived_continuity(
    previous: LivedContinuityReceipt | Mapping[str, Any],
    transition: CognitiveTransitionReceipt | Mapping[str, Any],
    *,
    temporal_state_ref: str,
) -> LivedContinuityTransitionReceipt:
    """Bind a C31 moment to the exact C16 transition without gaining authority."""
    try:
        lived = previous if isinstance(previous, LivedContinuityReceipt) else LivedContinuityReceipt.model_validate(previous)
        moved = transition if isinstance(transition, CognitiveTransitionReceipt) else CognitiveTransitionReceipt.model_validate(transition)
    except ValidationError as exc:
        raise LivedContinuityTransitionError("invalid lived-continuity transition input") from exc

    if lived.cycle_id != moved.from_cycle_id:
        raise LivedContinuityTransitionError("cognitive transition starts from another lived cycle")
    if lived.self_id != moved.self_id:
        raise LivedContinuityTransitionError("cognitive transition belongs to another self")
    if lived.person_revision != moved.person_revision:
        raise LivedContinuityTransitionError("cognitive transition belongs to another Person Revision")
    if lived.self_state_ref != moved.previous_self_state_ref:
        raise LivedContinuityTransitionError("cognitive transition starts from another SelfState")
    if lived.workspace_ref != moved.previous_workspace_ref:
        raise LivedContinuityTransitionError("cognitive transition starts from another workspace")
    if lived.thought_proposal_ref != moved.proposal_ref:
        raise LivedContinuityTransitionError("cognitive transition proposal binding mismatch")
    if not isinstance(temporal_state_ref, str) or not temporal_state_ref.strip():
        raise LivedContinuityTransitionError("temporal_state_ref must be non-empty")

    seed = {
        "previous_lived_continuity_ref": _ref("lived-continuity", lived),
        "cognitive_transition_ref": _ref("cognitive-transition", moved),
        "temporal_state_ref": temporal_state_ref,
    }
    return LivedContinuityTransitionReceipt(
        schema="kaliv-consciousness-core/lived-continuity-transition/v1",
        transition_id="lived-transition-" + hashlib.sha256(_canonical_json(seed)).hexdigest()[:32],
        previous_lived_continuity_ref=seed["previous_lived_continuity_ref"],
        cognitive_transition_ref=seed["cognitive_transition_ref"],
        from_cycle_id=moved.from_cycle_id,
        to_cycle_id=moved.to_cycle_id,
        self_id=moved.self_id,
        person_revision=moved.person_revision,
        previous_self_state_ref=moved.previous_self_state_ref,
        next_self_state_ref=moved.next_self_state_ref,
        previous_workspace_ref=moved.previous_workspace_ref,
        next_workspace_ref=moved.next_workspace_ref,
        proposal_ref=moved.proposal_ref,
        temporal_state_ref=temporal_state_ref,
        active_episode_ref=lived.active_episode_ref,
        episode_closure_evidence_ref=lived.episode_closure_evidence_ref,
        episode_review_ref=lived.episode_review_ref,
        reference_only=True,
        identity_authority=False,
        persistent_state_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        model_authority=False,
        raw_chain_of_thought_persisted=False,
        production_activation=False,
    )
