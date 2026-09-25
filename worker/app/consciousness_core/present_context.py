"""C31-B bounded present-context projection for replaceable cognition."""
from __future__ import annotations

from typing import Annotated, Literal, Mapping, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .lived_continuity import LivedContinuityReceipt
from .temporal import TemporalState


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class PresentContextError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class PresentContextProjection(StrictModel):
    schema: Literal["kaliv-consciousness-core/present-context/v1"]
    lived_continuity_ref: NonEmptyRef
    temporal_anchor_ref: NonEmptyRef
    local_day_phase: Literal["night", "morning", "afternoon", "evening"]
    session_elapsed_ms: Annotated[int, Field(ge=0, strict=True)] | None
    continuity_gap_detected: bool
    continuity_gap_ms: Annotated[int, Field(ge=0, strict=True)] | None
    temporal_uncertainty: Annotated[
        float, Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False)
    ]
    active_episode_ref: NonEmptyRef | None
    episode_review_ref: NonEmptyRef | None
    reference_only: Literal[True]
    raw_chain_of_thought_included: Literal[False]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def project_present_context(
    continuity: LivedContinuityReceipt | Mapping[str, Any],
    temporal: TemporalState | Mapping[str, Any],
) -> PresentContextProjection:
    """Expose evidence-backed 'now' context without making the model its owner."""
    try:
        lived = (
            continuity
            if isinstance(continuity, LivedContinuityReceipt)
            else LivedContinuityReceipt.model_validate(continuity)
        )
        now = (
            temporal
            if isinstance(temporal, TemporalState)
            else TemporalState.model_validate(temporal)
        )
    except ValidationError as exc:
        raise PresentContextError("invalid present-context input") from exc

    if lived.self_id != now.self_id:
        raise PresentContextError("temporal state belongs to another self")
    if lived.person_revision != now.person_revision:
        raise PresentContextError(
            "temporal state belongs to another Person Revision"
        )

    return PresentContextProjection(
        schema="kaliv-consciousness-core/present-context/v1",
        lived_continuity_ref="lived-continuity:" + lived.continuity_loop_id,
        temporal_anchor_ref="temporal-anchor:" + now.now_anchor.anchor_id,
        local_day_phase=now.local_day_phase,
        session_elapsed_ms=now.session_elapsed_ms,
        continuity_gap_detected=now.continuity_gap_detected,
        continuity_gap_ms=now.continuity_gap_ms,
        temporal_uncertainty=now.uncertainty,
        active_episode_ref=lived.active_episode_ref,
        episode_review_ref=lived.episode_review_ref,
        reference_only=True,
        raw_chain_of_thought_included=False,
        identity_authority=False,
        persistent_state_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
