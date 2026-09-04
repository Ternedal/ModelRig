from __future__ import annotations

import math
import re
from typing import Any, Mapping

from .runtime import BodyState
from .scheduler import RenderFrame
from .voicerig_adapter import TimingMode


class RenderFrameValidationError(ValueError):
    """Raised when renderer wire data violates BodyRig v0.1."""


_TYPE = "bodyrig.render_frame"
_VERSION = "0.1"
_ID_RE = re.compile(r"^[A-Za-z0-9._:+-]{1,160}$")
_SEMANTIC_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_SOURCE_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_BODY_MOTION_SOURCES = frozenset({"generic", "profile"})
_POSTURE_SOURCES = frozenset({"generic", "profile"})
_GESTURE_SOURCES = frozenset({"none", "semantic", "explicit_profile", "profile_replay"})
_DOMINANT_SIDES = frozenset({"left", "right", "balanced"})


def _number(value: object, *, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise RenderFrameValidationError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RenderFrameValidationError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise RenderFrameValidationError(
            f"{field} must be within {minimum:g}..{maximum:g}"
        )
    return number


def _unit(value: object, *, field: str) -> float:
    return _number(value, field=field, minimum=0.0, maximum=1.0)


def _hint(value: object, *, field: str) -> float:
    return _number(value, field=field, minimum=-1.0, maximum=1.0)


def _scale(value: object, *, field: str) -> float:
    return _number(value, field=field, minimum=0.0, maximum=2.0)


def _optional_string(
    value: object,
    *,
    field: str,
    pattern: re.Pattern[str] | None = None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 160:
        raise RenderFrameValidationError(
            f"{field} must be null or a bounded non-empty string"
        )
    if pattern is not None and pattern.fullmatch(value) is None:
        raise RenderFrameValidationError(f"{field} contains unsupported characters")
    return value


def _required_enum(value: object, *, field: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RenderFrameValidationError(f"{field} is unsupported")
    return value


def _face_channels(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, list):
        raise RenderFrameValidationError("face_channels must be an array")
    if len(value) > 32:
        raise RenderFrameValidationError("face_channels exceeds safety cap")
    result: list[tuple[str, float]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"id", "value"}:
            raise RenderFrameValidationError(
                "each face channel requires exactly id/value"
            )
        identifier = item.get("id")
        if not isinstance(identifier, str) or _SEMANTIC_ID_RE.fullmatch(identifier) is None:
            raise RenderFrameValidationError("face channel id is invalid")
        if identifier in seen:
            raise RenderFrameValidationError("face channel ids must be unique")
        seen.add(identifier)
        result.append(
            (
                identifier,
                _unit(item.get("value"), field=f"face_channels.{identifier}"),
            )
        )
    return tuple(result)


def _face_sources(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise RenderFrameValidationError("face_channel_sources must be an array")
    if len(value) > 32:
        raise RenderFrameValidationError("face_channel_sources exceeds safety cap")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"id", "source"}:
            raise RenderFrameValidationError(
                "each face channel source requires exactly id/source"
            )
        identifier = item.get("id")
        source = item.get("source")
        if not isinstance(identifier, str) or _SEMANTIC_ID_RE.fullmatch(identifier) is None:
            raise RenderFrameValidationError("face channel source id is invalid")
        if not isinstance(source, str) or _SOURCE_RE.fullmatch(source) is None:
            raise RenderFrameValidationError("face channel source is invalid")
        if identifier in seen:
            raise RenderFrameValidationError("face channel source ids must be unique")
        seen.add(identifier)
        result.append((identifier, source))
    return tuple(result)


def _optional_frequency(value: object) -> float | None:
    if not isinstance(value, Mapping) or set(value) != {"present", "value"}:
        raise RenderFrameValidationError(
            "gesture_frequency_per_minute requires exactly present/value"
        )
    present = value.get("present")
    if type(present) is not bool:
        raise RenderFrameValidationError(
            "gesture_frequency_per_minute.present must be boolean"
        )
    number = _number(
        value.get("value"),
        field="gesture_frequency_per_minute.value",
        minimum=0.0,
        maximum=600.0,
    )
    if not present:
        if number != 0.0:
            raise RenderFrameValidationError(
                "absent gesture_frequency_per_minute must carry canonical zero value"
            )
        return None
    return number


def render_frame_to_mapping(frame: RenderFrame) -> dict[str, Any]:
    """Serialize one renderer-neutral frame into the complete stable v0.1 wire shape."""

    payload: dict[str, Any] = {
        "type": _TYPE,
        "version": _VERSION,
        "timestamp_ms": frame.timestamp_ms,
        "state": frame.state.value,
        "gesture": frame.gesture,
        "gaze_target": frame.gaze_target,
        "gaze_strength": frame.gaze_strength,
        "emotion": frame.emotion,
        "emotion_intensity": frame.emotion_intensity,
        "energy": frame.energy,
        "mouth_open": frame.mouth_open,
        "visemes": [
            {"id": identifier, "weight": weight}
            for identifier, weight in frame.visemes
        ],
        "speech_timing_mode": (
            frame.speech_timing_mode.value if frame.speech_timing_mode else None
        ),
        "blink": frame.blink,
        "breath": frame.breath,
        "head_yaw_hint": frame.head_yaw_hint,
        "head_pitch_hint": frame.head_pitch_hint,
        "face_profile_id": frame.face_profile_id,
        "face_channels": [
            {"id": identifier, "value": value}
            for identifier, value in frame.face_channels
        ],
        "face_channel_sources": [
            {"id": identifier, "source": source}
            for identifier, source in frame.face_channel_sources
        ],
        "body_motion_profile_id": frame.body_motion_profile_id,
        "body_motion_source": frame.body_motion_source,
        "head_motion_scale": frame.head_motion_scale,
        "micro_motion_scale": frame.micro_motion_scale,
        "posture_lean_x": frame.posture_lean_x,
        "posture_source": frame.posture_source,
        "resolved_gesture": frame.resolved_gesture,
        "gesture_resolution_source": frame.gesture_resolution_source,
        "dominant_side_hint": frame.dominant_side_hint,
        "gesture_frequency_per_minute": {
            "present": frame.gesture_frequency_per_minute is not None,
            "value": (
                frame.gesture_frequency_per_minute
                if frame.gesture_frequency_per_minute is not None
                else 0.0
            ),
        },
    }
    parsed = render_frame_from_mapping(payload)
    if parsed != frame:
        raise RenderFrameValidationError(
            "render frame cannot round-trip through the canonical v0.1 wire contract"
        )
    return payload


def render_frame_from_mapping(payload: Mapping[str, Any]) -> RenderFrame:
    """Validate and deserialize a complete canonical BodyRig renderer frame.

    Renderer adapters may reject a frame, but malformed renderer input must
    never mutate BodyRig semantic runtime. Every renderer-neutral field emitted
    by the current scheduler is carried across this draft v0.1 boundary.
    """

    if not isinstance(payload, Mapping):
        raise RenderFrameValidationError("render frame must be an object")
    expected = {
        "type",
        "version",
        "timestamp_ms",
        "state",
        "gesture",
        "gaze_target",
        "gaze_strength",
        "emotion",
        "emotion_intensity",
        "energy",
        "mouth_open",
        "visemes",
        "speech_timing_mode",
        "blink",
        "breath",
        "head_yaw_hint",
        "head_pitch_hint",
        "face_profile_id",
        "face_channels",
        "face_channel_sources",
        "body_motion_profile_id",
        "body_motion_source",
        "head_motion_scale",
        "micro_motion_scale",
        "posture_lean_x",
        "posture_source",
        "resolved_gesture",
        "gesture_resolution_source",
        "dominant_side_hint",
        "gesture_frequency_per_minute",
    }
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        extra = sorted(set(payload) - expected)
        raise RenderFrameValidationError(
            f"render frame fields mismatch; missing={missing}, extra={extra}"
        )
    if payload.get("type") != _TYPE or payload.get("version") != _VERSION:
        raise RenderFrameValidationError("unsupported render frame type/version")

    timestamp = payload.get("timestamp_ms")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        raise RenderFrameValidationError("timestamp_ms must be a non-negative integer")

    try:
        state = BodyState(str(payload.get("state")))
    except ValueError as exc:
        raise RenderFrameValidationError("unsupported body state") from exc

    gesture = _optional_string(payload.get("gesture"), field="gesture")
    gaze_target = _optional_string(payload.get("gaze_target"), field="gaze_target")

    emotion = payload.get("emotion")
    if not isinstance(emotion, str) or not emotion or len(emotion) > 160:
        raise RenderFrameValidationError("emotion must be a bounded non-empty string")

    visemes_raw = payload.get("visemes")
    if not isinstance(visemes_raw, list) or len(visemes_raw) > 32:
        raise RenderFrameValidationError("visemes must be a bounded array")
    visemes: list[tuple[str, float]] = []
    seen_visemes: set[str] = set()
    for item in visemes_raw:
        if not isinstance(item, Mapping) or set(item) != {"id", "weight"}:
            raise RenderFrameValidationError("each viseme requires exactly id/weight")
        identifier = item.get("id")
        if not isinstance(identifier, str) or _ID_RE.fullmatch(identifier) is None:
            raise RenderFrameValidationError("viseme id is invalid")
        if identifier in seen_visemes:
            raise RenderFrameValidationError("viseme ids must be unique")
        seen_visemes.add(identifier)
        visemes.append(
            (
                identifier,
                _unit(item.get("weight"), field=f"viseme.{identifier}.weight"),
            )
        )

    mode_raw = payload.get("speech_timing_mode")
    if mode_raw is None:
        mode = None
    else:
        try:
            mode = TimingMode(str(mode_raw))
        except ValueError as exc:
            raise RenderFrameValidationError("unsupported speech_timing_mode") from exc

    face_channels = _face_channels(payload.get("face_channels"))
    face_sources = _face_sources(payload.get("face_channel_sources"))
    if tuple(name for name, _value in face_channels) != tuple(
        name for name, _source in face_sources
    ):
        raise RenderFrameValidationError(
            "face channel source ids/order must match face channel ids/order"
        )

    body_motion_source = _required_enum(
        payload.get("body_motion_source"),
        field="body_motion_source",
        allowed=_BODY_MOTION_SOURCES,
    )
    posture_source = _required_enum(
        payload.get("posture_source"),
        field="posture_source",
        allowed=_POSTURE_SOURCES,
    )
    gesture_source = _required_enum(
        payload.get("gesture_resolution_source"),
        field="gesture_resolution_source",
        allowed=_GESTURE_SOURCES,
    )

    dominant_raw = payload.get("dominant_side_hint")
    if dominant_raw is None:
        dominant = None
    else:
        dominant = _required_enum(
            dominant_raw,
            field="dominant_side_hint",
            allowed=_DOMINANT_SIDES,
        )

    return RenderFrame(
        timestamp_ms=timestamp,
        state=state,
        gesture=gesture,
        gaze_target=gaze_target,
        gaze_strength=_unit(payload.get("gaze_strength"), field="gaze_strength"),
        emotion=emotion,
        emotion_intensity=_unit(
            payload.get("emotion_intensity"), field="emotion_intensity"
        ),
        energy=_unit(payload.get("energy"), field="energy"),
        mouth_open=_unit(payload.get("mouth_open"), field="mouth_open"),
        visemes=tuple(visemes),
        speech_timing_mode=mode,
        blink=_unit(payload.get("blink"), field="blink"),
        breath=_unit(payload.get("breath"), field="breath"),
        head_yaw_hint=_hint(payload.get("head_yaw_hint"), field="head_yaw_hint"),
        head_pitch_hint=_hint(
            payload.get("head_pitch_hint"), field="head_pitch_hint"
        ),
        face_profile_id=_optional_string(
            payload.get("face_profile_id"), field="face_profile_id", pattern=_ID_RE
        ),
        face_channels=face_channels,
        face_channel_sources=face_sources,
        body_motion_profile_id=_optional_string(
            payload.get("body_motion_profile_id"),
            field="body_motion_profile_id",
            pattern=_ID_RE,
        ),
        body_motion_source=body_motion_source,
        head_motion_scale=_scale(
            payload.get("head_motion_scale"), field="head_motion_scale"
        ),
        micro_motion_scale=_scale(
            payload.get("micro_motion_scale"), field="micro_motion_scale"
        ),
        posture_lean_x=_hint(
            payload.get("posture_lean_x"), field="posture_lean_x"
        ),
        posture_source=posture_source,
        resolved_gesture=_optional_string(
            payload.get("resolved_gesture"), field="resolved_gesture"
        ),
        gesture_resolution_source=gesture_source,
        dominant_side_hint=dominant,
        gesture_frequency_per_minute=_optional_frequency(
            payload.get("gesture_frequency_per_minute")
        ),
    )
