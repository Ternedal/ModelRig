"""C29-I one-successful-RUN continuity reorientation horizon.

The horizon is process-local and cycle-count based. It owns no clock, timer,
scheduler, model call, persistence or execution authority.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .continuity import (
    ContinuityKnowledge,
    PostWakeContinuityState,
    post_wake_continuity_state_ref,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]


class ContinuityHorizonError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ContinuityReorientationWindow(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/continuity-reorientation-window/v1"
    ]
    continuity_state_ref: NonEmptyRef
    knowledge: ContinuityKnowledge
    state: Literal["ACTIVE", "CONSUMED"]
    remaining_successful_runs: Annotated[
        int,
        Field(ge=0, le=1, strict=True),
    ]
    consumed_cycle_id: CycleId | None
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "ContinuityReorientationWindow":
        if self.state == "ACTIVE":
            if (
                self.remaining_successful_runs != 1
                or self.consumed_cycle_id is not None
            ):
                raise ValueError(
                    "ACTIVE continuity window must have exactly one run"
                )
        else:
            if (
                self.remaining_successful_runs != 0
                or self.consumed_cycle_id is None
            ):
                raise ValueError(
                    "CONSUMED continuity window must bind consumed cycle"
                )
        return self


def open_continuity_reorientation_window(
    state: PostWakeContinuityState,
) -> ContinuityReorientationWindow:
    if not isinstance(state, PostWakeContinuityState):
        raise TypeError("state must be PostWakeContinuityState")
    return ContinuityReorientationWindow(
        schema=(
            "kaliv-consciousness-core/"
            "continuity-reorientation-window/v1"
        ),
        continuity_state_ref=post_wake_continuity_state_ref(state),
        knowledge=state.knowledge,
        state="ACTIVE",
        remaining_successful_runs=1,
        consumed_cycle_id=None,
        model_calls=0,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )


def consume_continuity_reorientation_window(
    window: ContinuityReorientationWindow,
    *,
    cycle_id: str,
) -> ContinuityReorientationWindow:
    if not isinstance(window, ContinuityReorientationWindow):
        raise TypeError(
            "window must be ContinuityReorientationWindow"
        )
    if window.state != "ACTIVE":
        raise ContinuityHorizonError(
            "continuity reorientation window is already consumed"
        )
    try:
        return ContinuityReorientationWindow(
            schema=window.schema,
            continuity_state_ref=window.continuity_state_ref,
            knowledge=window.knowledge,
            state="CONSUMED",
            remaining_successful_runs=0,
            consumed_cycle_id=cycle_id,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )
    except Exception as exc:
        raise ContinuityHorizonError(
            "invalid continuity consumed cycle"
        ) from exc
