"""Small explicit ModelRig BodyCue policy, default off.

This module emits only canonical BodyCue v1 semantic objects. It never emits
renderer plans, joint/bone transforms or engine animation identifiers. The
BodyRig boundary validates the cue again before translating semantics into the
selected body's runtime plan.

No sentiment is inferred from words or punctuation. `KALIV_BODY_CUES=1` enables
only the documented small policy.
"""
from __future__ import annotations

import os

from bodyrig.body_cue import build_body_cue

CUES_ENV = "KALIV_BODY_CUES"
EXPLAIN_MIN_CHARS = 60


def enabled() -> bool:
    return os.environ.get(CUES_ENV, "").strip() == "1"


def cue_for_state(*, state: str, utterance_id: str | None, body_id: str) -> dict | None:
    """Return a BodyCue v1 for a state only when a real utterance authority exists.

    State transitions themselves do not need a BodyCue. Optional emotion/energy
    embellishment does, and the public contract requires utterance_id. We never
    fabricate one merely to keep a face policy running.
    """
    if not enabled() or not utterance_id:
        return None
    if state == "thinking":
        return build_body_cue(
            utterance_id=utterance_id,
            body_id=body_id,
            emotion="curious",
            intensity=0.3,
            energy=0.4,
        )
    if state == "error":
        return build_body_cue(
            utterance_id=utterance_id,
            body_id=body_id,
            emotion="concerned",
            intensity=0.5,
            energy=0.3,
        )
    if state in ("idle", "listening", "interrupted"):
        return build_body_cue(
            utterance_id=utterance_id,
            body_id=body_id,
            emotion="neutral",
            intensity=0.0,
            energy=0.3,
            gaze="neutral",
        )
    return None


def cue_for_speech(*, sentence: str, utterance_id: str, body_id: str, duration_ms: int) -> dict | None:
    """Canonical BodyCue v1 paired with the exact VoiceRig utterance id."""
    if not enabled():
        return None
    text = (sentence or "").strip()
    long_explanation = len(text) >= EXPLAIN_MIN_CHARS
    return build_body_cue(
        utterance_id=utterance_id,
        body_id=body_id,
        emotion="neutral",
        intensity=0.6 if long_explanation else 0.0,
        energy=0.5,
        gesture="explain" if long_explanation else None,
        gaze="neutral",
        duration_ms=duration_ms,
    )
