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
import stat
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
    return round(float(value), 6)


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float
    confidence: float | None

    def normalized(self) -> "Landmark":
        x = _unit(self.x, "landmark.x")
        y = _unit(self.y, "landmark.y")
        z = _finite(self.z, "landmark.z")
        if not -4.0 <= z <= 4.0:
            raise TrackingContractError("landmark.z must be within [-4,4]")
        confidence = None
        if self.confidence is not None:
            confidence = _round(_unit(self.confidence, "landmark.confidence"))
        return Landmark(_round(x), _round(y), _round(z), confidence)

    def to_dict(self) -> dict:
        item = self.normalized()
        return {"x": item.x, "y": item.y, "z": item.z, "confidence": item.confidence}


@dataclass(frozen=True)
class BackendFrame:
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


@dataclass(frozen=True)
class _SourceSnapshot:
    sha256: str
    size: int
    device: int
    inode: int
    mtime_ns: int


class TrackingBackend(Protocol):
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
    values = [
        item["confidence"]
        for item in points.values()
        if item.get("confidence") is not None
    ]
    if not values:
        return None
    return _round(sum(values) / len(values))


def _observation_state(frame: dict, subsystem: str) -> tuple[bool, float | None]:
    if subsystem == "hands":
        left = _mean_confidence(frame.get("left_hand"))
        right = _mean_confidence(frame.get("right_hand"))
        values = [value for value in (left, right) if value is not None]
        observed = frame.get("left_hand") is not None or frame.get("right_hand") is not None
        confidence = _round(sum(values) / len(values)) if values else None
        return observed, confidence
    if subsystem == "face":
        observed = frame.get("face") is not None or frame.get("expressions") is not None
        return observed, _mean_confidence(frame.get("face"))
    points = frame.get(subsystem)
    return points is not None, _mean_confidence(points)


def _coverage(total_frames: int, states: list[tuple[bool, float | None]]) -> dict:
    observed = sum(1 for present, _confidence in states if present)
    confidences = [confidence for _present, confidence in states if confidence is not None]
    return {
        "observed_frames": observed,
        "total_frames": total_frames,
        "coverage": _round(observed / total_frames) if total_frames else 0.0,
        "confidence_frames": len(confidences),
        "mean_confidence": _round(sum(confidences) / len(confidences)) if confidences else 0.0,
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


def _capture_source(path: Path) -> _SourceSnapshot:
    """Hash one stable regular file and bind the digest to its file identity."""
    try:
        path_before = os.lstat(path)
    except OSError as exc:
        raise TrackingContractError(f"source cannot be inspected: {type(exc).__name__}") from exc
    if stat.S_ISLNK(path_before.st_mode) or not stat.S_ISREG(path_before.st_mode):
        raise TrackingContractError("source_path must name a non-symlink regular file")

    digest = hashlib.sha256()
    total = 0
    try:
        with open(path, "rb") as handle:
            opened_before = os.fstat(handle.fileno())
            if (opened_before.st_dev, opened_before.st_ino) != (path_before.st_dev, path_before.st_ino):
                raise TrackingContractError("source identity changed before hashing")
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                digest.update(block)
            opened_after = os.fstat(handle.fileno())
    except TrackingContractError:
        raise
    except OSError as exc:
        raise TrackingContractError(f"source cannot be hashed: {type(exc).__name__}") from exc

    try:
        path_after = os.lstat(path)
    except OSError as exc:
        raise TrackingContractError("source disappeared while hashing") from exc

    identity_before = (
        opened_before.st_dev,
        opened_before.st_ino,
        opened_before.st_size,
        opened_before.st_mtime_ns,
    )
    identity_after = (
        opened_after.st_dev,
        opened_after.st_ino,
        opened_after.st_size,
        opened_after.st_mtime_ns,
    )
    path_identity = (
        path_after.st_dev,
        path_after.st_ino,
        path_after.st_size,
        path_after.st_mtime_ns,
    )
    if identity_before != identity_after or identity_after != path_identity or total != opened_after.st_size:
        raise TrackingContractError("source changed while hashing")
    return _SourceSnapshot(
        sha256=digest.hexdigest(),
        size=total,
        device=int(opened_after.st_dev),
        inode=int(opened_after.st_ino),
        mtime_ns=int(opened_after.st_mtime_ns),
    )


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
    """Inspect/extract one immutable source into deterministic tracking v1."""
    if not isinstance(permission_assertion, str) or not permission_assertion.strip():
        raise TrackingContractError("permission_assertion is required")
    if len(permission_assertion) > 256:
        raise TrackingContractError("permission_assertion is too long")

    path = Path(source_path)
    source_before = _capture_source(path)
    media = backend.inspect(path).to_dict()
    identity = _backend_identity(backend)

    normalized: list[dict] = []
    coverage_states: dict[str, list[tuple[bool, float | None]]] = {
        "body": [], "hands": [], "face": [],
    }
    attempted_frames = 0
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
        attempted_frames += 1

        body = _validate_landmarks(raw.body, allowed=_BODY_IDS, subsystem="body")
        left = _validate_landmarks(raw.left_hand, allowed=_HAND_IDS, subsystem="left_hand")
        right = _validate_landmarks(raw.right_hand, allowed=_HAND_IDS, subsystem="right_hand")
        face = _validate_landmarks(raw.face, allowed=_FACE_IDS, subsystem="face")
        expressions = _validate_expressions(raw.expressions)
        frame = {
            "timestamp_us": raw.timestamp_us,
            "body": body,
            "left_hand": left,
            "right_hand": right,
            "face": face,
            "expressions": expressions,
        }
        for subsystem in coverage_states:
            coverage_states[subsystem].append(_observation_state(frame, subsystem))
        if all(value is None for value in (body, left, right, face, expressions)):
            continue
        normalized.append(frame)

    source_after = _capture_source(path)
    if source_after != source_before:
        raise TrackingContractError(
            "source changed during extraction; tracking provenance is invalid"
        )

    coverage = {
        subsystem: _coverage(attempted_frames, states)
        for subsystem, states in coverage_states.items()
    }
    payload = {
        "schema": SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": source_before.sha256,
            "bytes": source_before.size,
            "permission_assertion": permission_assertion.strip(),
            "media": media,
        },
        "backend": identity,
        "frames": normalized,
        "coverage": coverage,
        "recommendations": _recommendations(coverage),
        "production_activation": False,
    }
    canonical_tracking_json(payload)
    return payload


def canonical_tracking_json(payload: Mapping) -> str:
    if not isinstance(payload, Mapping):
        raise TrackingContractError("tracking payload must be an object")
    if payload.get("schema") != SCHEMA:
        raise TrackingContractError(f"tracking schema must be {SCHEMA}")
    if payload.get("production_activation") is not False:
        raise TrackingContractError("production_activation must remain false")
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )