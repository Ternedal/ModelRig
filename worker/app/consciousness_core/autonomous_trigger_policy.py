"""C25-A bounded autonomous cognition trigger policy.

Pure policy only. This module never schedules, invokes ThoughtEngine, consumes an
event, persists state or executes an action. It decides whether one already-
admitted CognitionEvent may later request one automatic exact-event step.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .supervisor import CognitionEvent
from .temporal import ClockSample


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
TriggerDecision = Literal["DENY", "DEFER", "ELIGIBLE"]
TriggerReason = Literal[
    "event_kind_denied",
    "salience_below_threshold",
    "runtime_epoch_changed",
    "cooldown_active",
    "window_budget_exhausted",
    "eligible",
]


class AutonomousTriggerPolicyError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class AutonomousTriggerPolicy(StrictModel):
    schema: Literal["kaliv-consciousness-core/autonomous-trigger-policy/v1"]
    window_ms: Annotated[int, Field(ge=1_000, le=86_400_000, strict=True)]
    max_steps_per_window: Annotated[int, Field(ge=1, le=64, strict=True)]
    cooldown_ms: Annotated[int, Field(ge=0, le=86_400_000, strict=True)]
    world_change_min_salience: UnitInterval
    embodiment_change_min_salience: UnitInterval
    memory_recall_min_salience: UnitInterval
    prediction_error_min_salience: UnitInterval
    wake_followup_enabled: bool
    production_activation: Literal[False]

    @model_validator(mode="after")
    def bounded_cooldown(self) -> "AutonomousTriggerPolicy":
        if self.cooldown_ms > self.window_ms:
            raise ValueError("cooldown_ms cannot exceed window_ms")
        return self


class AutomaticCognitionAccounting(StrictModel):
    schema: Literal["kaliv-consciousness-core/automatic-cognition-accounting/v1"]
    runtime_epoch_id: Annotated[str, Field(pattern=r"^epoch-[a-f0-9]{32}$")]
    window_started_monotonic_ms: NonNegativeInt
    automatic_steps_in_window: Annotated[int, Field(ge=0, le=64, strict=True)]
    last_automatic_step_monotonic_ms: NonNegativeInt | None
    production_activation: Literal[False]

    @model_validator(mode="after")
    def monotonic_shape(self) -> "AutomaticCognitionAccounting":
        if (
            self.last_automatic_step_monotonic_ms is not None
            and self.last_automatic_step_monotonic_ms
            < self.window_started_monotonic_ms
        ):
            raise ValueError("last automatic step predates accounting window")
        return self


class AutonomousTriggerDecision(StrictModel):
    schema: Literal["kaliv-consciousness-core/autonomous-trigger-decision/v1"]
    decision_id: Annotated[str, Field(pattern=r"^autodec-[a-f0-9]{32}$")]
    event_id: Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]
    event_kind: str
    event_salience: UnitInterval
    clock_sample_id: Annotated[str, Field(pattern=r"^clock-[a-f0-9]{32}$")]
    runtime_epoch_id: Annotated[str, Field(pattern=r"^epoch-[a-f0-9]{32}$")]
    decision: TriggerDecision
    reason: TriggerReason
    not_before_monotonic_ms: NonNegativeInt | None
    effective_window_started_monotonic_ms: NonNegativeInt
    effective_steps_in_window: Annotated[int, Field(ge=0, le=64, strict=True)]
    budget_remaining: Annotated[int, Field(ge=0, le=64, strict=True)]
    policy_ref: Annotated[str, Field(min_length=1, max_length=256)]
    event_consumed: Literal[False]
    model_calls: Literal[0]
    scheduling_authority: Literal[False]
    execution_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]


class AutomaticCognitionRecordReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/automatic-cognition-record/v1"]
    decision_id: Annotated[str, Field(pattern=r"^autodec-[a-f0-9]{32}$")]
    event_id: Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]
    clock_sample_id: Annotated[str, Field(pattern=r"^clock-[a-f0-9]{32}$")]
    previous_steps_in_window: Annotated[int, Field(ge=0, le=63, strict=True)]
    next_steps_in_window: Annotated[int, Field(ge=1, le=64, strict=True)]
    accounting: AutomaticCognitionAccounting
    model_calls_authorized_here: Literal[0]
    scheduling_authority: Literal[False]
    execution_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]


DEFAULT_AUTONOMOUS_TRIGGER_POLICY = AutonomousTriggerPolicy(
    schema="kaliv-consciousness-core/autonomous-trigger-policy/v1",
    window_ms=300_000,
    max_steps_per_window=4,
    cooldown_ms=30_000,
    world_change_min_salience=0.80,
    embodiment_change_min_salience=0.85,
    memory_recall_min_salience=0.85,
    prediction_error_min_salience=0.75,
    wake_followup_enabled=True,
    production_activation=False,
)


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _ref(prefix: str, value: Any) -> str:
    return prefix + ":" + hashlib.sha256(_canonical_json(value)).hexdigest()


def autonomous_trigger_policy_ref(policy: AutonomousTriggerPolicy) -> str:
    if not isinstance(policy, AutonomousTriggerPolicy):
        raise TypeError("policy must be AutonomousTriggerPolicy")
    return _ref("autonomous-trigger-policy", policy)


def _decision_id(seed: Mapping[str, Any]) -> str:
    return "autodec-" + hashlib.sha256(_canonical_json(seed)).hexdigest()[:32]


def new_automatic_cognition_accounting(
    clock: ClockSample,
) -> AutomaticCognitionAccounting:
    if not isinstance(clock, ClockSample):
        raise TypeError("clock must be ClockSample")
    return AutomaticCognitionAccounting(
        schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
        runtime_epoch_id=clock.runtime_epoch_id,
        window_started_monotonic_ms=clock.monotonic_ms,
        automatic_steps_in_window=0,
        last_automatic_step_monotonic_ms=None,
        production_activation=False,
    )


def _eligibility_threshold(
    event: CognitionEvent,
    policy: AutonomousTriggerPolicy,
) -> float | None:
    if event.kind in {"user_turn", "operator_signal", "tool_result"}:
        return None
    if event.kind == "wake_followup":
        return 0.0 if policy.wake_followup_enabled else None
    if event.kind == "world_change":
        return policy.world_change_min_salience
    if event.kind == "embodiment_change":
        return policy.embodiment_change_min_salience
    if event.kind == "memory_recall":
        return policy.memory_recall_min_salience
    if event.kind == "prediction_error":
        return policy.prediction_error_min_salience
    return None


def evaluate_autonomous_trigger(
    *,
    event: CognitionEvent,
    clock: ClockSample,
    accounting: AutomaticCognitionAccounting,
    policy: AutonomousTriggerPolicy = DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
) -> AutonomousTriggerDecision:
    """Evaluate one event without consuming it or authorizing a model call."""
    if not isinstance(event, CognitionEvent):
        raise TypeError("event must be CognitionEvent")
    if not isinstance(clock, ClockSample):
        raise TypeError("clock must be ClockSample")
    if not isinstance(accounting, AutomaticCognitionAccounting):
        raise TypeError("accounting must be AutomaticCognitionAccounting")
    if not isinstance(policy, AutonomousTriggerPolicy):
        raise TypeError("policy must be AutonomousTriggerPolicy")

    policy_reference = autonomous_trigger_policy_ref(policy)
    now = clock.monotonic_ms

    if accounting.runtime_epoch_id != clock.runtime_epoch_id:
        decision = "DENY"
        reason = "runtime_epoch_changed"
        effective_start = now
        effective_steps = 0
        not_before = None
    else:
        if now < accounting.window_started_monotonic_ms:
            raise AutonomousTriggerPolicyError(
                "trusted monotonic clock predates accounting window"
            )
        if (
            accounting.last_automatic_step_monotonic_ms is not None
            and now < accounting.last_automatic_step_monotonic_ms
        ):
            raise AutonomousTriggerPolicyError(
                "trusted monotonic clock predates last automatic step"
            )

        elapsed = now - accounting.window_started_monotonic_ms
        if elapsed >= policy.window_ms:
            # Budget accounting rolls over, but cooldown is independent of the
            # budget window. A step just before rollover must still suppress an
            # immediate second automatic step just after the boundary.
            effective_start = now
            effective_steps = 0
            effective_last = accounting.last_automatic_step_monotonic_ms
        else:
            effective_start = accounting.window_started_monotonic_ms
            effective_steps = accounting.automatic_steps_in_window
            effective_last = accounting.last_automatic_step_monotonic_ms

        threshold = _eligibility_threshold(event, policy)
        if threshold is None:
            decision = "DENY"
            reason = "event_kind_denied"
            not_before = None
        elif event.salience < threshold:
            decision = "DENY"
            reason = "salience_below_threshold"
            not_before = None
        else:
            defer_until = now
            defer_reason: TriggerReason | None = None
            if effective_steps >= policy.max_steps_per_window:
                defer_until = max(
                    defer_until,
                    effective_start + policy.window_ms,
                )
                defer_reason = "window_budget_exhausted"
            if effective_last is not None:
                cooldown_until = effective_last + policy.cooldown_ms
                if cooldown_until > now:
                    if cooldown_until >= defer_until:
                        defer_reason = "cooldown_active"
                    defer_until = max(defer_until, cooldown_until)

            if defer_until > now:
                decision = "DEFER"
                reason = defer_reason or "cooldown_active"
                not_before = defer_until
            else:
                decision = "ELIGIBLE"
                reason = "eligible"
                not_before = None

    budget_remaining = max(
        0,
        policy.max_steps_per_window - effective_steps,
    )
    seed = {
        "event_id": event.event_id,
        "clock_sample_id": clock.sample_id,
        "decision": decision,
        "reason": reason,
        "not_before_monotonic_ms": not_before,
        "effective_window_started_monotonic_ms": effective_start,
        "effective_steps_in_window": effective_steps,
        "policy_ref": policy_reference,
    }
    return AutonomousTriggerDecision(
        schema="kaliv-consciousness-core/autonomous-trigger-decision/v1",
        decision_id=_decision_id(seed),
        event_id=event.event_id,
        event_kind=event.kind,
        event_salience=event.salience,
        clock_sample_id=clock.sample_id,
        runtime_epoch_id=clock.runtime_epoch_id,
        decision=decision,
        reason=reason,
        not_before_monotonic_ms=not_before,
        effective_window_started_monotonic_ms=effective_start,
        effective_steps_in_window=effective_steps,
        budget_remaining=budget_remaining,
        policy_ref=policy_reference,
        event_consumed=False,
        model_calls=0,
        scheduling_authority=False,
        execution_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )


def record_automatic_cognition(
    *,
    decision: AutonomousTriggerDecision,
    clock: ClockSample,
    policy: AutonomousTriggerPolicy = DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
) -> AutomaticCognitionRecordReceipt:
    """Record one step only after a caller has separately completed it.

    This does not run, authorize or prove the step itself. The caller must only
    invoke this function after the existing exact-event step boundary succeeded.
    """
    if not isinstance(decision, AutonomousTriggerDecision):
        raise TypeError("decision must be AutonomousTriggerDecision")
    if not isinstance(clock, ClockSample):
        raise TypeError("clock must be ClockSample")
    if not isinstance(policy, AutonomousTriggerPolicy):
        raise TypeError("policy must be AutonomousTriggerPolicy")
    if decision.decision != "ELIGIBLE" or decision.reason != "eligible":
        raise AutonomousTriggerPolicyError(
            "only an ELIGIBLE decision may be recorded"
        )
    if decision.clock_sample_id != clock.sample_id:
        raise AutonomousTriggerPolicyError(
            "automatic cognition record must use the evaluated ClockSample"
        )
    if decision.runtime_epoch_id != clock.runtime_epoch_id:
        raise AutonomousTriggerPolicyError(
            "automatic cognition record runtime epoch mismatch"
        )
    if decision.policy_ref != autonomous_trigger_policy_ref(policy):
        raise AutonomousTriggerPolicyError(
            "automatic cognition record policy binding mismatch"
        )
    if decision.effective_steps_in_window >= policy.max_steps_per_window:
        raise AutonomousTriggerPolicyError(
            "automatic cognition budget already exhausted"
        )

    next_steps = decision.effective_steps_in_window + 1
    accounting = AutomaticCognitionAccounting(
        schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
        runtime_epoch_id=clock.runtime_epoch_id,
        window_started_monotonic_ms=(
            decision.effective_window_started_monotonic_ms
        ),
        automatic_steps_in_window=next_steps,
        last_automatic_step_monotonic_ms=clock.monotonic_ms,
        production_activation=False,
    )
    return AutomaticCognitionRecordReceipt(
        schema="kaliv-consciousness-core/automatic-cognition-record/v1",
        decision_id=decision.decision_id,
        event_id=decision.event_id,
        clock_sample_id=clock.sample_id,
        previous_steps_in_window=decision.effective_steps_in_window,
        next_steps_in_window=next_steps,
        accounting=accounting,
        model_calls_authorized_here=0,
        scheduling_authority=False,
        execution_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )
