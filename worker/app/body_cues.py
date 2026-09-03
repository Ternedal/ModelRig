"""Body cues from the turn -- the small, explicit policy, default off.

BodyCue is ModelRig's job: meaning, not bones. This module decides only
what the renderer already understands and what a turn plainly shows:

* a long spoken sentence gets the `explain` gesture (the renderer's
  procedural explain runs only while speaking, so it cannot leak);
* thinking is `curious`, low intensity -- a face that is working, not
  blank;
* an error turn is `concerned`.

Nothing is inferred from the words themselves: no sentiment guesswork,
no emotion from punctuation. That would be manufacturing feelings the
speaker never had. Off by default (KALIV_BODY_CUES=1 enables) so the
neutral baseline stays until an operator has seen the body move and
wants more.
"""

from __future__ import annotations

import os
from typing import Any

CUES_ENV = "KALIV_BODY_CUES"
EXPLAIN_MIN_CHARS = 60


def enabled() -> bool:
    return os.environ.get(CUES_ENV, "").strip() == "1"


def plan_for_state(state: str) -> dict[str, Any] | None:
    """An expression plan for a state transition, or None to leave the
    runtime's current expression alone."""
    if not enabled():
        return None
    if state == "thinking":
        return {"state": "thinking", "gesture": None, "gaze": None,
                "emotion": {"name": "curious", "intensity": 0.3}, "energy": 0.4}
    if state == "error":
        return {"state": "error", "gesture": None, "gaze": None,
                "emotion": {"name": "concerned", "intensity": 0.5}, "energy": 0.3}
    if state in ("idle", "listening", "interrupted"):
        return {"state": state, "gesture": None, "gaze": None, "emotion": None, "energy": 0.3}
    return None


def plan_for_speech(sentence: str) -> dict[str, Any] | None:
    """An expression plan for a sentence about to be spoken."""
    if not enabled():
        return None
    text = (sentence or "").strip()
    gesture = {"intent": "explain", "intensity": 0.6} if len(text) >= EXPLAIN_MIN_CHARS else None
    return {"state": "speaking", "gesture": gesture, "gaze": None, "emotion": None, "energy": 0.5}
