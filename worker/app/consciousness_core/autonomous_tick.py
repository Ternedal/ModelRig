"""C25-B caller-driven one-tick autonomous cognition adapter.

No thread, timer, scheduler, polling loop or retry lives here. A trusted owner
must explicitly await tick_once(). The adapter may request at most one existing
exact-event session step per call and only after C25-A marks every currently
pending event ELIGIBLE, preventing denied events from hitchhiking in the
supervisor's multi-event RUN selection.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .autonomous_trigger_policy import (
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
    AutomaticCognitionAccounting,
    AutonomousTriggerDecision,
    AutonomousTriggerPolicy,
    evaluate_autonomous_trigger,
    new_automatic_cognition_accounting,
    record_automatic_cognition,
)
from .profile_source import CognitiveProfileLoadResult, load_cognitive_profile
from .session_lifecycle import ProductionCognitiveSession
from .temporal import ClockSample


AUTONOMOUS_COGNITION_FLAG = "KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED"

TickOutcome = Literal["DISABLED", "IDLE", "DEFER", "WAIT", "RUN"]
TickReason = Literal[
    "disabled",
    "session_closed",
    "no_pending_events",
    "pending_event_denied",
    "pending_event_deferred",
    "profile_unavailable",
    "supervisor_wait",
    "run_completed",
]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class AutonomousCognitionTickError(RuntimeError):
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
    clock_sample_id: Annotated[str, Field(pattern=r"^clock-[a-f0-9]{32}$")] | None
    evaluated_event_ids: Annotated[
        list[Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]],
        Field(max_length=64),
    ]
    selected_event_id: Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")] | None
    trigger_decision_id: Annotated[
        str,
        Field(pattern=r"^autodec-[a-f0-9]{32}$"),
    ] | None
    not_before_monotonic_ms: NonNegativeInt | None
    cognitive_profile_ref: NonEmptyRef | None
    supervisor_decision: Literal["RUN", "WAIT", "IDLE"] | None
    supervisor_selected_event_ids: Annotated[
        list[Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]],
        Field(max_length=16),
    ]
    thought_engine_calls: Literal[0, 1]
    accounting_steps_before: NonNegativeInt
    accounting_steps_after: NonNegativeInt
    accounting_updated: bool
    automatic_repeat: Literal[False]
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def autonomous_cognition_enabled() -> bool:
    return os.getenv("KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED", "0") == "1"


class AutonomousCognitionTickAdapter:
    """Evaluate and possibly run at most one exact-event cognitive step."""

    def __init__(
        self,
        *,
        session: ProductionCognitiveSession,
        clock_sample_fn: Callable[[], ClockSample],
        profile_loader: Callable[[], CognitiveProfileLoadResult | None] = load_cognitive_profile,
        policy: AutonomousTriggerPolicy = DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
        accounting: AutomaticCognitionAccounting | None = None,
        enabled_fn: Callable[[], bool] = autonomous_cognition_enabled,
    ) -> None:
        if not isinstance(session, ProductionCognitiveSession):
            raise TypeError("session must be ProductionCognitiveSession")
        if not callable(clock_sample_fn):
            raise TypeError("clock_sample_fn must be callable")
        if not callable(profile_loader):
            raise TypeError("profile_loader must be callable")
        if not isinstance(policy, AutonomousTriggerPolicy):
            raise TypeError("policy must be AutonomousTriggerPolicy")
        if accounting is not None and not isinstance(
            accounting,
            AutomaticCognitionAccounting,
        ):
            raise TypeError("accounting must be AutomaticCognitionAccounting or None")
        if not callable(enabled_fn):
            raise TypeError("enabled_fn must be callable")

        self._session = session
        self._clock_sample_fn = clock_sample_fn
        self._profile_loader = profile_loader
        self._policy = policy
        self._accounting = accounting
        self._enabled_fn = enabled_fn

    @property
    def accounting(self) -> AutomaticCognitionAccounting | None:
        return self._accounting

    @property
    def policy(self) -> AutonomousTriggerPolicy:
        return self._policy

    def _receipt(
        self,
        *,
        outcome: TickOutcome,
        reason: TickReason,
        clock: ClockSample | None = None,
        evaluated_event_ids: list[str] | None = None,
        selected_event_id: str | None = None,
        trigger_decision_id: str | None = None,
        not_before_monotonic_ms: int | None = None,
        cognitive_profile_ref: str | None = None,
        supervisor_decision: Literal["RUN", "WAIT", "IDLE"] | None = None,
        supervisor_selected_event_ids: list[str] | None = None,
        thought_engine_calls: Literal[0, 1] = 0,
        accounting_before: int | None = None,
        accounting_after: int | None = None,
        accounting_updated: bool = False,
    ) -> AutonomousCognitionTickReceipt:
        current = self._accounting
        before = (
            accounting_before
            if accounting_before is not None
            else (current.automatic_steps_in_window if current is not None else 0)
        )
        after = (
            accounting_after
            if accounting_after is not None
            else (current.automatic_steps_in_window if current is not None else 0)
        )
        return AutonomousCognitionTickReceipt(
            schema="kaliv-consciousness-core/autonomous-cognition-tick/v1",
            outcome=outcome,
            reason=reason,
            clock_sample_id=clock.sample_id if clock is not None else None,
            evaluated_event_ids=evaluated_event_ids or [],
            selected_event_id=selected_event_id,
            trigger_decision_id=trigger_decision_id,
            not_before_monotonic_ms=not_before_monotonic_ms,
            cognitive_profile_ref=cognitive_profile_ref,
            supervisor_decision=supervisor_decision,
            supervisor_selected_event_ids=supervisor_selected_event_ids or [],
            thought_engine_calls=thought_engine_calls,
            accounting_steps_before=before,
            accounting_steps_after=after,
            accounting_updated=accounting_updated,
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
        """Run zero or one cognitive cycle; never loops or retries."""
        if not bool(self._enabled_fn()):
            return self._receipt(
                outcome="DISABLED",
                reason="disabled",
            )
        if self._session.closed:
            return self._receipt(
                outcome="IDLE",
                reason="session_closed",
            )

        try:
            clock = self._clock_sample_fn()
        except Exception as exc:
            raise AutonomousCognitionTickError(
                "trusted autonomous cognition clock unavailable"
            ) from exc
        if not isinstance(clock, ClockSample):
            raise AutonomousCognitionTickError(
                "trusted autonomous cognition clock returned invalid sample"
            )

        if self._accounting is None:
            self._accounting = new_automatic_cognition_accounting(clock)

        pending = list(self._session.supervisor_state.pending_events)
        if not pending:
            return self._receipt(
                outcome="IDLE",
                reason="no_pending_events",
                clock=clock,
            )

        decisions: dict[str, AutonomousTriggerDecision] = {}
        for event in pending:
            decision = evaluate_autonomous_trigger(
                event=event,
                clock=clock,
                accounting=self._accounting,
                policy=self._policy,
            )
            decisions[event.event_id] = decision

        evaluated_ids = [event.event_id for event in pending]

        # Anti-hitchhike boundary: C18 may select multiple pending events in one
        # RUN. C25-B only proceeds when every event it could include is already
        # permitted by C25-A on this same trusted clock/accounting snapshot.
        denied = [
            decision
            for decision in decisions.values()
            if decision.decision == "DENY"
        ]
        if denied:
            return self._receipt(
                outcome="IDLE",
                reason="pending_event_denied",
                clock=clock,
                evaluated_event_ids=evaluated_ids,
            )

        deferred = [
            decision
            for decision in decisions.values()
            if decision.decision == "DEFER"
        ]
        if deferred:
            not_before = max(
                decision.not_before_monotonic_ms or clock.monotonic_ms
                for decision in deferred
            )
            return self._receipt(
                outcome="DEFER",
                reason="pending_event_deferred",
                clock=clock,
                evaluated_event_ids=evaluated_ids,
                not_before_monotonic_ms=not_before,
            )

        eligible_events = sorted(
            pending,
            key=lambda event: (
                -event.salience,
                event.observed_sequence,
                event.event_id,
            ),
        )
        selected = eligible_events[0]
        selected_decision = decisions[selected.event_id]

        try:
            loaded = self._profile_loader()
        except Exception as exc:
            raise AutonomousCognitionTickError(
                "autonomous cognition profile unavailable"
            ) from exc
        if loaded is None:
            return self._receipt(
                outcome="IDLE",
                reason="profile_unavailable",
                clock=clock,
                evaluated_event_ids=evaluated_ids,
                selected_event_id=selected.event_id,
                trigger_decision_id=selected_decision.decision_id,
            )
        if not isinstance(loaded, CognitiveProfileLoadResult):
            raise AutonomousCognitionTickError(
                "autonomous cognition profile loader returned invalid result"
            )

        before_steps = self._accounting.automatic_steps_in_window
        try:
            step = await self._session.step(
                profile=loaded.profile,
                required_event_id=selected.event_id,
            )
        except Exception as exc:
            raise AutonomousCognitionTickError(
                "autonomous exact-event cognitive step failed"
            ) from exc

        plan = step.supervisor_step.plan
        if plan.decision == "WAIT":
            return self._receipt(
                outcome="WAIT",
                reason="supervisor_wait",
                clock=clock,
                evaluated_event_ids=evaluated_ids,
                selected_event_id=selected.event_id,
                trigger_decision_id=selected_decision.decision_id,
                cognitive_profile_ref=loaded.receipt.profile_ref,
                supervisor_decision="WAIT",
                supervisor_selected_event_ids=[],
                thought_engine_calls=0,
                accounting_before=before_steps,
                accounting_after=before_steps,
                accounting_updated=False,
            )
        if plan.decision != "RUN" or not step.supervisor_step.thought_engine_invoked:
            raise AutonomousCognitionTickError(
                "eligible exact-event step returned unexpected supervisor decision"
            )
        if selected.event_id not in plan.selected_event_ids:
            raise AutonomousCognitionTickError(
                "autonomous exact-event step lost required event binding"
            )

        # Every pending event was ELIGIBLE above. Therefore every event selected
        # by the canonical multi-event supervisor plan is also policy-authorized.
        for event_id in plan.selected_event_ids:
            decision = decisions.get(event_id)
            if decision is None or decision.decision != "ELIGIBLE":
                raise AutonomousCognitionTickError(
                    "supervisor selected event outside autonomous policy snapshot"
                )

        record = record_automatic_cognition(
            decision=selected_decision,
            clock=clock,
            policy=self._policy,
        )
        self._accounting = record.accounting
        return self._receipt(
            outcome="RUN",
            reason="run_completed",
            clock=clock,
            evaluated_event_ids=evaluated_ids,
            selected_event_id=selected.event_id,
            trigger_decision_id=selected_decision.decision_id,
            cognitive_profile_ref=loaded.receipt.profile_ref,
            supervisor_decision="RUN",
            supervisor_selected_event_ids=plan.selected_event_ids,
            thought_engine_calls=1,
            accounting_before=before_steps,
            accounting_after=self._accounting.automatic_steps_in_window,
            accounting_updated=True,
        )
