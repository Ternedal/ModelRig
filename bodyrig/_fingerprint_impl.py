"""Deterministic BodyRig M1.2 motion fingerprint and bodyprint builder.

The builder consumes the normalized, renderer-neutral M1.1 tracking timeline and
produces a compact package that captures movement style plus replayable gesture
candidates. Source video is never embedded and the extraction backend remains
provenance only; runtime consumers depend only on the stable package shape.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

from .bodyprint import BodyprintValidationError, validate_manifest
from .tracking import COORDINATE_SPACE, SCHEMA as TRACKING_SCHEMA, canonical_tracking_json

BUNDLE_SCHEMA = "bodyrig.bodyprint.bundle/v0.1"
FINGERPRINT_SCHEMA = "bodyrig.motion_fingerprint/v1"
FEATURE_SPACE = "torso_centered_scale_normalized/v1"
BUILDER_ID = "modelrig.bodyrig.motion_fingerprint"
BUILDER_VERSION = "0.1.0"
DEFAULT_CREATED_AT = "1970-01-01T00:00:00+00:00"


class FingerprintError(ValueError):
    """Tracking input or generated bodyprint package violates the M1.2 contract."""


@dataclass(frozen=True)
class FingerprintConfig:
    """Versioned, deterministic thresholds used by the M1.2 builder."""

    gesture_speed_threshold: float = 1.0
    gesture_max_gap_us: int = 180_000
    min_gesture_duration_us: int = 100_000
    min_point_confidence: float = 0.2
    created_at: str = DEFAULT_CREATED_AT

    def to_dict(self) -> dict[str, Any]:
        speed = _finite(self.gesture_speed_threshold, "config.gesture_speed_threshold")
        if not 0.05 <= speed <= 20.0:
            raise FingerprintError("config.gesture_speed_threshold must be within [0.05,20]")
        if type(self.gesture_max_gap_us) is not int or not 0 <= self.gesture_max_gap_us <= 5_000_000:
            raise FingerprintError("config.gesture_max_gap_us must be an integer within [0,5000000]")
        if type(self.min_gesture_duration_us) is not int or not 0 <= self.min_gesture_duration_us <= 30_000_000:
            raise FingerprintError(
                "config.min_gesture_duration_us must be an integer within [0,30000000]"
            )
        confidence = _unit(self.min_point_confidence, "config.min_point_confidence")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise FingerprintError("config.created_at must be a non-empty ISO-8601 string")
        # Reuse the manifest validator for the timestamp grammar without adding a dependency.
        probe = {
            "format": "bodyrig.bodyprint",
            "version": "0.1.0",
            "id": "timestamp-probe",
            "created_at": self.created_at,
            "capabilities": [],
            "confidence": {
                "appearance": 0.0,
                "body_shape": 0.0,
                "motion": 0.0,
                "face_behavior": 0.0,
                "hands": 0.0,
                "gaze": 0.0,
            },
        }
        try:
            validate_manifest(probe)
        except BodyprintValidationError as exc:
            raise FingerprintError(str(exc)) from exc
        return {
            "gesture_speed_threshold": _round(speed),
            "gesture_max_gap_us": self.gesture_max_gap_us,
            "min_gesture_duration_us": self.min_gesture_duration_us,
            "min_point_confidence": _round(confidence),
            "created_at": self.created_at,
        }


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FingerprintError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise FingerprintError(f"{label} must be finite")
    return number


def _unit(value: Any, label: str) -> float:
    number = _finite(value, label)
    if not 0.0 <= number <= 1.0:
        raise FingerprintError(f"{label} must be within [0,1]")
    return number


def _round(value: float) -> float:
    return round(float(value), 6)


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b)))


def _point(raw: Mapping[str, Any], label: str) -> tuple[float, float, float, float]:
    if not isinstance(raw, Mapping):
        raise FingerprintError(f"{label} must be an object")
    x = _unit(raw.get("x"), f"{label}.x")
    y = _unit(raw.get("y"), f"{label}.y")
    z = _finite(raw.get("z"), f"{label}.z")
    if not -4.0 <= z <= 4.0:
        raise FingerprintError(f"{label}.z must be within [-4,4]")
    confidence = _unit(raw.get("confidence"), f"{label}.confidence")
    return x, y, z, confidence


def _points(raw: Any, label: str) -> dict[str, tuple[float, float, float, float]] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or not raw:
        raise FingerprintError(f"{label} must be a non-empty object or null")
    result: dict[str, tuple[float, float, float, float]] = {}
    for name in sorted(raw):
        if not isinstance(name, str) or not name:
            raise FingerprintError(f"{label} point ids must be non-empty strings")
        result[name] = _point(raw[name], f"{label}.{name}")
    return result


def _coverage(payload: Mapping[str, Any], subsystem: str) -> tuple[float, float]:
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        raise FingerprintError("tracking.coverage must be an object")
    item = coverage.get(subsystem)
    if not isinstance(item, Mapping):
        raise FingerprintError(f"tracking.coverage.{subsystem} must be an object")
    return (
        _unit(item.get("coverage"), f"tracking.coverage.{subsystem}.coverage"),
        _unit(item.get("mean_confidence"), f"tracking.coverage.{subsystem}.mean_confidence"),
    )


def _validate_tracking(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise FingerprintError("tracking payload must be an object")
    if payload.get("schema") != TRACKING_SCHEMA:
        raise FingerprintError(f"tracking schema must be {TRACKING_SCHEMA}")
    if payload.get("coordinate_space") != COORDINATE_SPACE:
        raise FingerprintError(f"tracking coordinate_space must be {COORDINATE_SPACE}")
    if payload.get("production_activation") is not False:
        raise FingerprintError("tracking production_activation must remain false")
    source = payload.get("source")
    backend = payload.get("backend")
    if not isinstance(source, Mapping) or not isinstance(source.get("sha256"), str):
        raise FingerprintError("tracking source provenance is required")
    if len(source["sha256"]) != 64:
        raise FingerprintError("tracking source.sha256 must contain a SHA-256 hex digest")
    try:
        int(source["sha256"], 16)
    except ValueError as exc:
        raise FingerprintError("tracking source.sha256 must contain a SHA-256 hex digest") from exc
    if not isinstance(backend, Mapping):
        raise FingerprintError("tracking backend provenance is required")
    for key in ("id", "version", "model_revision"):
        if not isinstance(backend.get(key), str) or not backend[key]:
            raise FingerprintError(f"tracking backend.{key} is required")
    for subsystem in ("body", "hands", "face"):
        _coverage(payload, subsystem)

    frames = payload.get("frames")
    if not isinstance(frames, list):
        raise FingerprintError("tracking.frames must be an array")
    result: list[dict[str, Any]] = []
    previous = -1
    for index, raw in enumerate(frames):
        if not isinstance(raw, Mapping):
            raise FingerprintError(f"tracking.frames[{index}] must be an object")
        timestamp = raw.get("timestamp_us")
        if type(timestamp) is not int or timestamp < 0 or timestamp <= previous:
            raise FingerprintError("tracking frame timestamps must be strictly increasing")
        previous = timestamp
        expressions = raw.get("expressions")
        if expressions is not None:
            if not isinstance(expressions, Mapping) or not expressions:
                raise FingerprintError("tracking expressions must be non-empty or null")
            expressions = {
                str(key): _unit(value, f"tracking.frames[{index}].expressions.{key}")
                for key, value in sorted(expressions.items())
            }
        result.append(
            {
                "timestamp_us": timestamp,
                "body": _points(raw.get("body"), f"tracking.frames[{index}].body"),
                "left_hand": _points(
                    raw.get("left_hand"), f"tracking.frames[{index}].left_hand"
                ),
                "right_hand": _points(
                    raw.get("right_hand"), f"tracking.frames[{index}].right_hand"
                ),
                "face": _points(raw.get("face"), f"tracking.frames[{index}].face"),
                "expressions": expressions,
            }
        )
    # M1.1 owns canonical serialization; invoking it here binds M1.2 to that schema
    # without depending on a concrete extraction engine.
    try:
        canonical_tracking_json(payload)
    except Exception as exc:
        raise FingerprintError(str(exc)) from exc
    return result


def _midpoint(
    points: Mapping[str, tuple[float, float, float, float]], left: str, right: str
) -> tuple[float, float, float] | None:
    a, b = points.get(left), points.get(right)
    if a is None or b is None:
        return None
    return tuple((a[index] + b[index]) / 2.0 for index in range(3))


def _torso_frame(
    body: Mapping[str, tuple[float, float, float, float]]
) -> tuple[tuple[float, float, float], float] | None:
    hip = _midpoint(body, "left_hip", "right_hip")
    shoulders = _midpoint(body, "left_shoulder", "right_shoulder")
    center = hip or shoulders
    if center is None:
        usable = [(p[0], p[1], p[2]) for p in body.values()]
        if not usable:
            return None
        center = tuple(sum(point[index] for point in usable) / len(usable) for index in range(3))

    pairs = (
        ("left_shoulder", "right_shoulder"),
        ("left_hip", "right_hip"),
    )
    scale = 0.0
    for left, right in pairs:
        if left in body and right in body:
            scale = max(scale, _distance(body[left][:3], body[right][:3]))
    if scale <= 1e-6:
        planar = [(point[0], point[1]) for point in body.values()]
        if planar:
            span_x = max(x for x, _ in planar) - min(x for x, _ in planar)
            span_y = max(y for _, y in planar) - min(y for _, y in planar)
            scale = max(span_x, span_y)
    if scale <= 1e-6:
        return None
    return center, scale


def _normalize_points(
    values: Mapping[str, tuple[float, float, float, float]] | None,
    *,
    center: tuple[float, float, float],
    scale: float,
) -> dict[str, dict[str, float]] | None:
    if values is None:
        return None
    return {
        name: {
            "x": _round((point[0] - center[0]) / scale),
            "y": _round((point[1] - center[1]) / scale),
            "z": _round((point[2] - center[2]) / scale),
            "confidence": _round(point[3]),
        }
        for name, point in sorted(values.items())
    }


def _normalized_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for frame in frames:
        body = frame["body"]
        if body is None:
            continue
        torso = _torso_frame(body)
        if torso is None:
            continue
        center, scale = torso
        result.append(
            {
                "timestamp_us": frame["timestamp_us"],
                "scale": _round(scale),
                "body": _normalize_points(body, center=center, scale=scale),
                "left_hand": _normalize_points(frame["left_hand"], center=center, scale=scale),
                "right_hand": _normalize_points(frame["right_hand"], center=center, scale=scale),
                "face": _normalize_points(frame["face"], center=center, scale=scale),
                "expressions": frame["expressions"],
            }
        )
    return result


def _series_speed(
    frames: list[dict[str, Any]],
    *,
    subsystem: str,
    point_id: str,
    min_confidence: float,
) -> list[tuple[int, float, float]]:
    result: list[tuple[int, float, float]] = []
    previous: tuple[int, tuple[float, float, float], float] | None = None
    for frame in frames:
        points = frame.get(subsystem)
        point = points.get(point_id) if isinstance(points, Mapping) else None
        if not isinstance(point, Mapping) or point["confidence"] < min_confidence:
            previous = None
            continue
        current = (point["x"], point["y"], point["z"])
        if previous is not None:
            elapsed = (frame["timestamp_us"] - previous[0]) / 1_000_000.0
            if elapsed > 0:
                speed = _distance(current, previous[1]) / elapsed
                result.append((frame["timestamp_us"], speed, min(point["confidence"], previous[2])))
        previous = (frame["timestamp_us"], current, point["confidence"])
    return result


def _mean(values: list[float]) -> float:
    return _round(sum(values) / len(values)) if values else 0.0


def _posture_lean(frames: list[dict[str, Any]], min_confidence: float) -> float:
    values: list[float] = []
    for frame in frames:
        body = frame["body"]
        required = [body.get(name) for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")]
        if any(point is None or point["confidence"] < min_confidence for point in required):
            continue
        shoulder_x = (required[0]["x"] + required[1]["x"]) / 2.0
        hip_x = (required[2]["x"] + required[3]["x"]) / 2.0
        values.append(shoulder_x - hip_x)
    return _mean(values)


def _gesture_range(frames: list[dict[str, Any]], min_confidence: float) -> float:
    distances: list[float] = []
    for frame in frames:
        body = frame["body"]
        shoulder = {
            side: body.get(f"{side}_shoulder") for side in ("left", "right")
        }
        wrist = {side: body.get(f"{side}_wrist") for side in ("left", "right")}
        for side in ("left", "right"):
            a, b = shoulder[side], wrist[side]
            if a is None or b is None or min(a["confidence"], b["confidence"]) < min_confidence:
                continue
            distances.append(_distance((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"])))
    return _mean(distances)


def _arm_sample(frame: Mapping[str, Any], side: str) -> dict[str, Any] | None:
    body = frame.get("body")
    if not isinstance(body, Mapping):
        return None
    sample: dict[str, Any] = {"timestamp_us": frame["timestamp_us"], "points": {}}
    for joint in ("shoulder", "elbow", "wrist"):
        point = body.get(f"{side}_{joint}")
        if point is not None:
            sample["points"][joint] = dict(point)
    return sample if "wrist" in sample["points"] else None


def _gesture_digest_payload(
    side: str, start_us: int, end_us: int, trajectory: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "side": side,
        "start_us": start_us,
        "end_us": end_us,
        "trajectory": trajectory,
    }


def _gesture_id(
    side: str, start_us: int, end_us: int, trajectory: list[dict[str, Any]]
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            _gesture_digest_payload(side, start_us, end_us, trajectory),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"gesture-{digest[:16]}"


def _segment_gestures(frames: list[dict[str, Any]], config: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    threshold = config["gesture_speed_threshold"]
    confidence_floor = config["min_point_confidence"]
    for side in ("left", "right"):
        speeds = _series_speed(
            frames,
            subsystem="body",
            point_id=f"{side}_wrist",
            min_confidence=confidence_floor,
        )
        active_times = [timestamp for timestamp, speed, _ in speeds if speed >= threshold]
        if not active_times:
            continue
        groups: list[list[int]] = [[active_times[0]]]
        for timestamp in active_times[1:]:
            if timestamp - groups[-1][-1] <= config["gesture_max_gap_us"]:
                groups[-1].append(timestamp)
            else:
                groups.append([timestamp])
        for group in groups:
            end_us = group[-1]
            prior = [frame["timestamp_us"] for frame in frames if frame["timestamp_us"] < group[0]]
            start_us = prior[-1] if prior else group[0]
            if end_us - start_us < config["min_gesture_duration_us"]:
                continue
            trajectory = [
                sample
                for frame in frames
                if start_us <= frame["timestamp_us"] <= end_us
                for sample in [_arm_sample(frame, side)]
                if sample is not None
            ]
            if len(trajectory) < 2:
                continue
            confidences = [
                sample["points"]["wrist"]["confidence"]
                for sample in trajectory
            ]
            candidates.append(
                {
                    "id": _gesture_id(side, start_us, end_us, trajectory),
                    "side": side,
                    "start_us": start_us,
                    "end_us": end_us,
                    "duration_us": end_us - start_us,
                    "confidence": _mean(confidences),
                    "trajectory_space": FEATURE_SPACE,
                    "trajectory": trajectory,
                }
            )
    return sorted(candidates, key=lambda item: (item["start_us"], item["side"], item["id"]))


def _confidence(payload: Mapping[str, Any], subsystem: str) -> float:
    coverage, mean_confidence = _coverage(payload, subsystem)
    return _round(coverage * mean_confidence)


def _bodyprint_content_hash(
    motion_profile: Mapping[str, Any],
    gestures: list[dict[str, Any]],
    provenance: Mapping[str, Any],
) -> str:
    core = {
        "motion_profile": motion_profile,
        "gestures": gestures,
        "provenance": provenance,
    }
    return hashlib.sha256(
        json.dumps(
            core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _build_profile(
    payload: Mapping[str, Any], frames: list[dict[str, Any]], gestures: list[dict[str, Any]], config: Mapping[str, Any]
) -> dict[str, Any]:
    min_confidence = config["min_point_confidence"]
    wrist_speeds = [
        speed
        for side in ("left", "right")
        for _timestamp, speed, _confidence in _series_speed(
            frames,
            subsystem="body",
            point_id=f"{side}_wrist",
            min_confidence=min_confidence,
        )
    ]
    head_speeds = [
        speed
        for _timestamp, speed, _confidence in _series_speed(
            frames, subsystem="body", point_id="nose", min_confidence=min_confidence
        )
    ]
    gaze_proxy_speeds = [
        speed
        for _timestamp, speed, _confidence in _series_speed(
            frames, subsystem="face", point_id="nose_tip", min_confidence=min_confidence
        )
    ]
    if len(frames) >= 2:
        duration_min = max((frames[-1]["timestamp_us"] - frames[0]["timestamp_us"]) / 60_000_000.0, 1e-9)
    else:
        duration_min = 0.0
    side_counts = {
        side: sum(1 for gesture in gestures if gesture["side"] == side)
        for side in ("left", "right")
    }
    dominant_side = "balanced"
    if side_counts["left"] > side_counts["right"]:
        dominant_side = "left"
    elif side_counts["right"] > side_counts["left"]:
        dominant_side = "right"
    body_coverage, _ = _coverage(payload, "body")
    return {
        "schema": FINGERPRINT_SCHEMA,
        "feature_space": FEATURE_SPACE,
        "metrics": {
            "gesture_frequency_per_minute": _round(len(gestures) / duration_min) if duration_min else 0.0,
            "gesture_range": _gesture_range(frames, min_confidence),
            "hand_activity_per_second": _mean(wrist_speeds),
            "head_activity_per_second": _mean(head_speeds),
            "gaze_proxy_activity_per_second": _mean(gaze_proxy_speeds),
            "posture_lean_x": _posture_lean(frames, min_confidence),
        },
        "priors": {
            "gesture_count": len(gestures),
            "dominant_side": dominant_side,
            "body_tracking_coverage": _round(body_coverage),
            "gaze_proxy": "face.nose_tip_relative_to_torso",
        },
    }


def build_bodyprint(
    tracking: Mapping[str, Any], *, config: FingerprintConfig | None = None
) -> dict[str, Any]:
    """Build one content-addressed, deterministic bodyprint package from M1.1 tracks."""
    raw_frames = _validate_tracking(tracking)
    resolved_config = (config or FingerprintConfig()).to_dict()
    frames = _normalized_frames(raw_frames)
    if not frames:
        raise FingerprintError("tracking contains no usable torso-normalizable body frames")
    gestures = _segment_gestures(frames, resolved_config)
    profile = _build_profile(tracking, frames, gestures, resolved_config)

    tracking_json = canonical_tracking_json(tracking)
    tracking_sha = hashlib.sha256(tracking_json.encode("utf-8")).hexdigest()
    source = tracking["source"]
    backend = tracking["backend"]
    provenance = {
        "tracking_schema": TRACKING_SCHEMA,
        "tracking_sha256": tracking_sha,
        "source_sha256": source["sha256"],
        "backend": {
            "id": backend["id"],
            "version": backend["version"],
            "model_revision": backend["model_revision"],
        },
        "builder": {
            "id": BUILDER_ID,
            "version": BUILDER_VERSION,
            "config": resolved_config,
        },
        "source_video_required_at_runtime": False,
    }
    content_hash = _bodyprint_content_hash(profile, gestures, provenance)

    capabilities = ["motion_style"]
    if gestures:
        capabilities.append("gestures")
    face_confidence = _confidence(tracking, "face")
    if face_confidence > 0.0:
        capabilities.extend(["face_behavior", "gaze"])
    manifest = {
        "format": "bodyrig.bodyprint",
        "version": "0.1.0",
        "id": f"bodyprint-{content_hash[:24]}",
        "created_at": resolved_config["created_at"],
        "capabilities": capabilities,
        "confidence": {
            "appearance": 0.0,
            "body_shape": 0.0,
            "motion": _confidence(tracking, "body"),
            "face_behavior": face_confidence,
            "hands": _confidence(tracking, "hands"),
            "gaze": face_confidence,
        },
    }
    package = {
        "schema": BUNDLE_SCHEMA,
        "manifest": manifest,
        "motion_profile": profile,
        "gestures": gestures,
        "provenance": provenance,
        "production_activation": False,
    }
    validate_bodyprint_package(package)
    return package


def gesture_intent(candidate: Mapping[str, Any]) -> str:
    """Return the renderer-neutral runtime intent for one validated candidate."""
    if not isinstance(candidate, Mapping):
        raise FingerprintError("gesture candidate must be an object")
    gesture_id = candidate.get("id")
    if not isinstance(gesture_id, str) or not gesture_id.startswith("gesture-"):
        raise FingerprintError("gesture candidate id is invalid")
    return f"bodyprint:{gesture_id}"


def validate_bodyprint_package(package: Mapping[str, Any]) -> None:
    if not isinstance(package, Mapping):
        raise FingerprintError("bodyprint package must be an object")
    expected = {
        "schema",
        "manifest",
        "motion_profile",
        "gestures",
        "provenance",
        "production_activation",
    }
    if set(package) != expected:
        raise FingerprintError("bodyprint package contains missing or unsupported top-level fields")
    if package.get("schema") != BUNDLE_SCHEMA:
        raise FingerprintError(f"bodyprint package schema must be {BUNDLE_SCHEMA}")
    if package.get("production_activation") is not False:
        raise FingerprintError("bodyprint production_activation must remain false")
    manifest = package.get("manifest")
    if not isinstance(manifest, Mapping):
        raise FingerprintError("bodyprint manifest must be an object")
    try:
        validate_manifest(manifest)
    except BodyprintValidationError as exc:
        raise FingerprintError(str(exc)) from exc

    profile = package.get("motion_profile")
    if not isinstance(profile, Mapping) or profile.get("schema") != FINGERPRINT_SCHEMA:
        raise FingerprintError(f"motion_profile.schema must be {FINGERPRINT_SCHEMA}")
    if profile.get("feature_space") != FEATURE_SPACE:
        raise FingerprintError(f"motion_profile.feature_space must be {FEATURE_SPACE}")
    metrics = profile.get("metrics")
    if not isinstance(metrics, Mapping):
        raise FingerprintError("motion_profile.metrics must be an object")
    expected_metrics = {
        "gesture_frequency_per_minute",
        "gesture_range",
        "hand_activity_per_second",
        "head_activity_per_second",
        "gaze_proxy_activity_per_second",
        "posture_lean_x",
    }
    if set(metrics) != expected_metrics:
        raise FingerprintError("motion_profile.metrics fields are invalid")
    for key in expected_metrics:
        value = _finite(metrics[key], f"motion_profile.metrics.{key}")
        if key == "posture_lean_x":
            if not -10.0 <= value <= 10.0:
                raise FingerprintError("motion_profile.metrics.posture_lean_x is out of range")
        elif not 0.0 <= value <= 1_000.0:
            raise FingerprintError(f"motion_profile.metrics.{key} is out of range")

    gestures = package.get("gestures")
    if not isinstance(gestures, list):
        raise FingerprintError("gestures must be an array")
    seen: set[str] = set()
    for index, gesture in enumerate(gestures):
        if not isinstance(gesture, Mapping):
            raise FingerprintError(f"gestures[{index}] must be an object")
        gesture_id = gesture.get("id")
        if not isinstance(gesture_id, str) or not gesture_id.startswith("gesture-"):
            raise FingerprintError(f"gestures[{index}].id is invalid")
        if gesture_id in seen:
            raise FingerprintError("gesture ids must be unique")
        seen.add(gesture_id)
        side = gesture.get("side")
        if side not in {"left", "right"}:
            raise FingerprintError(f"gestures[{index}].side is invalid")
        for field in ("start_us", "end_us", "duration_us"):
            if type(gesture.get(field)) is not int or gesture[field] < 0:
                raise FingerprintError(f"gestures[{index}].{field} must be non-negative integer")
        start_us = gesture["start_us"]
        end_us = gesture["end_us"]
        if end_us < start_us or gesture["duration_us"] != end_us - start_us:
            raise FingerprintError(f"gestures[{index}] timing is inconsistent")
        _unit(gesture.get("confidence"), f"gestures[{index}].confidence")
        if gesture.get("trajectory_space") != FEATURE_SPACE:
            raise FingerprintError(f"gestures[{index}].trajectory_space is invalid")
        trajectory = gesture.get("trajectory")
        if not isinstance(trajectory, list) or len(trajectory) < 2:
            raise FingerprintError(f"gestures[{index}].trajectory must contain at least two samples")
        last_timestamp = -1
        for sample_index, sample in enumerate(trajectory):
            if not isinstance(sample, Mapping) or type(sample.get("timestamp_us")) is not int:
                raise FingerprintError(f"gestures[{index}].trajectory[{sample_index}] is invalid")
            if sample["timestamp_us"] <= last_timestamp:
                raise FingerprintError(f"gestures[{index}] trajectory timestamps must increase")
            last_timestamp = sample["timestamp_us"]
            points = sample.get("points")
            if not isinstance(points, Mapping) or "wrist" not in points:
                raise FingerprintError(f"gestures[{index}] trajectory requires wrist points")
            for name, point in points.items():
                if name not in {"shoulder", "elbow", "wrist"} or not isinstance(point, Mapping):
                    raise FingerprintError(f"gestures[{index}] trajectory contains invalid arm points")
                for axis in ("x", "y", "z"):
                    value = _finite(point.get(axis), f"gestures[{index}].trajectory.{name}.{axis}")
                    if not -20.0 <= value <= 20.0:
                        raise FingerprintError(f"gestures[{index}] trajectory coordinate is out of range")
                _unit(point.get("confidence"), f"gestures[{index}].trajectory.{name}.confidence")
        if gesture_id != _gesture_id(side, start_us, end_us, trajectory):
            raise FingerprintError(f"gestures[{index}].id does not match gesture content")

    provenance = package.get("provenance")
    if not isinstance(provenance, Mapping):
        raise FingerprintError("provenance must be an object")
    if provenance.get("tracking_schema") != TRACKING_SCHEMA:
        raise FingerprintError("provenance tracking_schema is invalid")
    if provenance.get("source_video_required_at_runtime") is not False:
        raise FingerprintError("runtime must not require source video")
    builder = provenance.get("builder")
    if not isinstance(builder, Mapping) or builder.get("id") != BUILDER_ID or builder.get("version") != BUILDER_VERSION:
        raise FingerprintError("builder provenance is invalid")

    expected_id = f"bodyprint-{_bodyprint_content_hash(profile, gestures, provenance)[:24]}"
    if manifest.get("id") != expected_id:
        raise FingerprintError("manifest.id does not match bodyprint content")


def canonical_bodyprint_json(package: Mapping[str, Any]) -> str:
    validate_bodyprint_package(package)
    return json.dumps(
        package,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
