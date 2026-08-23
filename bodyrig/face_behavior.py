"""Deterministic BodyRig M2.1 facial-behavior priors from tracking v1.

This module deliberately stays renderer-neutral. It summarizes observed facial
expression behavior into bounded priors that a later runtime mixer may consume;
it does not emit VRM morph commands and it never fabricates missing evidence.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .tracking import SCHEMA as TRACKING_SCHEMA

FACE_BEHAVIOR_SCHEMA = "bodyrig.face_behavior/v0.1"
_EXPRESSION_IDS = (
    "blink_left",
    "blink_right",
    "jaw_open",
    "mouth_smile_left",
    "mouth_smile_right",
    "mouth_frown_left",
    "mouth_frown_right",
    "brow_inner_up",
    "brow_down_left",
    "brow_down_right",
)


class FaceBehaviorError(ValueError):
    """Tracking input or derived face-behavior data violates M2.1."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FaceBehaviorError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise FaceBehaviorError(f"{label} must be finite")
    return value


def _unit(value: Any, label: str) -> float:
    value = _finite(value, label)
    if not 0.0 <= value <= 1.0:
        raise FaceBehaviorError(f"{label} must be within [0,1]")
    return value


def _round(value: float) -> float:
    return round(float(value), 6)


def _validate_tracking(tracking: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(tracking, Mapping):
        raise FaceBehaviorError("tracking must be an object")
    if tracking.get("schema") != TRACKING_SCHEMA:
        raise FaceBehaviorError(f"tracking.schema must be {TRACKING_SCHEMA}")
    if tracking.get("production_activation") is not False:
        raise FaceBehaviorError("tracking production_activation must remain false")
    frames = tracking.get("frames")
    if not isinstance(frames, list):
        raise FaceBehaviorError("tracking.frames must be an array")
    last_timestamp = -1
    result: list[Mapping[str, Any]] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise FaceBehaviorError(f"tracking.frames[{index}] must be an object")
        timestamp = frame.get("timestamp_us")
        if type(timestamp) is not int or timestamp < 0 or timestamp <= last_timestamp:
            raise FaceBehaviorError("tracking frame timestamps must be strictly increasing")
        last_timestamp = timestamp
        expressions = frame.get("expressions")
        if expressions is not None:
            if not isinstance(expressions, Mapping) or not expressions:
                raise FaceBehaviorError(f"tracking.frames[{index}].expressions must be non-empty or null")
            unknown = set(expressions) - set(_EXPRESSION_IDS)
            if unknown:
                raise FaceBehaviorError(f"unsupported expression ids: {sorted(unknown)}")
            for key, value in expressions.items():
                _unit(value, f"tracking.frames[{index}].expressions.{key}")
        result.append(frame)
    return result


def _series(frames: list[Mapping[str, Any]], key: str) -> list[tuple[int, float]]:
    values: list[tuple[int, float]] = []
    for frame in frames:
        expressions = frame.get("expressions")
        if isinstance(expressions, Mapping) and key in expressions:
            values.append((frame["timestamp_us"], _unit(expressions[key], key)))
    return values


def _mean(values: list[float]) -> float:
    return _round(sum(values) / len(values)) if values else 0.0


def _event_rate_per_minute(series: list[tuple[int, float]], *, threshold: float = 0.55) -> tuple[float, int]:
    if len(series) < 2:
        return 0.0, 0
    events = 0
    active = series[0][1] >= threshold
    for _timestamp, value in series[1:]:
        now_active = value >= threshold
        if now_active and not active:
            events += 1
        active = now_active
    duration_us = series[-1][0] - series[0][0]
    if duration_us <= 0:
        return 0.0, events
    return _round(events * 60_000_000.0 / duration_us), events


def build_face_behavior(tracking: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic, bounded facial-behavior priors from tracking v1."""
    frames = _validate_tracking(tracking)
    expression_frames = sum(1 for frame in frames if isinstance(frame.get("expressions"), Mapping))
    total_frames = len(frames)

    left_blink = _series(frames, "blink_left")
    right_blink = _series(frames, "blink_right")
    left_rate, left_events = _event_rate_per_minute(left_blink)
    right_rate, right_events = _event_rate_per_minute(right_blink)

    def paired_mean(left_key: str, right_key: str) -> float:
        values: list[float] = []
        for frame in frames:
            expressions = frame.get("expressions")
            if not isinstance(expressions, Mapping):
                continue
            sides = [
                _unit(expressions[key], key)
                for key in (left_key, right_key)
                if key in expressions
            ]
            if sides:
                values.append(sum(sides) / len(sides))
        return _mean(values)

    asymmetry_values: list[float] = []
    for frame in frames:
        expressions = frame.get("expressions")
        if isinstance(expressions, Mapping) and "blink_left" in expressions and "blink_right" in expressions:
            asymmetry_values.append(abs(
                _unit(expressions["blink_left"], "blink_left")
                - _unit(expressions["blink_right"], "blink_right")
            ))

    coverage = tracking.get("coverage")
    face_coverage = 0.0
    face_confidence = 0.0
    if isinstance(coverage, Mapping) and isinstance(coverage.get("face"), Mapping):
        face = coverage["face"]
        face_coverage = _unit(face.get("coverage", 0.0), "coverage.face.coverage")
        face_confidence = _unit(face.get("mean_confidence", 0.0), "coverage.face.mean_confidence")

    payload = {
        "schema": FACE_BEHAVIOR_SCHEMA,
        "tracking_schema": TRACKING_SCHEMA,
        "observation": {
            "timeline_frames": total_frames,
            "expression_frames": expression_frames,
            "expression_coverage": _round(expression_frames / total_frames) if total_frames else 0.0,
            "face_coverage": _round(face_coverage),
            "face_landmark_confidence": _round(face_confidence),
        },
        "blink": {
            "left_events": left_events,
            "right_events": right_events,
            "left_per_minute": left_rate,
            "right_per_minute": right_rate,
            "mean_per_minute": _round((left_rate + right_rate) / 2.0),
            "mean_asymmetry": _mean(asymmetry_values),
        },
        "expression_priors": {
            "jaw_open": _mean([value for _ts, value in _series(frames, "jaw_open")]),
            "smile": paired_mean("mouth_smile_left", "mouth_smile_right"),
            "frown": paired_mean("mouth_frown_left", "mouth_frown_right"),
            "brow_inner_up": _mean([value for _ts, value in _series(frames, "brow_inner_up")]),
            "brow_down": paired_mean("brow_down_left", "brow_down_right"),
        },
        "production_activation": False,
    }
    validate_face_behavior(payload)
    return payload


def validate_face_behavior(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise FaceBehaviorError("face behavior must be an object")
    if set(payload) != {"schema", "tracking_schema", "observation", "blink", "expression_priors", "production_activation"}:
        raise FaceBehaviorError("face behavior contains missing or unsupported top-level fields")
    if payload.get("schema") != FACE_BEHAVIOR_SCHEMA:
        raise FaceBehaviorError(f"schema must be {FACE_BEHAVIOR_SCHEMA}")
    if payload.get("tracking_schema") != TRACKING_SCHEMA:
        raise FaceBehaviorError(f"tracking_schema must be {TRACKING_SCHEMA}")
    if payload.get("production_activation") is not False:
        raise FaceBehaviorError("production_activation must remain false")

    observation = payload.get("observation")
    if not isinstance(observation, Mapping) or set(observation) != {
        "timeline_frames", "expression_frames", "expression_coverage", "face_coverage", "face_landmark_confidence"
    }:
        raise FaceBehaviorError("observation fields are invalid")
    for key in ("timeline_frames", "expression_frames"):
        if type(observation[key]) is not int or observation[key] < 0:
            raise FaceBehaviorError(f"observation.{key} must be a non-negative integer")
    if observation["expression_frames"] > observation["timeline_frames"]:
        raise FaceBehaviorError("expression_frames cannot exceed timeline_frames")
    for key in ("expression_coverage", "face_coverage", "face_landmark_confidence"):
        _unit(observation[key], f"observation.{key}")

    blink = payload.get("blink")
    if not isinstance(blink, Mapping) or set(blink) != {
        "left_events", "right_events", "left_per_minute", "right_per_minute", "mean_per_minute", "mean_asymmetry"
    }:
        raise FaceBehaviorError("blink fields are invalid")
    for key in ("left_events", "right_events"):
        if type(blink[key]) is not int or blink[key] < 0:
            raise FaceBehaviorError(f"blink.{key} must be a non-negative integer")
    for key in ("left_per_minute", "right_per_minute", "mean_per_minute"):
        value = _finite(blink[key], f"blink.{key}")
        if not 0.0 <= value <= 600.0:
            raise FaceBehaviorError(f"blink.{key} is out of range")
    _unit(blink["mean_asymmetry"], "blink.mean_asymmetry")

    priors = payload.get("expression_priors")
    expected = {"jaw_open", "smile", "frown", "brow_inner_up", "brow_down"}
    if not isinstance(priors, Mapping) or set(priors) != expected:
        raise FaceBehaviorError("expression_priors fields are invalid")
    for key in expected:
        _unit(priors[key], f"expression_priors.{key}")


def canonical_face_behavior_json(payload: Mapping[str, Any]) -> str:
    validate_face_behavior(payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
