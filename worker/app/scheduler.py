"""Scheduled tasks, built on the JobStore (dormant behind KALIV_SCHEDULER).

The benchmark's cheapest category by far -- and the hard parts were paid for
already: the JobStore knows terminal truth, cancellation and restart honesty,
so this file is the two things it does not know: WHEN to run, and WHETHER it is
allowed to at all.

The second one is the real design problem, and it is not cron. The tool gate's
promise is "Anders approves anything that writes". At 03:00 there is nobody to
approve. Three answers were possible:

  * refuse every write -- honest, and turns the feature into an alarm clock
  * park writes for confirmation -- honest, and they expire before morning, so
    the schedule silently does nothing forever
  * approve ONCE, at schedule time, with the arguments frozen

The third is the only one that keeps the promise and does something. Anders
approving "append this exact text every morning" IS Anders approving the write;
what he did not approve is a DIFFERENT write appearing under that approval. So
the approval is bound to a fingerprint of (tool, args): change an argument and
the approval dies with it. That is the gate's immutable-argument invariant,
extended along the time axis.

Two rules follow from the same place and are absolute:
  * `desktop` actions can never be scheduled. A click at 03:00 lands in
    whatever window happens to be there, and screenshot binding cannot save it:
    the screen it was planned against no longer exists.
  * schedules are created by Anders, never by a model. There is no
    model-visible tool here, on purpose -- a model that can create schedules
    can launder a write past its own confirmation card by asking for it later.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

# "every:900" -> every 900 seconds. "daily:03:00" -> at 03:00 local time.
_EVERY = re.compile(r"^every:(\d+)$")
_DAILY = re.compile(r"^daily:([01]\d|2[0-3]):([0-5]\d)$")

MIN_INTERVAL_S = 60


class ScheduleError(ValueError):
    """A schedule that cannot be honoured. Never silently downgraded."""


def enabled() -> bool:
    """Dormant by default. Nothing ticks until Anders says so."""
    return os.getenv("KALIV_SCHEDULER", "").strip().lower() in ("1", "true", "on")


def fingerprint(tool: str, args: dict) -> str:
    """What exactly was approved. Sort keys so argument order cannot change it."""
    blob = json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Cadence:
    kind: str          # "every" | "daily"
    seconds: int = 0   # for "every"
    hour: int = 0      # for "daily"
    minute: int = 0


def parse_cadence(spec: str) -> Cadence:
    m = _EVERY.match(spec or "")
    if m:
        secs = int(m.group(1))
        if secs < MIN_INTERVAL_S:
            # Not a safety rail so much as an honesty one: a 5-second schedule
            # is a busy loop wearing a calendar's clothes.
            raise ScheduleError(
                f"interval {secs}s er under minimum {MIN_INTERVAL_S}s"
            )
        return Cadence("every", seconds=secs)
    m = _DAILY.match(spec or "")
    if m:
        return Cadence("daily", hour=int(m.group(1)), minute=int(m.group(2)))
    raise ScheduleError(
        f"ukendt kadence {spec!r} — brug 'every:<sekunder>' eller 'daily:HH:MM'"
    )


def next_run(cadence: Cadence, after: float) -> float:
    """The next moment this should fire, strictly after `after`."""
    if cadence.kind == "every":
        return after + cadence.seconds
    lt = time.localtime(after)
    candidate = time.mktime((
        lt.tm_year, lt.tm_mon, lt.tm_mday,
        cadence.hour, cadence.minute, 0, 0, 0, -1,
    ))
    if candidate <= after:
        candidate = time.mktime((
            lt.tm_year, lt.tm_mon, lt.tm_mday + 1,
            cadence.hour, cadence.minute, 0, 0, 0, -1,
        ))
    return candidate


def catch_up(cadence: Cadence, due_at: float, now: float) -> tuple[int, float]:
    """How many runs were MISSED while the rig was off, and when to fire next.

    Returns (missed, next_due). The count is reported, never executed: a rig
    that was off for a week must not wake up and run seven days of work at
    once, and it must not pretend nothing was skipped either. The JobStore
    learned the same lesson the hard way -- an interrupted job says
    "interrupted", it does not quietly claim success.
    """
    if now < due_at:
        return 0, due_at
    missed = 0
    due = due_at
    while due <= now:
        due = next_run(cadence, due)
        missed += 1
    # The one we are firing now is not a miss.
    return max(0, missed - 1), due


def refusal(tool_risk: str, approved_fingerprint: str | None,
            current_fingerprint: str) -> str | None:
    """Why this scheduled task must not run, or None.

    Pure: the policy is a fact about (risk, approval, arguments), not about
    whatever the caller happens to have in scope at 03:00.
    """
    if tool_risk == "desktop":
        return (
            "skrivebordshandlinger kan ikke planlægges: et klik kl. 03:00 lander "
            "i det vindue der tilfældigvis er der, og screenshot-bindingen kan "
            "ikke redde det — skærmen det blev planlagt mod findes ikke længere"
        )
    if tool_risk == "read":
        return None
    if not approved_fingerprint:
        return (
            "planlagte skrivninger kræver at du godkendte dem da du oprettede "
            "planen — der er ingen at spørge kl. 03:00"
        )
    if approved_fingerprint != current_fingerprint:
        return (
            "argumenterne er ændret siden du godkendte planen; godkendelsen "
            "gjaldt den handling, ikke denne"
        )
    return None
