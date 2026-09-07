from __future__ import annotations

import math
import re
from typing import Any, Mapping


BODY_CUE_TYPE = "modelrig-body-cue"
BODY_CUE_VERSION = 1

_UTTERANCE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_BODY = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
_SEMANTIC = re.compile(r"^[a-z0-9_-]+$")
_OBJECT_GAZE = re.compile(r"^object:[A-Za-z0-9._:-]{1,120}$")
_ALLOWED_GAZE = {"user", "away", "neutral"}
_ALLOWED_KEYS = {
    "type",
    "version",
    "utterance_id",
    "body_id",
    "emotion",
    "intensity",
    "energy",
    "gesture",
    "gaze",
    "posture",
    "duration_ms",
}
_SEMANTIC_KEYS = {
    "body_id",
    "emotion",
    "intensity",
    "energy",
    "gesture",
    "gaze",
    "posture",
    "duration_ms",
}


class BodyCueError(ValueError):
    """A BodyCue crossed the ModelRig -> BodyRig semantic boundary incorrectly."""


def _unit(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BodyCueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise BodyCueError(f"{label} must be within 0..1")
    return result


def _semantic(value: Any, label: str, maximum: int) -> str:
    text = str(value or "")
    if not text or len(text) > maximum or _SEMANTIC.fullmatch(text) is None:
        raise BodyCueError(f"{label} is not a canonical semantic identifier")
    return text


def validate_body_cue(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strict executable BodyCue v1 validator.

    The JSON schema remains the public contract. This small executable mirror is
    the runtime trust boundary: exact field set, exact version, no engine-space
    fields, and no guessing unknown versions/values.
    """
    if not isinstance(value, Mapping):
        raise BodyCueError("BodyCue must be an object")
    keys = set(value)
    unknown = keys - _ALLOWED_KEYS
    if unknown:
        raise BodyCueError(f"BodyCue contains unknown fields: {sorted(unknown)}")
    if value.get("type") != BODY_CUE_TYPE or value.get("version") != BODY_CUE_VERSION:
        raise BodyCueError("BodyCue type/version mismatch")
    utterance_id = str(value.get("utterance_id") or "")
    if _UTTERANCE.fullmatch(utterance_id) is None:
        raise BodyCueError("BodyCue utterance_id is not canonical")
    if not (keys & _SEMANTIC_KEYS):
        raise BodyCueError("BodyCue contains no semantic intent")

    result = dict(value)
    result["utterance_id"] = utterance_id
    if "body_id" in value:
        body_id = str(value["body_id"])
        if _BODY.fullmatch(body_id) is None:
            raise BodyCueError("BodyCue body_id is not canonical")
        result["body_id"] = body_id
    if "emotion" in value:
        result["emotion"] = _semantic(value["emotion"], "emotion", 64)
    if "gesture" in value:
        result["gesture"] = _semantic(value["gesture"], "gesture", 80)
    if "posture" in value:
        result["posture"] = _semantic(value["posture"], "posture", 80)
    if "intensity" in value:
        result["intensity"] = _unit(value["intensity"], "intensity")
    if "energy" in value:
        result["energy"] = _unit(value["energy"], "energy")
    if "duration_ms" in value:
        duration = value["duration_ms"]
        if isinstance(duration, bool) or not isinstance(duration, int) or not 0 <= duration <= 120000:
            raise BodyCueError("duration_ms must be an integer within 0..120000")
    if "gaze" in value:
        gaze = str(value["gaze"])
        if gaze not in _ALLOWED_GAZE and _OBJECT_GAZE.fullmatch(gaze) is None:
            raise BodyCueError("gaze is not a canonical BodyCue target")
        result["gaze"] = gaze
    return result


def build_body_cue(*, utterance_id: str, **semantic: Any) -> dict[str, Any]:
    cue = {
        "type": BODY_CUE_TYPE,
        "version": BODY_CUE_VERSION,
        "utterance_id": utterance_id,
        **{key: value for key, value in semantic.items() if value is not None},
    }
    return validate_body_cue(cue)


def expression_plan_from_body_cue(cue: Mapping[str, Any], *, state: str) -> dict[str, Any]:
    """Translate supported BodyCue v1 semantics into a renderer-neutral plan.

    A schema-valid semantic field that this runtime cannot realize must fail
    closed rather than being silently discarded. `duration_ms` is a timing hint
    owned by the speech/scheduler path; posture currently has no runtime mapping.
    """
    checked = validate_body_cue(cue)
    if not isinstance(state, str) or not state:
        raise BodyCueError("runtime state is required for BodyCue application")
    if "posture" in checked:
        raise BodyCueError("BodyCue posture is valid v1 but not yet supported by this runtime")

    intensity = float(checked.get("intensity", 0.5))
    gesture = None
    if "gesture" in checked:
        gesture = {"intent": checked["gesture"], "intensity": intensity}

    gaze = None
    if "gaze" in checked and checked["gaze"] != "neutral":
        gaze = {"target": checked["gaze"], "intensity": 1.0}

    emotion = None
    if "emotion" in checked and checked["emotion"] != "neutral":
        emotion = {"name": checked["emotion"], "intensity": intensity}

    plan: dict[str, Any] = {
        "state": state,
        "gesture": gesture,
        "gaze": gaze,
        "emotion": emotion,
    }
    if "energy" in checked:
        plan["energy"] = checked["energy"]
    return plan
