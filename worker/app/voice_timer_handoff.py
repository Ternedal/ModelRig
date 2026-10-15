"""Side-effect-free handoff of parsed voice timer intents to an operator UI.

This is NOT a schedule preview (which must come from ScheduleAdmin.preview)
or an approval. No model-generated string can authorize a write.
"""
from __future__ import annotations

from dataclasses import dataclass

from .voice_timer_contract import propose_timer
from .voice_timer_intent import unsupported_timer_reply


@dataclass(frozen=True)
class TimerHandoff:
    duration_seconds: int
    spoken_request: str
    requires_human_confirmation: bool = True
    scheduler_preview_verified: bool = False
    timer_started: bool = False


def prepare_timer_handoff(spoken_request: str) -> TimerHandoff | None:
    """Offer the UI only a validated duration; never create an alarm."""
    proposal = propose_timer(spoken_request)
    if proposal is None:
        return None
    return TimerHandoff(
        duration_seconds=proposal.duration_seconds,
        spoken_request=proposal.spoken_request,
    )


def timer_handoff_reply(spoken_request: str) -> str | None:
    """Voice answer remains honest regardless of potential UI handoff."""
    return unsupported_timer_reply(spoken_request)
