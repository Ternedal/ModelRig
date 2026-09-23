"""C29-G pure continuity-driven reorientation policy.

The policy may recommend bounded attention salience after wake, but it cannot
schedule cognition, enqueue events, persist state, call a model, or execute.
"""
from __future__ import annotations

from typing import Annotated, Literal, Mapping, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .continuity import (
    ContinuityKnowledge,
    PostWakeContinuityState,
    post_wake_continuity_state_ref,
)


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]

ReorientationMode = Literal[
    "ORDINARY",
    "UNCERTAINTY_ELEVATED",
    "RECOVERY_ELEVATED",
    "RECOVERY_MAXIMUM",
]


class ContinuityReorientationError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ContinuityReorientationPolicy(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/continuity-reorientation-policy/v1"
    ]
    planned_exact_salience: UnitInterval
    planned_unknown_salience: UnitInterval
    unplanned_bounded_salience: UnitInterval
    unplanned_unbounded_salience: UnitInterval
    production_activation: Literal[False]

    @model_validator(mode="after")
    def ordered_salience(self) -> "ContinuityReorientationPolicy":
        values = [
            self.planned_exact_salience,
            self.planned_unknown_salience,
            self.unplanned_bounded_salience,
            self.unplanned_unbounded_salience,
        ]
        if values != sorted(values):
            raise ValueError(
                "continuity reorientation salience must be monotonic"
            )
        return self


DEFAULT_CONTINUITY_REORIENTATION_POLICY = ContinuityReorientationPolicy(
    schema=(
        "kaliv-consciousness-core/continuity-reorientation-policy/v1"
    ),
    planned_exact_salience=0.90,
    planned_unknown_salience=0.95,
    unplanned_bounded_salience=0.98,
    unplanned_unbounded_salience=1.0,
    production_activation=False,
)


class ContinuityReorientationDecision(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/continuity-reorientation-decision/v1"
    ]
    continuity_state_ref: NonEmptyRef
    knowledge: ContinuityKnowledge
    mode: ReorientationMode
    attention_salience: UnitInterval
    reason: Literal[
        "planned_exact_duration",
        "planned_duration_uncertain",
        "unplanned_gap_bounded",
        "unplanned_gap_unbounded",
    ]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    automatic_cognition_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def evaluate_continuity_reorientation(
    state: PostWakeContinuityState | Mapping[str, Any],
    *,
    policy: ContinuityReorientationPolicy = (
        DEFAULT_CONTINUITY_REORIENTATION_POLICY
    ),
) -> ContinuityReorientationDecision:
    """Map already-adjudicated continuity knowledge to bounded salience."""
    try:
        continuity = (
            state
            if isinstance(state, PostWakeContinuityState)
            else PostWakeContinuityState.model_validate(state)
        )
        active_policy = (
            policy
            if isinstance(policy, ContinuityReorientationPolicy)
            else ContinuityReorientationPolicy.model_validate(policy)
        )
    except ValidationError as exc:
        raise ContinuityReorientationError(
            "invalid continuity reorientation input"
        ) from exc

    mapping = {
        "PLANNED_EXACT": (
            "ORDINARY",
            active_policy.planned_exact_salience,
            "planned_exact_duration",
        ),
        "PLANNED_UNKNOWN": (
            "UNCERTAINTY_ELEVATED",
            active_policy.planned_unknown_salience,
            "planned_duration_uncertain",
        ),
        "UNPLANNED_BOUNDED": (
            "RECOVERY_ELEVATED",
            active_policy.unplanned_bounded_salience,
            "unplanned_gap_bounded",
        ),
        "UNPLANNED_UNBOUNDED": (
            "RECOVERY_MAXIMUM",
            active_policy.unplanned_unbounded_salience,
            "unplanned_gap_unbounded",
        ),
    }
    mode, salience, reason = mapping[continuity.knowledge]
    return ContinuityReorientationDecision(
        schema=(
            "kaliv-consciousness-core/"
            "continuity-reorientation-decision/v1"
        ),
        continuity_state_ref=post_wake_continuity_state_ref(
            continuity
        ),
        knowledge=continuity.knowledge,
        mode=mode,
        attention_salience=salience,
        reason=reason,
        model_calls=0,
        self_state_store_write_applied=False,
        automatic_cognition_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
