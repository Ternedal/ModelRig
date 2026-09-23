"""C29-L minimal read-only continuity status snapshot.

The snapshot intentionally exposes only adjudicated Core refs/semantics. Raw
sleep/liveness lifecycle evidence does not cross this diagnostic boundary.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .continuity import (
    ContinuityKnowledge,
    PostWakeContinuityState,
    post_wake_continuity_state_ref,
)
from .continuity_orientation import (
    ContinuityOrientationState,
    continuity_orientation_state_ref,
)
from .continuity_recovery import (
    ContinuityRecoveryCompletionReceipt,
    continuity_recovery_completion_ref,
)


class ContinuityStatusError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ContinuityStatusSnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/continuity-status-snapshot/v1"
    ]
    status: Literal["NONE", "REORIENTING", "ORIENTED"]
    knowledge: ContinuityKnowledge | None
    continuity_state_ref: str | None
    orientation_state_ref: str | None
    recovery_completion_ref: str | None
    direct_model_context_active: bool
    reorientation_complete: bool
    model_calls: Literal[0]
    persistence_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]


def build_continuity_status_snapshot(
    *,
    continuity_state: PostWakeContinuityState | None,
    orientation: ContinuityOrientationState | None,
    completion: ContinuityRecoveryCompletionReceipt | None,
) -> ContinuityStatusSnapshot:
    """Build one bounded read-only status view with strict evidence pairing."""
    if continuity_state is None:
        if orientation is not None or completion is not None:
            raise ContinuityStatusError(
                "continuity-free status cannot carry orientation/completion"
            )
        return ContinuityStatusSnapshot(
            schema=(
                "kaliv-consciousness-core/"
                "continuity-status-snapshot/v1"
            ),
            status="NONE",
            knowledge=None,
            continuity_state_ref=None,
            orientation_state_ref=None,
            recovery_completion_ref=None,
            direct_model_context_active=False,
            reorientation_complete=False,
            model_calls=0,
            persistence_authority=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    if not isinstance(continuity_state, PostWakeContinuityState):
        raise TypeError(
            "continuity_state must be PostWakeContinuityState or None"
        )
    if not isinstance(orientation, ContinuityOrientationState):
        raise ContinuityStatusError(
            "continuity status requires orientation state"
        )

    continuity_ref = post_wake_continuity_state_ref(continuity_state)
    orientation_ref = continuity_orientation_state_ref(orientation)
    if orientation.continuity_state_ref != continuity_ref:
        raise ContinuityStatusError(
            "orientation belongs to another continuity state"
        )
    if orientation.knowledge != continuity_state.knowledge:
        raise ContinuityStatusError(
            "orientation knowledge does not match continuity state"
        )

    if orientation.phase == "REORIENTING":
        if completion is not None:
            raise ContinuityStatusError(
                "REORIENTING status cannot carry completion"
            )
        return ContinuityStatusSnapshot(
            schema=(
                "kaliv-consciousness-core/"
                "continuity-status-snapshot/v1"
            ),
            status="REORIENTING",
            knowledge=continuity_state.knowledge,
            continuity_state_ref=continuity_ref,
            orientation_state_ref=orientation_ref,
            recovery_completion_ref=None,
            direct_model_context_active=True,
            reorientation_complete=False,
            model_calls=0,
            persistence_authority=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    if not isinstance(completion, ContinuityRecoveryCompletionReceipt):
        raise ContinuityStatusError(
            "ORIENTED status requires recovery completion"
        )
    completion_ref = continuity_recovery_completion_ref(completion)
    if completion.continuity_state_ref != continuity_ref:
        raise ContinuityStatusError(
            "completion belongs to another continuity state"
        )
    if orientation.recovery_completion_ref != completion_ref:
        raise ContinuityStatusError(
            "orientation completion ref does not match completion"
        )
    if orientation.completed_cycle_id != completion.accepted_cycle_id:
        raise ContinuityStatusError(
            "orientation cycle does not match completion"
        )

    return ContinuityStatusSnapshot(
        schema=(
            "kaliv-consciousness-core/continuity-status-snapshot/v1"
        ),
        status="ORIENTED",
        knowledge=continuity_state.knowledge,
        continuity_state_ref=continuity_ref,
        orientation_state_ref=orientation_ref,
        recovery_completion_ref=completion_ref,
        direct_model_context_active=False,
        reorientation_complete=True,
        model_calls=0,
        persistence_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )
