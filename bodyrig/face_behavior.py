"""Deterministic BodyRig M2.1 facial-behavior profile from tracking v1.

The profile records observed facial behavior, not facial identity geometry. It is
renderer-neutral and does not emit VRM expressions. Missing observations remain
explicitly absent (``null`` with zero samples) instead of being converted into a
fabricated neutral prior.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from .tracking import (
    COORDINATE_SPACE,
    SCHEMA as TRACKING_SCHEMA,
    canonical_tracking_json,
)

SCHEMA = "bodyrig.face_behavior/v0.1"
BUILDER_ID = "modelrig.bodyrig.face_behavior"
BUILDER_VERSION = "0.1.0"

_EXPRESSION_IDS = frozenset(
    {
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
    }
)
_PRIOR_IDS = frozenset({"jaw_open", "smile", "frown", "brow_inner_up", "brow_down"})


class FaceBehaviorError(ValueError):
    """Tracking input or facial-behavior output violates the M2.1 contract."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FaceBehaviorError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise FaceBehaviorError(f"{label} must be finite")
    return number


def _unit(value: Any, label: str) -> float:
    number = _finite(value, label)
    if not 0.0 <= number <= 1.0:
        raise FaceBehaviorError(f"{label} must be within [0,1]")
    return number


def _round(value: float) -> float:
    return round(float(value), 6)


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise FaceBehaviorError(f"{label} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise FaceBehaviorError(f"{label} must be a SHA-256 hex digest") from exc
    return value.lower()


def _validate_tracking(tracking: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(tracking, Mapping):
        raise FaceBehaviorError("tracking must be an object")
    if tracking.get("schema") != TRACKING_SCHEMA:
        raise FaceBehaviorError(f"tracking.schema must be {TRACKING_SCHEMA}")
    if tracking.get("coordinate_space") != COORDINATE_SPACE:
        raise FaceBehaviorError(f"tracking.coordinate_space must be {COORDINATE_SPACE}")
    if tracking.get("production_activation") is not False:
        raise FaceBehaviorError("tracking production_activation must remain false")

    source = tracking.get("source")
    backend = tracking.get("backend")
    if not isinstance(source, Mapping):
        raise FaceBehaviorError("tracking source provenance is required")
    _sha256(source.get("sha256"), "tracking.source.sha256")
    if not isinstance(backend, Mapping):
        raise FaceBehaviorError("tracking backend provenance is required")
    for key in ("id", "version", "model_revision"):
        if not isinstance(backend.get(key), str) or not backend[key]:
            raise FaceBehaviorError(f"tracking.backend.{key} is required")

    frames = tracking.get("frames")
    if not isinstance(frames, list):
        raise FaceBehaviorError("tracking.frames must be an array")
    result: list[Mapping[str, Any]] = []
    previous = -1
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise FaceBehaviorError(f"tracking.frames[{index}] must be an object")
        timestamp = frame.get("timestamp_us")
        if type(timestamp) is not int or timestamp < 0 or timestamp <= previous:
            raise FaceBehaviorError("tracking frame timestamps must be strictly increasing")
        previous = timestamp
        expressions = frame.get("expressions")
        if expressions is not None:
            if not isinstance(expressions, Mapping) or not expressions:
                raise FaceBehaviorError(
                    f"tracking.frames[{index}].expressions must be non-empty or null"
                )
            unknown = set(expressions) - _EXPRESSION_IDS
            if unknown:
                raise FaceBehaviorError(f"unsupported expression ids: {sorted(unknown)}")
            for key, value in expressions.items():
                _unit(value, f"tracking.frames[{index}].expressions.{key}")
        result.append(frame)

    try:
        canonical_tracking_json(tracking)
    except Exception as exc:
        raise FaceBehaviorError(str(exc)) from exc
    return result


def _series(frames: list[Mapping[str, Any]], key: str) -> list[tuple[int, float]]:
    result: list[tuple[int, float]] = []
    for frame in frames:
        expressions = frame.get("expressions")
        if isinstance(expressions, Mapping) and key in expressions:
            result.append((frame["timestamp_us"], _unit(expressions[key], key)))
    return result


def _prior(values: list[float], total_frames: int) -> dict[str, Any]:
    if not values:
        return {"mean": None, "samples": 0, "coverage": 0.0}
    return {
        "mean": _round(sum(values) / len(values)),
        "samples": len(values),
        "coverage": _round(len(values) / total_frames) if total_frames else 0.0,
    }


def _paired_prior(
    frames: list[Mapping[str, Any]], left_key: str, right_key: str
) -> dict[str, Any]:
    values: list[float] = []
    for frame in frames:
        expressions = frame.get("expressions")
        if not isinstance(expressions, Mapping):
            continue
        observed = [
            _unit(expressions[key], key)
            for key in (left_key, right_key)
            if key in expressions
        ]
        if observed:
            values.append(sum(observed) / len(observed))
    return _prior(values, len(frames))


def _event_rate(
    series: list[tuple[int, float]], *, threshold: float = 0.55
) -> dict[str, Any]:
    if not series:
        return {"events": 0, "samples": 0, "per_minute": None}
    events = 0
    active = series[0][1] >= threshold
    for _timestamp, value in series[1:]:
        now = value >= threshold
        if now and not active:
            events += 1
        active = now
    if len(series) < 2:
        rate = None
    else:
        duration_us = series[-1][0] - series[0][0]
        rate = None if duration_us <= 0 else _round(events * 60_000_000.0 / duration_us)
    return {"events": events, "samples": len(series), "per_minute": rate}


def _nullable_mean(values: list[float]) -> float | None:
    return _round(sum(values) / len(values)) if values else None


def _identity_payload(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in profile.items() if key != "id"}


def _content_id(profile: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _identity_payload(profile),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"face-{hashlib.sha256(canonical).hexdigest()[:24]}"


def build_face_behavior(tracking: Mapping[str, Any]) -> dict[str, Any]:
    """Build one deterministic facial-behavior profile from normalized tracking."""
    frames = _validate_tracking(tracking)
    total_frames = len(frames)
    expression_frames = sum(
        1 for frame in frames if isinstance(frame.get("expressions"), Mapping)
    )

    left_blink = _event_rate(_series(frames, "blink_left"))
    right_blink = _event_rate(_series(frames, "blink_right"))
    paired_asymmetry: list[float] = []
    for frame in frames:
        expressions = frame.get("expressions")
        if (
            isinstance(expressions, Mapping)
            and "blink_left" in expressions
            and "blink_right" in expressions
        ):
            paired_asymmetry.append(
                abs(
                    _unit(expressions["blink_left"], "blink_left")
                    - _unit(expressions["blink_right"], "blink_right")
                )
            )

    available_rates = [
        value
        for value in (left_blink["per_minute"], right_blink["per_minute"])
        if value is not None
    ]

    coverage = tracking.get("coverage")
    face_coverage = 0.0
    face_confidence = 0.0
    if isinstance(coverage, Mapping) and isinstance(coverage.get("face"), Mapping):
        face = coverage["face"]
        face_coverage = _unit(face.get("coverage", 0.0), "coverage.face.coverage")
        face_confidence = _unit(
            face.get("mean_confidence", 0.0), "coverage.face.mean_confidence"
        )

    source = tracking["source"]
    backend = tracking["backend"]
    tracking_json = canonical_tracking_json(tracking)
    profile: dict[str, Any] = {
        "schema": SCHEMA,
        "id": "pending",
        "observation": {
            "timeline_frames": total_frames,
            "expression_frames": expression_frames,
            "expression_coverage": _round(expression_frames / total_frames)
            if total_frames
            else 0.0,
            "face_coverage": _round(face_coverage),
            "face_landmark_confidence": _round(face_confidence),
        },
        "blink": {
            "left": left_blink,
            "right": right_blink,
            "mean_per_minute": _nullable_mean(available_rates),
            "paired_asymmetry": _prior(paired_asymmetry, total_frames),
        },
        "expression_priors": {
            "jaw_open": _prior(
                [value for _timestamp, value in _series(frames, "jaw_open")],
                total_frames,
            ),
            "smile": _paired_prior(
                frames, "mouth_smile_left", "mouth_smile_right"
            ),
            "frown": _paired_prior(
                frames, "mouth_frown_left", "mouth_frown_right"
            ),
            "brow_inner_up": _prior(
                [value for _timestamp, value in _series(frames, "brow_inner_up")],
                total_frames,
            ),
            "brow_down": _paired_prior(
                frames, "brow_down_left", "brow_down_right"
            ),
        },
        "provenance": {
            "tracking_schema": TRACKING_SCHEMA,
            "tracking_sha256": hashlib.sha256(tracking_json.encode("utf-8")).hexdigest(),
            "source_sha256": source["sha256"],
            "backend": {
                "id": backend["id"],
                "version": backend["version"],
                "model_revision": backend["model_revision"],
            },
            "builder": {"id": BUILDER_ID, "version": BUILDER_VERSION},
            "source_video_required_at_runtime": False,
        },
        "production_activation": False,
    }
    profile["id"] = _content_id(profile)
    validate_face_behavior(profile)
    return profile


def _validate_prior(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != {"mean", "samples", "coverage"}:
        raise FaceBehaviorError(f"{label} has invalid fields")
    if type(value["samples"]) is not int or value["samples"] < 0:
        raise FaceBehaviorError(f"{label}.samples must be a non-negative integer")
    _unit(value["coverage"], f"{label}.coverage")
    mean = value["mean"]
    if value["samples"] == 0:
        if mean is not None or value["coverage"] != 0.0:
            raise FaceBehaviorError(f"{label} missing evidence must remain null/zero coverage")
    else:
        if mean is None:
            raise FaceBehaviorError(f"{label}.mean is required when samples exist")
        _unit(mean, f"{label}.mean")


def _validate_rate(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != {"events", "samples", "per_minute"}:
        raise FaceBehaviorError(f"{label} has invalid fields")
    for key in ("events", "samples"):
        if type(value[key]) is not int or value[key] < 0:
            raise FaceBehaviorError(f"{label}.{key} must be a non-negative integer")
    if value["events"] > value["samples"]:
        raise FaceBehaviorError(f"{label}.events cannot exceed samples")
    rate = value["per_minute"]
    if value["samples"] < 2:
        if rate is not None:
            raise FaceBehaviorError(f"{label}.per_minute must be null with fewer than two samples")
    elif rate is not None:
        number = _finite(rate, f"{label}.per_minute")
        if not 0.0 <= number <= 600.0:
            raise FaceBehaviorError(f"{label}.per_minute is out of range")


def validate_face_behavior(profile: Mapping[str, Any]) -> None:
    if not isinstance(profile, Mapping):
        raise FaceBehaviorError("face behavior profile must be an object")
    expected = {
        "schema",
        "id",
        "observation",
        "blink",
        "expression_priors",
        "provenance",
        "production_activation",
    }
    if set(profile) != expected:
        raise FaceBehaviorError("face behavior contains missing or unsupported top-level fields")
    if profile.get("schema") != SCHEMA:
        raise FaceBehaviorError(f"schema must be {SCHEMA}")
    if profile.get("production_activation") is not False:
        raise FaceBehaviorError("production_activation must remain false")

    observation = profile.get("observation")
    observation_keys = {
        "timeline_frames",
        "expression_frames",
        "expression_coverage",
        "face_coverage",
        "face_landmark_confidence",
    }
    if not isinstance(observation, Mapping) or set(observation) != observation_keys:
        raise FaceBehaviorError("observation fields are invalid")
    for key in ("timeline_frames", "expression_frames"):
        if type(observation[key]) is not int or observation[key] < 0:
            raise FaceBehaviorError(f"observation.{key} must be a non-negative integer")
    if observation["expression_frames"] > observation["timeline_frames"]:
        raise FaceBehaviorError("expression_frames cannot exceed timeline_frames")
    for key in ("expression_coverage", "face_coverage", "face_landmark_confidence"):
        _unit(observation[key], f"observation.{key}")

    blink = profile.get("blink")
    if not isinstance(blink, Mapping) or set(blink) != {
        "left",
        "right",
        "mean_per_minute",
        "paired_asymmetry",
    }:
        raise FaceBehaviorError("blink fields are invalid")
    _validate_rate(blink["left"], "blink.left")
    _validate_rate(blink["right"], "blink.right")
    mean_rate = blink["mean_per_minute"]
    if mean_rate is not None:
        number = _finite(mean_rate, "blink.mean_per_minute")
        if not 0.0 <= number <= 600.0:
            raise FaceBehaviorError("blink.mean_per_minute is out of range")
    _validate_prior(blink["paired_asymmetry"], "blink.paired_asymmetry")

    priors = profile.get("expression_priors")
    if not isinstance(priors, Mapping) or set(priors) != _PRIOR_IDS:
        raise FaceBehaviorError("expression_priors fields are invalid")
    for key in sorted(_PRIOR_IDS):
        _validate_prior(priors[key], f"expression_priors.{key}")

    provenance = profile.get("provenance")
    if not isinstance(provenance, Mapping):
        raise FaceBehaviorError("provenance must be an object")
    if provenance.get("tracking_schema") != TRACKING_SCHEMA:
        raise FaceBehaviorError("provenance.tracking_schema is invalid")
    _sha256(provenance.get("tracking_sha256"), "provenance.tracking_sha256")
    _sha256(provenance.get("source_sha256"), "provenance.source_sha256")
    backend = provenance.get("backend")
    builder = provenance.get("builder")
    if not isinstance(backend, Mapping) or not all(
        isinstance(backend.get(key), str) and backend[key]
        for key in ("id", "version", "model_revision")
    ):
        raise FaceBehaviorError("backend provenance is invalid")
    if (
        not isinstance(builder, Mapping)
        or builder.get("id") != BUILDER_ID
        or builder.get("version") != BUILDER_VERSION
    ):
        raise FaceBehaviorError("builder provenance is invalid")
    if provenance.get("source_video_required_at_runtime") is not False:
        raise FaceBehaviorError("runtime must not require source video")

    if profile.get("id") != _content_id(profile):
        raise FaceBehaviorError("face behavior id does not match content")


def canonical_face_behavior_json(profile: Mapping[str, Any]) -> str:
    validate_face_behavior(profile)
    return json.dumps(
        profile,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
