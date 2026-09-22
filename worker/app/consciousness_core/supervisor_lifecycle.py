"""C18-B default-off production lifecycle seam for the cognition supervisor.

This module wires the C18-A kernel into the worker process without creating a
route, background task, timer, polling loop or autonomous model invocation.

Activation requires BOTH exact opt-ins:
- KALIV_CONSCIOUSNESS_CORE_ENABLED=1
- KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED=1

Even when enabled, cognition happens only when an in-process caller explicitly
submits bounded CognitionEvent values and awaits bridge.step(...) with exact
current cognitive snapshots.
"""
from __future__ import annotations

import hashlib
import os
import re
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from .contracts import CognitiveProfile, PersonalitySnapshot
from .cycle import CognitiveWorkspace, RuntimeWorldState
from .production_lifecycle import TrustedRuntimeClock
from .runtime import ConsciousnessCoreRuntime, compose_runtime, enabled as core_enabled
from .self_state import PersistentSelfState
from .supervisor import (
    CognitionEvent,
    CognitionSupervisorKernel,
    SupervisorCycleResult,
    SupervisorPlan,
    SupervisorPolicy,
    SupervisorState,
    bootstrap_supervisor,
    plan_supervisor_step,
    queue_cognition_event,
)
from .temporal import ClockSample


SUPERVISOR_LIFECYCLE_FLAG = "KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED"

_DEFAULT_POLICY = SupervisorPolicy(
    schema="kaliv-consciousness-core/supervisor-policy/v1",
    min_cycle_interval_ms=500,
    max_events_per_cycle=4,
    production_activation=False,
)


class SupervisorLifecycleError(RuntimeError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class SupervisorBridgeStep(_StrictModel):
    schema: Literal["kaliv-consciousness-core/supervisor-bridge-step/v1"] = (
        "kaliv-consciousness-core/supervisor-bridge-step/v1"
    )
    clock_sample: ClockSample
    plan: SupervisorPlan
    cycle_result: SupervisorCycleResult | None
    thought_engine_invoked: bool
    internal_thread_created: Literal[False] = False
    internal_timer_created: Literal[False] = False
    automatic_repeat: Literal[False] = False
    production_activation: Literal[False] = False


def supervisor_lifecycle_enabled(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Fail closed: only the exact string '1' enables C18-B."""
    if env is None:
        return os.getenv("KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED", "0") == "1"
    return env.get("KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED", "0") == "1"


def _supervisor_id(runtime_epoch_id: str) -> str:
    digest = hashlib.sha256(
        ("c18b-supervisor|" + runtime_epoch_id).encode("utf-8")
    ).hexdigest()
    return "csup-" + digest[:32]


class ProductionSupervisorBridge:
    """In-memory explicit-call bridge around the C18-A supervisor kernel.

    The bridge does not own a scheduler. submit() only queues bounded context.
    plan() only evaluates deterministic pacing. step() samples the trusted clock
    and performs at most one model call if and only if the resulting plan is RUN.
    """

    def __init__(
        self,
        *,
        runtime: ConsciousnessCoreRuntime,
        clock: TrustedRuntimeClock,
        policy: SupervisorPolicy = _DEFAULT_POLICY,
    ) -> None:
        if not isinstance(runtime, ConsciousnessCoreRuntime):
            raise TypeError("runtime must be ConsciousnessCoreRuntime")
        if not isinstance(clock, TrustedRuntimeClock):
            raise TypeError("clock must be TrustedRuntimeClock")
        if not isinstance(policy, SupervisorPolicy):
            raise TypeError("policy must be SupervisorPolicy")

        bootstrap_clock = clock.sample()
        self._clock = clock
        self._policy = policy
        self._kernel = CognitionSupervisorKernel(runtime)
        self._state = bootstrap_supervisor(
            supervisor_id=_supervisor_id(bootstrap_clock.runtime_epoch_id),
            clock_sample=bootstrap_clock,
        )
        self._closed = False
        self._in_step = False

    @property
    def state(self) -> SupervisorState:
        return self._state

    @property
    def policy(self) -> SupervisorPolicy:
        return self._policy

    @property
    def closed(self) -> bool:
        return self._closed

    def _require_open(self) -> None:
        if self._closed:
            raise SupervisorLifecycleError("supervisor bridge is closed")

    def _require_available(self) -> None:
        self._require_open()
        if self._in_step:
            raise SupervisorLifecycleError(
                "supervisor bridge step already in progress"
            )

    def submit(
        self,
        event: CognitionEvent | Mapping[str, Any],
    ) -> SupervisorState:
        self._require_available()
        self._state = queue_cognition_event(self._state, event)
        return self._state

    def plan(self) -> tuple[ClockSample, SupervisorPlan]:
        self._require_available()
        clock = self._clock.sample()
        plan = plan_supervisor_step(
            state=self._state,
            clock_sample=clock,
            policy=self._policy,
        )
        return clock, plan

    async def step(
        self,
        *,
        current_state: PersistentSelfState | Mapping[str, Any],
        current_world: RuntimeWorldState | Mapping[str, Any],
        current_workspace: CognitiveWorkspace | Mapping[str, Any],
        personality_snapshot: PersonalitySnapshot | Mapping[str, Any],
        profile: CognitiveProfile | Mapping[str, Any],
        relevant_memory_refs: list[str] | None = None,
        embodiment_state_ref: str | None = None,
        required_event_id: str | None = None,
        allowed_event_ids: list[str] | None = None,
    ) -> SupervisorBridgeStep:
        """Evaluate one supervisor step; never loops or retries automatically."""
        self._require_available()
        self._in_step = True
        try:
            clock = self._clock.sample()
            plan = plan_supervisor_step(
                state=self._state,
                clock_sample=clock,
                policy=self._policy,
            )

            if required_event_id is not None:
                if (
                    not isinstance(required_event_id, str)
                    or re.fullmatch(r"cevt-[a-f0-9]{32}", required_event_id) is None
                ):
                    raise SupervisorLifecycleError(
                        "required_event_id is not a valid CognitionEvent id"
                    )
                if not any(
                    event.event_id == required_event_id
                    for event in self._state.pending_events
                ):
                    raise SupervisorLifecycleError(
                        "required cognition event is not pending"
                    )
                if (
                    plan.decision == "RUN"
                    and required_event_id not in plan.selected_event_ids
                ):
                    raise SupervisorLifecycleError(
                        "required cognition event is not selected by canonical plan"
                    )

            if allowed_event_ids is not None:
                if not isinstance(allowed_event_ids, list):
                    raise SupervisorLifecycleError(
                        "allowed_event_ids must be a list when supplied"
                    )
                if len(allowed_event_ids) > 64 or len(allowed_event_ids) != len(
                    set(allowed_event_ids)
                ):
                    raise SupervisorLifecycleError(
                        "allowed cognition event set is invalid"
                    )
                for event_id in allowed_event_ids:
                    if (
                        not isinstance(event_id, str)
                        or re.fullmatch(r"cevt-[a-f0-9]{32}", event_id) is None
                    ):
                        raise SupervisorLifecycleError(
                            "allowed cognition event id is invalid"
                        )
                allowed = set(allowed_event_ids)
                if required_event_id is not None and required_event_id not in allowed:
                    raise SupervisorLifecycleError(
                        "required cognition event is outside allowed event set"
                    )
                if plan.decision == "RUN" and any(
                    event_id not in allowed
                    for event_id in plan.selected_event_ids
                ):
                    raise SupervisorLifecycleError(
                        "canonical plan selected an event outside allowed set"
                    )

            if plan.decision != "RUN":
                return SupervisorBridgeStep(
                    clock_sample=clock,
                    plan=plan,
                    cycle_result=None,
                    thought_engine_invoked=False,
                    internal_thread_created=False,
                    internal_timer_created=False,
                    automatic_repeat=False,
                    production_activation=False,
                )

            state_before = self._state
            result = await self._kernel.run_once(
                supervisor_state=state_before,
                plan=plan,
                clock_sample=clock,
                policy=self._policy,
                current_state=current_state,
                current_world=current_world,
                current_workspace=current_workspace,
                personality_snapshot=personality_snapshot,
                profile=profile,
                relevant_memory_refs=relevant_memory_refs,
                embodiment_state_ref=embodiment_state_ref,
            )
            if self._state is not state_before:
                raise SupervisorLifecycleError(
                    "supervisor state changed during single-flight step"
                )
            self._state = result.next_supervisor_state
            return SupervisorBridgeStep(
                clock_sample=clock,
                plan=plan,
                cycle_result=result,
                thought_engine_invoked=True,
                internal_thread_created=False,
                internal_timer_created=False,
                automatic_repeat=False,
                production_activation=False,
            )
        finally:
            self._in_step = False

    def close(self) -> None:
        # No durable state is written. Closing only blocks future in-process use.
        self._closed = True


def production_supervisor_bridge_factory(
    _app,
    *,
    runtime_factory=compose_runtime,
    clock_factory=TrustedRuntimeClock,
) -> ProductionSupervisorBridge | None:
    """Build the bridge only after the exact double opt-in.

    The ordering matters: with the supervisor flag off, C18-B does not even
    inspect/compose the model runtime. With supervisor on but Core off, provider
    composition is still skipped.
    """
    if not supervisor_lifecycle_enabled():
        return None
    if not core_enabled():
        return None

    runtime = runtime_factory()
    if runtime is None:
        raise SupervisorLifecycleError(
            "Consciousness Core runtime unavailable after exact double opt-in"
        )
    clock = clock_factory()
    return ProductionSupervisorBridge(
        runtime=runtime,
        clock=clock,
    )


def compose_supervisor_lifecycle_lifespan(
    inner_lifespan,
    bridge_factory=production_supervisor_bridge_factory,
):
    """Compose C18-B around production lifespan without taking scheduler ownership."""
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if not callable(bridge_factory):
        raise TypeError("bridge_factory must be callable")

    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app):
        async with inner_lifespan(app):
            bridge = bridge_factory(app)
            if bridge is not None and not isinstance(
                bridge,
                ProductionSupervisorBridge,
            ):
                raise TypeError(
                    "bridge_factory must return ProductionSupervisorBridge or None"
                )

            if bridge is not None:
                app.state.consciousness_supervisor = bridge
            try:
                yield
            finally:
                if bridge is not None:
                    bridge.close()
                    try:
                        delattr(app.state, "consciousness_supervisor")
                    except AttributeError:
                        pass

    composed.__wrapped__ = authority_owner
    return composed
