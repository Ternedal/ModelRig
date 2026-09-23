"""C29-K explicit process-local recovery orientation phase.

The state is descriptive Core-owned session context only. It does not mutate
RuntimeWorldState, SelfState, model context, scheduling, persistence or memory.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .continuity import (
    ContinuityKnowledge,
    PostWakeContinuityState,
    post_wake_continuity_state_ref,
)
from .continuity_horizon import ContinuityReorientationWindow
from .continuity_recovery import (
    ContinuityRecoveryCompletionReceipt,
    continuity_recovery_completion_ref,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]


class ContinuityOrientationError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ContinuityOrientationState(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/continuity-orientation-state/v1"
    ]
    orientation_id: Annotated[
        str,
        Field(pattern=r"^orientation-[a-f0-9]{32}$"),
    ]
    continuity_state_ref: NonEmptyRef
    knowledge: ContinuityKnowledge
    phase: Literal["REORIENTING", "ORIENTED"]
    direct_model_context_active: bool
    recovery_completion_ref: NonEmptyRef | None
    completed_cycle_id: CycleId | None
    reorientation_complete: bool
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_phase(self) -> "ContinuityOrientationState":
        if self.phase == "REORIENTING":
            if (
                not self.direct_model_context_active
                or self.recovery_completion_ref is not None
                or self.completed_cycle_id is not None
                or self.reorientation_complete
            ):
                raise ValueError("REORIENTING orientation shape is invalid")
        else:
            if (
                self.direct_model_context_active
                or self.recovery_completion_ref is None
                or self.completed_cycle_id is None
                or not self.reorientation_complete
            ):
                raise ValueError("ORIENTED orientation shape is invalid")
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


def continuity_orientation_state_ref(
    state: ContinuityOrientationState,
) -> str:
    if not isinstance(state, ContinuityOrientationState):
        raise TypeError("state must be ContinuityOrientationState")
    return "continuity-orientation-state:" + _digest(state)


def open_continuity_orientation(
    *,
    continuity_state: PostWakeContinuityState,
    window: ContinuityReorientationWindow,
) -> ContinuityOrientationState:
    if not isinstance(continuity_state, PostWakeContinuityState):
        raise TypeError("continuity_state must be PostWakeContinuityState")
    if not isinstance(window, ContinuityReorientationWindow):
        raise TypeError("window must be ContinuityReorientationWindow")
    continuity_ref = post_wake_continuity_state_ref(continuity_state)
    if window.state != "ACTIVE":
        raise ContinuityOrientationError(
            "open orientation requires ACTIVE reorientation window"
        )
    if window.continuity_state_ref != continuity_ref:
        raise ContinuityOrientationError(
            "reorientation window belongs to another continuity state"
        )
    if window.knowledge != continuity_state.knowledge:
        raise ContinuityOrientationError(
            "reorientation window knowledge mismatch"
        )
    seed = {
        "continuity_state_ref": continuity_ref,
        "phase": "REORIENTING",
    }
    return ContinuityOrientationState(
        schema=(
            "kaliv-consciousness-core/"
            "continuity-orientation-state/v1"
        ),
        orientation_id="orientation-" + _digest(seed)[:32],
        continuity_state_ref=continuity_ref,
        knowledge=continuity_state.knowledge,
        phase="REORIENTING",
        direct_model_context_active=True,
        recovery_completion_ref=None,
        completed_cycle_id=None,
        reorientation_complete=False,
        model_calls=0,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )


def complete_continuity_orientation(
    *,
    previous: ContinuityOrientationState,
    continuity_state: PostWakeContinuityState,
    window: ContinuityReorientationWindow,
    completion: ContinuityRecoveryCompletionReceipt,
) -> ContinuityOrientationState:
    if not isinstance(previous, ContinuityOrientationState):
        raise TypeError("previous must be ContinuityOrientationState")
    if not isinstance(continuity_state, PostWakeContinuityState):
        raise TypeError("continuity_state must be PostWakeContinuityState")
    if not isinstance(window, ContinuityReorientationWindow):
        raise TypeError("window must be ContinuityReorientationWindow")
    if not isinstance(completion, ContinuityRecoveryCompletionReceipt):
        raise TypeError(
            "completion must be ContinuityRecoveryCompletionReceipt"
        )
    if previous.phase != "REORIENTING":
        raise ContinuityOrientationError(
            "only REORIENTING state can become ORIENTED"
        )
    continuity_ref = post_wake_continuity_state_ref(continuity_state)
    if previous.continuity_state_ref != continuity_ref:
        raise ContinuityOrientationError(
            "previous orientation belongs to another continuity state"
        )
    if window.state != "CONSUMED":
        raise ContinuityOrientationError(
            "completion requires consumed reorientation window"
        )
    if window.continuity_state_ref != continuity_ref:
        raise ContinuityOrientationError(
            "consumed window belongs to another continuity state"
        )
    if completion.continuity_state_ref != continuity_ref:
        raise ContinuityOrientationError(
            "completion belongs to another continuity state"
        )
    if completion.accepted_cycle_id != window.consumed_cycle_id:
        raise ContinuityOrientationError(
            "completion cycle does not match consumed window"
        )
    if completion.knowledge != continuity_state.knowledge:
        raise ContinuityOrientationError(
            "completion knowledge mismatch"
        )

    completion_ref = continuity_recovery_completion_ref(completion)
    seed = {
        "continuity_state_ref": continuity_ref,
        "phase": "ORIENTED",
        "recovery_completion_ref": completion_ref,
        "completed_cycle_id": completion.accepted_cycle_id,
    }
    return ContinuityOrientationState(
        schema=(
            "kaliv-consciousness-core/"
            "continuity-orientation-state/v1"
        ),
        orientation_id="orientation-" + _digest(seed)[:32],
        continuity_state_ref=continuity_ref,
        knowledge=continuity_state.knowledge,
        phase="ORIENTED",
        direct_model_context_active=False,
        recovery_completion_ref=completion_ref,
        completed_cycle_id=completion.accepted_cycle_id,
        reorientation_complete=True,
        model_calls=0,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )
