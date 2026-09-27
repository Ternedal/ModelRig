"""C31-F default-off continuous-loop supervisor composition seam.

This module composes references to the existing scheduler, wake and cognitive
supervisor primitives. It deliberately does not create a loop, timer, thread,
model call, execution path, or scheduler authority of its own.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .supervisor import SupervisorPlan
from .wake_cycle import WakeOrientationReceipt


CONTINUOUS_LOOP_FLAG = "KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED"
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class ContinuousLoopSupervisorError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ContinuousLoopSupervisorPlan(StrictModel):
    schema: Literal["kaliv-consciousness-core/continuous-loop-supervisor-plan/v1"]
    plan_id: Annotated[str, Field(pattern=r"^cloop-[a-f0-9]{32}$")]
    enabled: bool
    scheduler_tick_ref: NonEmptyRef | None
    supervisor_plan_ref: NonEmptyRef | None
    wake_orientation_ref: NonEmptyRef | None
    disposition: Literal["DISABLED", "IDLE", "DEFER", "RUN_ONE_CYCLE"]
    max_cognitive_cycles: Literal[0, 1]
    explicit_wake_reorientation: bool
    automatic_repeat: Literal[False]
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    identity_authority: Literal[False]
    model_authority: Literal[False]
    agent3_execution_required: Literal[True]
    existing_gates_required: Literal[True]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "ContinuousLoopSupervisorPlan":
        if not self.enabled:
            if self.disposition != "DISABLED" or self.max_cognitive_cycles != 0:
                raise ValueError("disabled loop plan must remain inert")
        if self.disposition == "RUN_ONE_CYCLE":
            if self.max_cognitive_cycles != 1 or self.supervisor_plan_ref is None:
                raise ValueError("run plan requires exactly one supervisor-authorized cycle")
            if self.scheduler_tick_ref is None:
                raise ValueError("run plan requires scheduler evidence")
        elif self.max_cognitive_cycles != 0:
            raise ValueError("non-run loop plan cannot authorize a cycle")
        if self.wake_orientation_ref is not None and not self.explicit_wake_reorientation:
            raise ValueError("wake reference requires explicit reorientation")
        return self


def enabled(env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get(CONTINUOUS_LOOP_FLAG, "0") == "1"


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value=value.model_dump(mode="json")
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()


def _ref(kind: str, value: Any) -> str:
    return kind+":"+hashlib.sha256(_canonical_json(value)).hexdigest()


def plan_continuous_loop_step(
    *,
    scheduler_tick_ref: str | None,
    supervisor_plan: SupervisorPlan | Mapping[str, Any] | None,
    wake_orientation: WakeOrientationReceipt | Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ContinuousLoopSupervisorPlan:
    """Compose one externally driven step; never self-schedule or self-repeat."""
    is_enabled=enabled(env)
    if not is_enabled:
        disposition="DISABLED"
        cycles=0
        supervisor_ref=None
        wake_ref=None
        tick_ref=None
    else:
        if not isinstance(scheduler_tick_ref,str) or not scheduler_tick_ref.strip():
            raise ContinuousLoopSupervisorError("enabled composition requires scheduler_tick_ref")
        tick_ref=scheduler_tick_ref
        try:
            plan=None if supervisor_plan is None else (
                supervisor_plan if isinstance(supervisor_plan,SupervisorPlan)
                else SupervisorPlan.model_validate(supervisor_plan)
            )
            wake=None if wake_orientation is None else (
                wake_orientation if isinstance(wake_orientation,WakeOrientationReceipt)
                else WakeOrientationReceipt.model_validate(wake_orientation)
            )
        except ValidationError as exc:
            raise ContinuousLoopSupervisorError("invalid continuous-loop input") from exc
        if plan is None:
            disposition="IDLE";cycles=0;supervisor_ref=None
        else:
            supervisor_ref=_ref("supervisor-plan",plan)
            disposition={"RUN":"RUN_ONE_CYCLE","WAIT":"DEFER","IDLE":"IDLE"}[plan.decision]
            cycles=1 if plan.decision=="RUN" else 0
        wake_ref=None if wake is None else _ref("wake-orientation",wake)

    seed={"enabled":is_enabled,"scheduler_tick_ref":tick_ref,"supervisor_plan_ref":supervisor_ref,"wake_orientation_ref":wake_ref,"disposition":disposition}
    return ContinuousLoopSupervisorPlan(
        schema="kaliv-consciousness-core/continuous-loop-supervisor-plan/v1",
        plan_id="cloop-"+hashlib.sha256(_canonical_json(seed)).hexdigest()[:32],
        enabled=is_enabled,
        scheduler_tick_ref=tick_ref,
        supervisor_plan_ref=supervisor_ref,
        wake_orientation_ref=wake_ref,
        disposition=disposition,
        max_cognitive_cycles=cycles,
        explicit_wake_reorientation=wake_ref is not None,
        automatic_repeat=False,
        internal_thread_created=False,
        internal_timer_created=False,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        identity_authority=False,
        model_authority=False,
        agent3_execution_required=True,
        existing_gates_required=True,
        production_activation=False,
    )
