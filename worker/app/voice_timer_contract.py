"""Pure, fail-closed authorization contract for future spoken timer creation.

This module deliberately does not create alarms, schedules or notifications.
The actual executor must prove authorization AND durable persistence before
a caller may announce success. Keeping this contract pure permits CI tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TimerProposal:
    duration_seconds: int
    spoken_request: str

    def __post_init__(self) -> None:
        if not 1 <= self.duration_seconds <= 3600:
            raise ValueError("timer duration must be between 1 and 3600 seconds")
        if not self.spoken_request.strip():
            raise ValueError("spoken request must be nonempty")


@dataclass(frozen=True)
class TimerExecutionReceipt:
    authorized: bool
    persisted: bool
    delivery_confirmed: bool
    timer_id: str | None = None


def authorized_timer_acknowledgement(receipt: TimerExecutionReceipt | None) -> str:
    """Fail closed until a trusted executor can verify persisted delivery.

    Dataclass fields are caller-supplied claims, not an authenticated receipt.
    Do not turn them into a user-facing success message. A future integration
    must verify the real scheduler result through its own trusted boundary.
    """
    return "Timeren er ikke startet. Jeg kunne ikke bekræfte godkendelse og levering."


def propose_timer(text: str) -> TimerProposal | None:
    from .voice_timer_intent import parse_timer_request

    seconds = parse_timer_request(text)
    if seconds is None:
        return None
    return TimerProposal(seconds, text.strip())
