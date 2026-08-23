"""Deterministic BodyRig M1.3 source-relative body proportion profile.

This module deliberately measures only image-relative landmark ratios from the
stable ``bodyrig.tracking/v1`` contract. It does not claim metric anthropometry,
volumetric body shape, body mass or photorealistic likeness. A future 3D recovery
adapter may provide better observations without changing this profile boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from statistics import median
from typing import Any, Mapping

from .tracking import COORDINATE_SPACE, SCHEMA as TRACKING_SCHEMA, canonical_tracking_json

SCHEMA = "bodyrig.shape_profile/v0.1"
METHOD = "image_relative_landmark_ratios/v1"
BUILDER_ID = "modelrig.bodyrig.shape_profile"
BUILDER_VERSION = "0.1.0"


class ShapeProfileError(ValueError):
    """Tracking input or generated shape profile violates the M1.3 contract."""


@dataclass(frozen=True)
class ShapeConfig:
    min_point_confidence: float = 0.35
    min_samples: int = 3

    def to_dict(self) -> dict[str, Any]:
        confidence = _unit(self.min_point_confidence, "config.min_point_confidence")
        if type(self.min_samples) is not int or not 1 <= self.min_samples <= 10000:
            raise ShapeProfileError("config.min_samples must be an integer within [1,10000]")
        return {"min_point_confidence": _round(confidence), "min_samples": self.min_samples}


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShapeProfileError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ShapeProfileError(f"{label} must be finite")
    return number


def _unit(value: Any, label: str) -> float:
    number = _finite(value, label)
    if not 0.0 <= number <= 1.0:
        raise ShapeProfileError(f"{label} must be within [0,1]")
    return number


def _round(value: float) -> float:
    return round(float(value), 6)


def _point(raw: Any, label: str) -> tuple[float, float, float, float]:
    if not isinstance(raw, Mapping):
        raise ShapeProfileError(f"{label} must be an object")
    x = _unit(raw.get("x"), f"{label}.x")
    y = _unit(raw.get("y"), f"{label}.y")
    z = _finite(raw.get("z"), f"{label}.z")
    if not -4.0 <= z <= 4.0:
        raise ShapeProfileError(f"{label}.z must be within [-4,4]")
    confidence = _unit(raw.get("confidence"), f"{label}.confidence")
    return x, y, z, confidence


def _distance(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


def _midpoint(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (
        (a[0] + b[0]) / 2.0,
        (a[1] + b[1]) / 2.0,
        (a[2] + b[2]) / 2.0,
        min(a[3], b[3]),
    )


def _body_frame(raw: Any, index: int) -> dict[str, tuple[float, float, float, float]] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or not raw:
        raise ShapeProfileError(f"tracking.frames[{index}].body must be non-empty or null")
    result: dict[str, tuple[float, float, float, float]] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise ShapeProfileError("body landmark ids must be non-empty strings")
        result[name] = _point(value, f"tracking.frames[{index}].body.{name}")
    return result


def _validate_tracking(payload: Mapping[str, Any]) -> list[tuple[int, dict[str, tuple[float, float, float, float]] | None]]:
    if not isinstance(payload, Mapping):
        raise ShapeProfileError("tracking payload must be an object")
    if payload.get("schema") != TRACKING_SCHEMA:
        raise ShapeProfileError(f"tracking schema must be {TRACKING_SCHEMA}")
    if payload.get("coordinate_space") != COORDINATE_SPACE:
        raise ShapeProfileError(f"tracking coordinate_space must be {COORDINATE_SPACE}")
    if payload.get("production_activation") is not False:
        raise ShapeProfileError("tracking production_activation must remain false")
    source = payload.get("source")
    backend = payload.get("backend")
    if not isinstance(source, Mapping) or not isinstance(source.get("sha256"), str):
        raise ShapeProfileError("tracking source provenance is required")
    if len(source["sha256"]) != 64:
        raise ShapeProfileError("tracking source.sha256 must be a SHA-256 digest")
    try:
        int(source["sha256"], 16)
    except ValueError as exc:
        raise ShapeProfileError("tracking source.sha256 must be a SHA-256 digest") from exc
    if not isinstance(backend, Mapping):
        raise ShapeProfileError("tracking backend provenance is required")
    for key in ("id", "version", "model_revision"):
        if not isinstance(backend.get(key), str) or not backend[key]:
            raise ShapeProfileError(f"tracking backend.{key} is required")
    frames = payload.get("frames")
    if not isinstance(frames, list):
        raise ShapeProfileError("tracking.frames must be an array")
    parsed = []
    previous = -1
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise ShapeProfileError(f"tracking.frames[{index}] must be an object")
        timestamp = frame.get("timestamp_us")
        if type(timestamp) is not int or timestamp < 0 or timestamp <= previous:
            raise ShapeProfileError("tracking frame timestamps must be strictly increasing")
        previous = timestamp
        parsed.append((timestamp, _body_frame(frame.get("body"), index)))
    try:
        canonical_tracking_json(payload)
    except Exception as exc:
        raise ShapeProfileError(str(exc)) from exc
    return parsed


_MEASUREMENTS: dict[str, tuple[str, str]] = {
    "shoulder_width": ("left_shoulder", "right_shoulder"),
    "hip_width": ("left_hip", "right_hip"),
    "left_upper_arm": ("left_shoulder", "left_elbow"),
    "right_upper_arm": ("right_shoulder", "right_elbow"),
    "left_lower_arm": ("left_elbow", "left_wrist"),
    "right_lower_arm": ("right_elbow", "right_wrist"),
    "left_upper_leg": ("left_hip", "left_knee"),
    "right_upper_leg": ("right_hip", "right_knee"),
    "left_lower_leg": ("left_knee", "left_ankle"),
    "right_lower_leg": ("right_knee", "right_ankle"),
}

_ASYMMETRY = {
    "upper_arm": ("left_upper_arm", "right_upper_arm"),
    "lower_arm": ("left_lower_arm", "right_lower_arm"),
    "upper_leg": ("left_upper_leg", "right_upper_leg"),
    "lower_leg": ("left_lower_leg", "right_lower_leg"),
}


def _reference(body: Mapping[str, tuple[float, float, float, float]], floor: float) -> tuple[float, float] | None:
    required = [body.get(name) for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")]
    if any(point is None for point in required):
        return None
    points = [point for point in required if point is not None]
    confidence = min(point[3] for point in points)
    if confidence < floor:
        return None
    shoulder_center = _midpoint(points[0], points[1])
    hip_center = _midpoint(points[2], points[3])
    torso = _distance(shoulder_center, hip_center)
    if torso <= 1e-6:
        return None
    return torso, confidence


def _ratio(body: Mapping[str, tuple[float, float, float, float]], left: str, right: str, scale: float, floor: float) -> tuple[float, float] | None:
    a, b = body.get(left), body.get(right)
    if a is None or b is None:
        return None
    confidence = min(a[3], b[3])
    if confidence < floor:
        return None
    return _distance(a, b) / scale, confidence


def _extra_ratios(body: Mapping[str, tuple[float, float, float, float]], scale: float, floor: float) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    shoulder_points = [body.get("left_shoulder"), body.get("right_shoulder")]
    hip_points = [body.get("left_hip"), body.get("right_hip")]
    ankle_points = [body.get("left_ankle"), body.get("right_ankle")]
    wrist_points = [body.get("left_wrist"), body.get("right_wrist")]
    if all(point is not None and point[3] >= floor for point in shoulder_points + hip_points):
        shoulder = _midpoint(shoulder_points[0], shoulder_points[1])  # type: ignore[arg-type]
        hip = _midpoint(hip_points[0], hip_points[1])  # type: ignore[arg-type]
        result["torso_length"] = (_distance(shoulder, hip) / scale, min(shoulder[3], hip[3]))
    if all(point is not None and point[3] >= floor for point in shoulder_points + ankle_points):
        shoulder = _midpoint(shoulder_points[0], shoulder_points[1])  # type: ignore[arg-type]
        ankle = _midpoint(ankle_points[0], ankle_points[1])  # type: ignore[arg-type]
        result["visible_body_span"] = (_distance(shoulder, ankle) / scale, min(shoulder[3], ankle[3]))
    if all(point is not None and point[3] >= floor for point in wrist_points):
        result["wrist_span"] = (_distance(wrist_points[0], wrist_points[1]) / scale, min(wrist_points[0][3], wrist_points[1][3]))  # type: ignore[index,arg-type]
    return result


def _aggregate(samples: list[tuple[float, float]], min_samples: int) -> dict[str, Any] | None:
    if len(samples) < min_samples:
        return None
    values = [value for value, _confidence in samples]
    center = median(values)
    deviations = [abs(value - center) for value in values]
    confidence = sum(confidence for _value, confidence in samples) / len(samples)
    return {
        "ratio": _round(center),
        "samples": len(samples),
        "mean_confidence": _round(confidence),
        "mad": _round(median(deviations)),
    }


def _asymmetry(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_value = _finite(left["ratio"], "left.ratio")
    right_value = _finite(right["ratio"], "right.ratio")
    denominator = (left_value + right_value) / 2.0
    signed = 0.0 if denominator <= 1e-9 else (left_value - right_value) / denominator
    return {
        "signed_ratio": _round(signed),
        "left_longer": bool(signed > 0.01),
        "right_longer": bool(signed < -0.01),
        "confidence": _round(min(float(left["mean_confidence"]), float(right["mean_confidence"]))),
    }


def _identity_payload(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in profile.items() if key != "id"}


def _content_id(profile: Mapping[str, Any]) -> str:
    canonical = json.dumps(_identity_payload(profile), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return f"shape-{hashlib.sha256(canonical).hexdigest()[:24]}"


def build_shape_profile(tracking: Mapping[str, Any], *, config: ShapeConfig | None = None) -> dict[str, Any]:
    frames = _validate_tracking(tracking)
    resolved = (config or ShapeConfig()).to_dict()
    floor = resolved["min_point_confidence"]
    samples: dict[str, list[tuple[float, float]]] = {name: [] for name in (*_MEASUREMENTS, "torso_length", "visible_body_span", "wrist_span")}
    reference_frames = 0
    for _timestamp, body in frames:
        if body is None:
            continue
        reference = _reference(body, floor)
        if reference is None:
            continue
        reference_frames += 1
        scale, reference_confidence = reference
        for name, (left, right) in _MEASUREMENTS.items():
            value = _ratio(body, left, right, scale, floor)
            if value is not None:
                samples[name].append((value[0], min(value[1], reference_confidence)))
        for name, value in _extra_ratios(body, scale, floor).items():
            samples[name].append((value[0], min(value[1], reference_confidence)))

    measurements: dict[str, Any] = {}
    for name in sorted(samples):
        aggregated = _aggregate(samples[name], resolved["min_samples"])
        if aggregated is not None:
            measurements[name] = aggregated
    if "torso_length" not in measurements:
        raise ShapeProfileError("tracking contains insufficient torso evidence for shape profiling")

    asymmetry: dict[str, Any] = {}
    for name, (left, right) in _ASYMMETRY.items():
        if left in measurements and right in measurements:
            asymmetry[name] = _asymmetry(measurements[left], measurements[right])

    recommendations = ["viewpoint_sensitive_2d_profile"]
    expected = set(_MEASUREMENTS) | {"torso_length", "visible_body_span", "wrist_span"}
    missing = sorted(expected - set(measurements))
    if missing:
        recommendations.append("need_more_full_body_views")
    if reference_frames < max(5, resolved["min_samples"]):
        recommendations.append("need_more_stable_torso_frames")

    tracking_json = canonical_tracking_json(tracking)
    source = tracking["source"]
    backend = tracking["backend"]
    evidence_confidences = [item["mean_confidence"] for item in measurements.values()]
    profile: dict[str, Any] = {
        "schema": SCHEMA,
        "id": "pending",
        "method": METHOD,
        "measurement_space": "torso_normalized_source_relative/v1",
        "metric_units": False,
        "measurements": measurements,
        "asymmetry": asymmetry,
        "confidence": _round(sum(evidence_confidences) / len(evidence_confidences)) if evidence_confidences else 0.0,
        "evidence": {
            "input_frames": len(frames),
            "reference_frames": reference_frames,
            "tracking_sha256": hashlib.sha256(tracking_json.encode("utf-8")).hexdigest(),
            "source_sha256": source["sha256"],
            "backend": {"id": backend["id"], "version": backend["version"], "model_revision": backend["model_revision"]},
            "builder": {"id": BUILDER_ID, "version": BUILDER_VERSION, "config": resolved},
            "source_video_required_at_runtime": False,
        },
        "recommendations": recommendations,
        "production_activation": False,
    }
    profile["id"] = _content_id(profile)
    validate_shape_profile(profile)
    return profile


def validate_shape_profile(profile: Mapping[str, Any]) -> None:
    if not isinstance(profile, Mapping):
        raise ShapeProfileError("shape profile must be an object")
    expected = {"schema", "id", "method", "measurement_space", "metric_units", "measurements", "asymmetry", "confidence", "evidence", "recommendations", "production_activation"}
    if set(profile) != expected:
        raise ShapeProfileError("shape profile contains missing or unsupported top-level fields")
    if profile.get("schema") != SCHEMA or profile.get("method") != METHOD:
        raise ShapeProfileError("shape profile schema/method is unsupported")
    if profile.get("measurement_space") != "torso_normalized_source_relative/v1":
        raise ShapeProfileError("shape measurement_space is unsupported")
    if profile.get("metric_units") is not False:
        raise ShapeProfileError("M1.3 must not claim metric body measurements")
    if profile.get("production_activation") is not False:
        raise ShapeProfileError("shape profile production_activation must remain false")
    _unit(profile.get("confidence"), "confidence")
    measurements = profile.get("measurements")
    if not isinstance(measurements, Mapping) or "torso_length" not in measurements:
        raise ShapeProfileError("measurements must contain torso_length")
    allowed = set(_MEASUREMENTS) | {"torso_length", "visible_body_span", "wrist_span"}
    if set(measurements) - allowed:
        raise ShapeProfileError("measurements contains unsupported fields")
    for name, item in measurements.items():
        if not isinstance(item, Mapping) or set(item) != {"ratio", "samples", "mean_confidence", "mad"}:
            raise ShapeProfileError(f"measurements.{name} has invalid shape")
        ratio = _finite(item["ratio"], f"measurements.{name}.ratio")
        if not 0.0 < ratio <= 20.0:
            raise ShapeProfileError(f"measurements.{name}.ratio is out of range")
        if type(item["samples"]) is not int or item["samples"] <= 0:
            raise ShapeProfileError(f"measurements.{name}.samples must be positive integer")
        _unit(item["mean_confidence"], f"measurements.{name}.mean_confidence")
        mad = _finite(item["mad"], f"measurements.{name}.mad")
        if not 0.0 <= mad <= 20.0:
            raise ShapeProfileError(f"measurements.{name}.mad is out of range")
    asymmetry = profile.get("asymmetry")
    if not isinstance(asymmetry, Mapping) or set(asymmetry) - set(_ASYMMETRY):
        raise ShapeProfileError("asymmetry contains unsupported fields")
    for name, item in asymmetry.items():
        if not isinstance(item, Mapping) or set(item) != {"signed_ratio", "left_longer", "right_longer", "confidence"}:
            raise ShapeProfileError(f"asymmetry.{name} has invalid shape")
        signed = _finite(item["signed_ratio"], f"asymmetry.{name}.signed_ratio")
        if not -2.0 <= signed <= 2.0:
            raise ShapeProfileError(f"asymmetry.{name}.signed_ratio is out of range")
        if type(item["left_longer"]) is not bool or type(item["right_longer"]) is not bool or (item["left_longer"] and item["right_longer"]):
            raise ShapeProfileError(f"asymmetry.{name} direction flags are invalid")
        _unit(item["confidence"], f"asymmetry.{name}.confidence")
    evidence = profile.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ShapeProfileError("evidence must be an object")
    if evidence.get("source_video_required_at_runtime") is not False:
        raise ShapeProfileError("runtime must not require source video")
    for field in ("tracking_sha256", "source_sha256"):
        digest = evidence.get(field)
        if not isinstance(digest, str) or len(digest) != 64:
            raise ShapeProfileError(f"evidence.{field} must be SHA-256")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ShapeProfileError(f"evidence.{field} must be SHA-256") from exc
    backend = evidence.get("backend")
    builder = evidence.get("builder")
    if not isinstance(backend, Mapping) or not all(isinstance(backend.get(key), str) and backend[key] for key in ("id", "version", "model_revision")):
        raise ShapeProfileError("backend provenance is invalid")
    if not isinstance(builder, Mapping) or builder.get("id") != BUILDER_ID or builder.get("version") != BUILDER_VERSION:
        raise ShapeProfileError("builder provenance is invalid")
    recommendations = profile.get("recommendations")
    if not isinstance(recommendations, list) or not all(isinstance(item, str) and item for item in recommendations):
        raise ShapeProfileError("recommendations must be an array of strings")
    if profile.get("id") != _content_id(profile):
        raise ShapeProfileError("shape profile id does not match content")


def canonical_shape_json(profile: Mapping[str, Any]) -> str:
    validate_shape_profile(profile)
    return json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
