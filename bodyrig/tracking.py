"""BodyRig M1.1 renderer/extractor-neutral tracking contract.

This module owns the stable output of video analysis, not a particular ML
engine. A backend may use MediaPipe, 4D-Humans/PHALP, another local model, or a
future service, but it must map its native values into these types before they
become BodyRig data.

Source media is immutable input. Serialized provenance contains a SHA-256 and
media facts, never the source path or raw frames. Missing observations stay
missing; the normalizer does not interpolate detection loss into invented data.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol

SCHEMA = "bodyrig.tracking/v1"
COORDINATE_SPACE = "image_normalized_right_down_depth_relative/v1"

_BODY_IDS = frozenset({
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
    "left_heel", "right_heel", "left_foot_index", "right_foot_index",
})
_HAND_IDS = frozenset({
    "wrist", "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "pinky_mcp", "pinky_pip", "pinky_dip", "pinky_tip",
})
_FACE_IDS = frozenset({
    "nose_tip", "chin", "mouth_left", "mouth_right", "upper_lip", "lower_lip",
    "left_eye_inner", "left_eye_outer", "right_eye_inner", "right_eye_outer",
    "left_brow_inner", "left_brow_outer", "right_brow_inner", "right_brow_outer",
})
_EXPRESSION_IDS = frozenset({
    "blink_left", "blink_right", "jaw_open", "mouth_smile_left",
    "mouth_smile_right", "mouth_frown_left", "mouth_frown_right",
    "brow_inner_up", "brow_down_left", "brow_down_right",
})


class TrackingContractError(ValueError):
    """Backend output or tracking metadata violates the stable M1.1 contract."""


def _finite(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrackingContractError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise TrackingContractError(f"{label} must be finite")
    return value


def _unit(value: float, label: str) -> float:
    value = _finite(value, label)
    if not 0.0 <= value <= 1.0:
        raise TrackingContractError(f"{label} must be within [0,1]")
    return value


def _round(value: float) -> float:
    # Contract precision. This makes engine jitter below 1e-6 irrelevant to
    # serialized determinism while preserving far more precision than tracking
    # quality warrants.
    return round(float(value), 6)


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float
    confidence: float

    def normalized(self) -> "Landmark":
        x = _unit(self.x, "landmark.x")
        y = _unit(self.y, "landmark.y")
        z = _finite(self.z, "landmark.z")
        if not -4.0 <= z <= 4.0:
            raise TrackingContractError("landmark.z must be within [-4,4]")
        confidence = _unit(self.confidence, "landmark.confidence")
        return Landmark(_round(x), _round(y), _round(z), _round(confidence))

    def to_dict(self) -> dict:
        item = self.normalized()
        return {
            "x": item.x,
            "y": item.y,
            "z": item.z,
            "confidence": item.confidence,
        }


@dataclass(frozen=True)
class BackendFrame:
    """Engine-neutral observation returned by a TrackingBackend.

    ``None`` means the subsystem was not observed on this frame. An empty map
    is invalid: backends must not disguise detection loss as a successful but
    content-free observation.
    """

    timestamp_us: int
    body: Mapping[str, Landmark] | None = None
    left_hand: Mapping[str, Landmark] | None = None
    right_hand: Mapping[str, Landmark] | None = None
    face: Mapping[str, Landmark] | None = None
    expressions: Mapping[str, float] | None = None


@dataclass(frozen=True)
class MediaFacts:
    codec: str
    width: int
    height: int
    duration_us: int
    nominal_fps: float

    def to_dict(self) -> dict:
        if not self.codec or len(self.codec) > 64:
            raise TrackingContractError("media.codec must be non-empty and <=64 chars")
        if type(self.width) is not int or self.width <= 0:
            raise TrackingContractError("media.width must be a positive integer")
        if type(self.height) is not int or self.height <= 0:
            raise TrackingContractError("media.height must be a positive integer")
        if type(self.duration_us) is not int or self.duration_us <= 0:
            raise TrackingContractError("media.duration_us must be positive")
        fps = _finite(self.nominal_fps, "media.nominal_fps")
        if not 0.1 <= fps <= 1000.0:
            raise TrackingContractError("media.nominal_fps out of range")
        return {
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
            "duration_us": self.duration_us,
            "nominal_fps": _round(fps),
        }


class TrackingBackend(Protocol):
    """Replaceable extraction backend boundary.

    Native model/SDK objects must not cross this interface. A backend returns
    MediaFacts and BackendFrame values only.
    """

    backend_id: str
    backend_version: str
    model_revision: str

    def inspect(self, source_path: os.PathLike[str] | str) -> MediaFacts: ...

    def extract(self, source_path: os.PathLike[str] | str) -> Iterable[BackendFrame]: ...


def _validate_landmarks(
    values: Mapping[str, Landmark] | None,
    *,
    allowed: frozenset[str],
    subsystem: str,
) -> dict[str, dict] | None:
    if values is None:
        return None
    if not isinstance(values, Mapping) or not values:
        raise TrackingContractError(f"{subsystem} observation must be non-empty or null")
    unknown = set(values) - allowed
    if unknown:
        raise TrackingContractError(
            f"{subsystem} contains non-canonical landmark ids: {sorted(unknown)}"
        )
    result: dict[str, dict] = {}
    for key in sorted(values):
        value = values[key]
        if not isinstance(value, Landmark):
            raise TrackingContractError(f"{subsystem}.{key} must be Landmark")
        result[key] = value.to_dict()
    return result


def _validate_expressions(values: Mapping[str, float] | None) -> dict[str, float] | None:
    if values is None:
        return None
    if not isinstance(values, Mapping) or not values:
        raise TrackingContractError("expressions observation must be non-empty or null")
    unknown = set(values) - _EXPRESSION_IDS
    if unknown:
        raise TrackingContractError(
            f"expressions contains non-canonical ids: {sorted(unknown)}"
        )
    return {key: _round(_unit(values[key], f"expressions.{key}")) for key in sorted(values)}


def _mean_confidence(points: Mapping[str, dict] | None) -> float | None:
    if not points:
        return None
    return _round(sum(item["confidence"] for item in points.values()) / len(points))


def _subsystem_confidence(frame: dict, subsystem: str) -> float | None:
    if subsystem == "hands":
        values = [
            value for value in (
                _mean_confidence(frame.get("left_hand")),
                _mean_confidence(frame.get("right_hand")),
            )
            if value is not None
        ]
        return _round(sum(values) / len(values)) if values else None
    if subsystem == "face":
        points = _mean_confidence(frame.get("face"))
        expressions = frame.get("expressions")
        expr = None
        if expressions:
            # Expression coefficients are intensities, not detector confidence;
            # their presence proves a face-expression observation exists but is
            # not promoted into a fake confidence value.
            expr = 1.0
        values = [value for value in (points, expr) if value is not None]
        return _round(sum(values) / len(values)) if values else None
    return _mean_confidence(frame.get(subsystem))


def _coverage(frames: list[dict], subsystem: str) -> dict:
    if not frames:
        return {"observed_frames": 0, "total_frames": 0, "coverage": 0.0, "mean_confidence": 0.0}
    confidences = [
        value for frame in frames
        if (value := _subsystem_confidence(frame, subsystem)) is not None
    ]
    observed = len(confidences)
    return {
        "observed_frames": observed,
        "total_frames": len(frames),
        "coverage": _round(observed / len(frames)),
        "mean_confidence": _round(sum(confidences) / observed) if observed else 0.0,
    }


def _recommendations(coverage: dict[str, dict]) -> list[str]:
    result: list[str] = []
    if coverage["body"]["coverage"] < 0.7:
        result.append("need_more_full_body")
    if coverage["hands"]["coverage"] < 0.5:
        result.append("more_visible_hands")
    if coverage["face"]["coverage"] < 0.5:
        result.append("need_clearer_face")
    return result


def _source_sha256(path: os.PathLike[str] | str) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            digest.update(block)
    return digest.hexdigest(), total


def _backend_identity(backend: TrackingBackend) -> dict:
    values = {
        "id": getattr(backend, "backend_id", ""),
        "version": getattr(backend, "backend_version", ""),
        "model_revision": getattr(backend, "model_revision", ""),
    }
    for key, value in values.items():
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise TrackingContractError(f"backend.{key} must be non-empty and <=128 chars")
    return values


def build_tracking_timeline(
    source_path: os.PathLike[str] | str,
    *,
    backend: TrackingBackend,
    permission_assertion: str,
) -> dict:
    """Inspect/extract one source video into deterministic BodyRig tracking v1."""
    if not isinstance(permission_assertion, str) or not permission_assertion.strip():
        raise TrackingContractError("permission_assertion is required")
    if len(permission_assertion) > 256:
        raise TrackingContractError("permission_assertion is too long")

    path = Path(source_path)
    if not path.is_file():
        raise TrackingContractError("source_path must name an existing regular file")

    source_hash, source_bytes = _source_sha256(path)
    media = backend.inspect(path).to_dict()
    identity = _backend_identity(backend)

    normalized: list[dict] = []
    last_timestamp = -1
    for raw in backend.extract(path):
        if not isinstance(raw, BackendFrame):
            raise TrackingContractError("backend.extract must yield BackendFrame values")
        if type(raw.timestamp_us) is not int or raw.timestamp_us < 0:
            raise TrackingContractError("frame timestamp_us must be a non-negative integer")
        if raw.timestamp_us <= last_timestamp:
            raise TrackingContractError("frame timestamps must be strictly increasing")
        if raw.timestamp_us > media["duration_us"]:
            raise TrackingContractError("frame timestamp exceeds media duration")
        last_timestamp = raw.timestamp_us

        body = _validate_landmarks(raw.body, allowed=_BODY_IDS, subsystem="body")
        left = _validate_landmarks(raw.left_hand, allowed=_HAND_IDS, subsystem="left_hand")
        right = _validate_landmarks(raw.right_hand, allowed=_HAND_IDS, subsystem="right_hand")
        face = _validate_landmarks(raw.face, allowed=_FACE_IDS, subsystem="face")
        expressions = _validate_expressions(raw.expressions)
        if all(value is None for value in (body, left, right, face, expressions)):
            # Detection loss is omitted entirely rather than emitted as a fake
            # all-zero person frame. Timestamp gaps therefore preserve truth.
            continue
        normalized.append({
            "timestamp_us": raw.timestamp_us,
            "body": body,
            "left_hand": left,
            "right_hand": right,
            "face": face,
            "expressions": expressions,
        })

    coverage = {
        "body": _coverage(normalized, "body"),
        "hands": _coverage(normalized, "hands"),
        "face": _coverage(normalized, "face"),
    }
    payload = {
        "schema": SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": source_hash,
            "bytes": source_bytes,
            "permission_assertion": permission_assertion.strip(),
            "media": media,
        },
        "backend": identity,
        "frames": normalized,
        "coverage": coverage,
        "recommendations": _recommendations(coverage),
        "production_activation": False,
    }
    # Round-trip through canonical JSON now so non-JSON backend values cannot
    # sneak into what looks like a valid timeline.
    canonical_tracking_json(payload)
    return payload


def canonical_tracking_json(payload: Mapping) -> str:
    if not isinstance(payload, Mapping):
        raise TrackingContractError("tracking payload must be an object")
    if payload.get("schema") != SCHEMA:
        raise TrackingContractError(f"tracking schema must be {SCHEMA}")
    if payload.get("production_activation") is not False:
        raise TrackingContractError("production_activation must remain false")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
