"""Read-only bridge to the existing human-controlled ScheduleAdmin preview.

This intentionally never calls create(), approves a grant, or guesses a
schedulable timer tool. A real registry-backed tool must be supplied by the
operator; no timer or alarm tool is assumed to exist.
"""
from __future__ import annotations

from typing import Any

from .schedule_admin import ScheduleAdmin, SchedulePreview
from .voice_timer_handoff import TimerHandoff


class TimerPreviewUnavailable(ValueError):
    """No valid scheduler-backed preview can be shown to the operator."""


def preview_timer_with_scheduler(
    handoff: TimerHandoff,
    *,
    tool: str,
    args: dict[str, Any],
    cadence: str,
    admin: ScheduleAdmin,
    ttl_days: int = 1,
    max_runs: int = 1,
) -> SchedulePreview:
    """Request canonical preview, refusing untrusted or unapproved shortcuts.

    This only previews a *configured* schedulable tool. There is currently no
    dedicated alarm tool wired here, so the caller must not infer timer support.
    """
    if not isinstance(handoff, TimerHandoff):
        raise TimerPreviewUnavailable("expected a validated timer handoff")
    if not 1 <= handoff.duration_seconds <= 3600:
        raise TimerPreviewUnavailable("timer duration is invalid")
    if not handoff.requires_human_confirmation or handoff.timer_started:
        raise TimerPreviewUnavailable("timer handoff has unsafe state")
    if not tool or not isinstance(tool, str) or not isinstance(args, dict):
        raise TimerPreviewUnavailable("operator must supply a registered tool and arguments")
    if not cadence or not isinstance(cadence, str):
        raise TimerPreviewUnavailable("operator must supply a valid cadence")
    preview = admin.preview(
        tool=tool,
        args=args,
        cadence=cadence,
        ttl_days=ttl_days,
        max_runs=max_runs,
    )
    if not preview.requires_approval:
        raise TimerPreviewUnavailable("timer action must require human approval")
    if preview.risk != "write":
        raise TimerPreviewUnavailable("timer action must be classified as write")
    return preview
