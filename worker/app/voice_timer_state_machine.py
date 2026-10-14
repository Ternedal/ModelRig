"""Pure one-shot timer transitions; never grants permission or delivers alarms.

The authenticated operator and durable alarm transport are external boundaries.
This module is deliberately inert and has no wall-clock sleeps or side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TimerState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DUE = "due"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class TimerTransition:
    state: TimerState
    due_at: float | None = None


def activate(
    state: TimerState, *, authorized: bool, persisted: bool,
    delivery_channel_ready: bool, confirmed_at: float, duration_seconds: int
) -> TimerTransition:
    """Compute possible activation; caller must persist transactionally first."""
    if state != TimerState.PENDING:
        raise ValueError("only pending timers can be activated")
    if not (authorized and persisted and delivery_channel_ready):
        raise PermissionError("authorization, persistence and delivery readiness required")
    if type(duration_seconds) is not int or not 1 <= duration_seconds <= 3600:
        raise ValueError("duration must be 1..3600 seconds")
    return TimerTransition(TimerState.ACTIVE, confirmed_at + duration_seconds)


def mark_due(state: TimerState, *, due_at: float, now: float) -> TimerTransition:
    if state != TimerState.ACTIVE or now < due_at:
        raise ValueError("timer is not yet due")
    return TimerTransition(TimerState.DUE, due_at)


def delivered(state: TimerState, *, transport_acknowledged: bool) -> TimerTransition:
    if state != TimerState.DUE or not transport_acknowledged:
        raise ValueError("alarm transport has not acknowledged delivery")
    return TimerTransition(TimerState.DELIVERED)


def cancel(state: TimerState) -> TimerTransition:
    if state not in (TimerState.PENDING, TimerState.ACTIVE, TimerState.DUE):
        raise ValueError("timer is terminal")
    return TimerTransition(TimerState.CANCELLED)
