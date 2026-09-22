"""C25-B default-off one-tick autonomous cognition adapter.

Caller-driven only. No thread, timer, polling loop, retry, route or scheduler is
created here. One explicit tick may evaluate the current pending event snapshot
and request at most one existing exact-event session step.

The adapter is deliberately conservative: automatic cognition is refused unless
EVERY pending event in the evaluated snapshot is ELIGIBLE under the same C25-A
policy/accounting/clock sample. The exact eligible event-id snapshot is also
passed into C18 so an event admitted after evaluation cannot hitchhike into the
RUN before ThoughtEngine invocation.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .autonomous_trigger_policy import (
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
    AutomaticCognitionAccounting,
    AutonomousTriggerDecision,
    AutonomousTriggerPolicy,
    AutonomousTriggerPolicyError,
    evaluate_autonomous_trigger,
    new_automatic_cognition_accounting,
    record_automatic_cognition,
)
from .profile_source import CognitiveProfileLoadResult, load_cognitive_profile
from .production_lifecycle import TrustedRuntimeClock
from .session_lifecycle import ProductionCognitiveSession
from .supervisor import CognitionEvent
from .temporal import ClockSample


AUTONOMOUS_COGNITION_FLAG = "KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED"

EventId = Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
TickOutcome = Literal["DISABLED", "IDLE", "DEFER", "WAIT", "RUN"]
TickReason = Literal[
    "flag_disabled",
    "no_pending_events",
    "denied_pending_event",
    "deferred_pending_event",
    "supervisor_wait",
    "ran",
]


class AutonomousCognitionAdapterError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class AutonomousCognitionTickReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/autonomous-cognition-tick/v1"]
    outcome: TickOutcome
    reason: TickReason
    clock_sample_id: Annotated[
        str | None,
        Field(default=None, pattern=r"^clock-[a-f0-9]{32}$"),
    ]
    runtime_epoch_id: Annotated[
        str | None,
        Field(default=None, pattern=r"^epoch-[a-f0-9]{32}$"),
    ]
    pending_event_count: Annotated[int, Field(ge=0, le=64, strict=True)]
    evaluated_event_count: Annotated[int, Field(ge=0, le=64, strict=True)]
    denied_event_ids: Annotated[list[EventId], Field(max_length=64)]
    deferred_event_ids: Annotated[list[EventId], Field(max_length=64)]
    eligible_event_ids: Annotated[list[EventId], Field(max_length=64)]
    selected_event_id: EventId | None
    supervisor_selected_event_ids: Annotated[list[EventId], Field(max_length=16)]
    not_before_monotonic_ms: Annotated[int | None, Field(ge=0, strict=True)]
    cognitive_profile_ref: NonEmptyRef | None
    model_calls: Literal[0, 1]
    accounting_steps_before: Annotated[int, Field(ge=0, le=64, strict=True)]
    accounting_steps_after: Annotated[int, Field(ge=0, le=64, strict=True)]
    accounting_recorded: bool
    automatic_repeat: Literal[False]
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_outcome_shape(self) -> "AutonomousCognitionTickReceipt":
        if self.outcome == "DISABLED":
            if self.clock_sample_id is not None or self.runtime_epoch_id is not None:
                raise ValueError("DISABLED tick cannot sample the trusted clock")
            if self.pending_event_count or self.evaluated_event_count:
                raise ValueError("DISABLED tick cannot inspect pending events")
        if self.outcome in {"DISABLED", "IDLE", "DEFER", "WAIT"}:
            if self.model_calls != 0 or self.accounting_recorded:
                raise ValueError("non-RUN tick cannot record a model call/budget")
            if self.accounting_steps_after != self.accounting_steps_before:
                raise ValueError("non-RUN tick cannot change accounting")
        if self.outcome == "RUN":
            if self.model_calls != 1 or not self.accounting_recorded:
                raise ValueError("RUN tick must record exactly one model call")
            if self.accounting_steps_after != self.accounting_steps_before + 1:
                raise ValueError("RUN tick must increment accounting exactly once")
            if self.selected_event_id is None:
                raise ValueError("RUN tick requires one selected event")
            if self.selected_event_id not in self.supervisor_selected_event_ids:
                raise ValueError("RUN tick did not execute its selected exact event")
        if self.outcome == "WAIT":
            if self.selected_event_id is None:
                raise ValueError("WAIT tick requires one selected eligible event")
            if self.supervisor_selected_event_ids:
                raise ValueError("WAIT tick cannot report selected supervisor events")
        if self.outcome == "DEFER" and self.not_before_monotonic_ms is None:
            raise ValueError("DEFER tick requires a not-before timestamp")
        return self


ProfileLoader = Callable[[], CognitiveProfileLoadResult | None]


def autonomous_cognition_enabled() -> bool:
    """Only exact string 1 enables caller-driven automatic cognition."""
    return os.getenv("KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED", "0") == "1"


def _ordered(events: list[CognitionEvent]) -> list[CognitionEvent]:
    """Match C18 canonical event ordering exactly."""
    return sorted(
        events,
        key=lambda item: (-item.salience, item.observed_sequence, item.event_id),
    )


class AutonomousCognitionTickAdapter:
    """Evaluate one pending snapshot and request at most one exact-event step."""

    def __init__(
        self,
        *,
        session: ProductionCognitiveSession,
        clock: TrustedRuntimeClock,
        profile_loader: ProfileLoader = load_cognitive_profile,
        policy: AutonomousTriggerPolicy = DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
        accounting: AutomaticCognitionAccounting | None = None,
    ) -> None:
        if not isinstance(session, ProductionCognitiveSession):
            raise TypeError("session must be ProductionCognitiveSession")
        if not isinstance(clock, TrustedRuntimeClock):
            raise TypeError("clock must be TrustedRuntimeClock")
        if not callable(profile_loader):
            raise TypeError("profile_loader must be callable")
        if not isinstance(policy, AutonomousTriggerPolicy):
            raise TypeError("policy must be AutonomousTriggerPolicy")
        if accounting is not None and not isinstance(
            accounting,
            AutomaticCognitionAccounting,
        ):
            raise TypeError("accounting must be AutomaticCognitionAccounting or None")
        self._session = session
        self._clock = clock
        self._profile_loader = profile_loader
        self._policy = policy
        self._accounting = accounting

    @property
    def accounting(self) -> AutomaticCognitionAccounting | None:
        return self._accounting

    def _receipt(
        self,
        *,
        outcome: TickOutcome,
        reason: TickReason,
        clock: ClockSample | None,
        pending_count: int,
        decisions: list[AutonomousTriggerDecision],
        selected_event_id: str | None = None,
        supervisor_selected_event_ids: list[str] | None = None,
        not_before_monotonic_ms: int | None = None,
        cognitive_profile_ref: str | None = None,
        model_calls: Literal[0, 1] = 0,
        accounting_before: int = 0,
        accounting_after: int | None = None,
        accounting_recorded: bool = False,
    ) -> AutonomousCognitionTickReceipt:
        denied = [
            item.event_id for item in decisions if item.decision == "DENY"
        ]
        deferred = [
            item.event_id for item in decisions if item.decision == "DEFER"
        ]
        eligible = [
            item.event_id for item in decisions if item.decision == "ELIGIBLE"
        ]
        return AutonomousCognitionTickReceipt(
            schema="kaliv-consciousness-core/autonomous-cognition-tick/v1",
            outcome=outcome,
            reason=reason,
            clock_sample_id=None if clock is None else clock.sample_id,
            runtime_epoch_id=None if clock is None else clock.runtime_epoch_id,
            pending_event_count=pending_count,
            evaluated_event_count=len(decisions),
            denied_event_ids=denied,
            deferred_event_ids=deferred,
            eligible_event_ids=eligible,
            selected_event_id=selected_event_id,
            supervisor_selected_event_ids=supervisor_selected_event_ids or [],
            not_before_monotonic_ms=not_before_monotonic_ms,
            cognitive_profile_ref=cognitive_profile_ref,
            model_calls=model_calls,
            accounting_steps_before=accounting_before,
            accounting_steps_after=(
                accounting_before if accounting_after is None else accounting_after
            ),
            accounting_recorded=accounting_recorded,
            automatic_repeat=False,
            internal_thread_created=False,
            internal_timer_created=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    async def tick_once(self) -> AutonomousCognitionTickReceipt:
        """Run at most one existing exact-event session step.

        Flag-off is intentionally first: it samples no clock, inspects no session,
        loads no profile and cannot invoke a model.
        """
        if not autonomous_cognition_enabled():
            before = (
                0
                if self._accounting is None
                else self._accounting.automatic_steps_in_window
            )
            return self._receipt(
                outcome="DISABLED",
                reason="flag_disabled",
                clock=None,
                pending_count=0,
                decisions=[],
                accounting_before=before,
            )

        clock = self._clock.sample()
        if self._accounting is None:
            self._accounting = new_automatic_cognition_accounting(clock)
        accounting = self._accounting

        if accounting.runtime_epoch_id != clock.runtime_epoch_id:
            raise AutonomousCognitionAdapterError(
                "autonomous accounting runtime epoch no longer matches trusted clock"
            )

        pending = list(self._session.supervisor_state.pending_events)
        before_steps = accounting.automatic_steps_in_window
        if not pending:
            return self._receipt(
                outcome="IDLE",
                reason="no_pending_events",
                clock=clock,
                pending_count=0,
                decisions=[],
                accounting_before=before_steps,
            )

        decisions = [
            evaluate_autonomous_trigger(
                event=event,
                clock=clock,
                accounting=accounting,
                policy=self._policy,
            )
            for event in pending
        ]

        # DENY dominates DEFER. A denied event beside an otherwise eligible
        # event must not hitchhike into C18's multi-event canonical RUN.
        denied = [item for item in decisions if item.decision == "DENY"]
        if denied:
            return self._receipt(
                outcome="IDLE",
                reason="denied_pending_event",
                clock=clock,
                pending_count=len(pending),
                decisions=decisions,
                accounting_before=before_steps,
            )

        deferred = [item for item in decisions if item.decision == "DEFER"]
        if deferred:
            not_before = max(
                item.not_before_monotonic_ms or clock.monotonic_ms
                for item in deferred
            )
            return self._receipt(
                outcome="DEFER",
                reason="deferred_pending_event",
                clock=clock,
                pending_count=len(pending),
                decisions=decisions,
                not_before_monotonic_ms=not_before,
                accounting_before=before_steps,
            )

        eligible_by_id = {
            item.event_id: item
            for item in decisions
            if item.decision == "ELIGIBLE"
        }
        if len(eligible_by_id) != len(pending):
            raise AutonomousCognitionAdapterError(
                "autonomous policy produced an unexpected decision shape"
            )

        selected_event = _ordered(pending)[0]
        selected_decision = eligible_by_id[selected_event.event_id]
        allowed_event_ids = sorted(eligible_by_id)

        # Profile IO is deliberately delayed until after policy admission.
        loaded = self._profile_loader()
        if loaded is None or not isinstance(loaded, CognitiveProfileLoadResult):
            raise AutonomousCognitionAdapterError(
                "autonomous cognitive profile unavailable"
            )

        try:
            step = await self._session.step(
                profile=loaded.profile,
                required_event_id=selected_event.event_id,
                allowed_event_ids=allowed_event_ids,
            )
        except (AutonomousTriggerPolicyError, Exception):
            # Accounting is intentionally unchanged. The exception is left
            # visible to the explicit caller; C25-C owns production isolation.
            raise

        plan = step.supervisor_step.plan
        if plan.decision == "WAIT":
            return self._receipt(
                outcome="WAIT",
                reason="supervisor_wait",
                clock=clock,
                pending_count=len(pending),
                decisions=decisions,
                selected_event_id=selected_event.event_id,
                cognitive_profile_ref=loaded.receipt.profile_ref,
                accounting_before=before_steps,
            )
        if plan.decision != "RUN":
            raise AutonomousCognitionAdapterError(
                "eligible autonomous event did not produce WAIT or RUN"
            )
        if not step.context_updated or not step.supervisor_step.thought_engine_invoked:
            raise AutonomousCognitionAdapterError(
                "RUN did not produce exactly one cognitive transition"
            )

        record = record_automatic_cognition(
            decision=selected_decision,
            clock=clock,
            policy=self._policy,
        )
        self._accounting = record.accounting
        return self._receipt(
            outcome="RUN",
            reason="ran",
            clock=clock,
            pending_count=len(pending),
            decisions=decisions,
            selected_event_id=selected_event.event_id,
            supervisor_selected_event_ids=plan.selected_event_ids,
            cognitive_profile_ref=loaded.receipt.profile_ref,
            model_calls=1,
            accounting_before=before_steps,
            accounting_after=record.next_steps_in_window,
            accounting_recorded=True,
        )
