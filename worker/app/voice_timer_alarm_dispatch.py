"""One bounded, opt-in delivery iteration; never starts a background worker.

A transport implementation is supplied explicitly. The return value only
represents an internal transport acceptance, NOT a device alarm receipt.
Client-side durable acknowledgement remains a separate release gate.\nA transport ACK never marks a timer delivered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .voice_timer_alarm_outbox import AlarmClaim, TimerAlarmOutbox


class AlarmTransport(Protocol):
    def send(self, claim: AlarmClaim) -> bool:
        """Return True only on explicit transport acceptance."""


@dataclass(frozen=True)
class AlarmDispatchResult:
    timer_id: str | None
    outcome: str


def dispatch_once(
    outbox: TimerAlarmOutbox,
    transport: AlarmTransport,
    *,
    now: float | None = None,
    lease_seconds: int = 30,
) -> AlarmDispatchResult:
    """Attempt at most one delivery, without auto-starting timers or loops.

    Failed delivery leaves the durable lease for expiry/retry. An exception
    never becomes a successful timer receipt. Callers must not present this
    return value as confirmation of an audible alarm.
    """
    claim = outbox.claim_next(now=now, lease_seconds=lease_seconds)
    if claim is None:
        return AlarmDispatchResult(None, "idle")
    try:
        accepted = transport.send(claim)
    except Exception:
        return AlarmDispatchResult(claim.timer_id, "transport_error")
    if accepted is not True:
        return AlarmDispatchResult(claim.timer_id, "not_accepted")
    # Transport acceptance is NOT proof of client presentation.
    # Leave the claim leased until a separate trusted client-receipt boundary
    # acknowledges it. Without such a boundary it expires and can be retried.
    return AlarmDispatchResult(claim.timer_id, "transport_accepted_pending_receipt")
