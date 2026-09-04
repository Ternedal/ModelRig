"""BodyRig M2.3 renderer-neutral personalized body-motion mixer.

This layer consumes a validated M1.2 bodyprint package and personalizes only
renderer-neutral motion hints. ModelRig remains semantic authority: the mixer
never invents a gesture when no semantic gesture was requested, and it never
emits bones, clips or renderer animation names.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Mapping

from .fingerprint import canonical_bodyprint_json, validate_bodyprint_package
from .runtime import RuntimeSnapshot


class BodyMotionMixerError(ValueError):
    """Raised when M2.3 body-motion input cannot be mixed safely."""


@dataclass(frozen=True)
class BodyMotionRuntimeFrame:
    """Renderer-neutral personalized body-motion hints for one clock instant."""

    timestamp_ms: int
    profile_id: str | None
    source: str
    head_motion_scale: float
    micro_motion_scale: float
    posture_lean_x: float
    posture_source: str
    gesture_semantic: str | None
    gesture_replay: str | None
    gesture_source: str
    dominant_side: str | None
    gesture_frequency_per_minute: float | None


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BodyMotionMixerError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise BodyMotionMixerError(f"{label} must be finite")
    return number


def _unit(value: Any, label: str) -> float:
    number = _finite(value, label)
    if not 0.0 <= number <= 1.0:
        raise BodyMotionMixerError(f"{label} must be within [0,1]")
    return number


def _round(value: float) -> float:
    return round(float(value), 6)


def _activity_scale(value: float) -> float:
    """Map non-negative source activity onto a conservative runtime gain."""

    value = max(0.0, float(value))
    normalized = value / (1.0 + value)
    return _round(0.55 + 0.90 * normalized)


def _posture_hint(value: float) -> float:
    # M1.2 posture_lean_x is torso-scale relative and validator-bounded to
    # [-10,10]. Runtime keeps only a bounded semantic lean hint.
    return _round(max(-1.0, min(1.0, float(value))))


class BodyMotionMixer:
    """Deterministically personalize body motion from an optional M1.2 package."""

    def __init__(
        self,
        *,
        session_id: str,
        bodyprint_id: str,
        bodyprint_package: Mapping[str, Any] | None = None,
    ) -> None:
        if not session_id or not bodyprint_id:
            raise BodyMotionMixerError("session_id and bodyprint_id are required")

        self._session_id = session_id
        self._bodyprint_id = bodyprint_id
        self._profile_id: str | None = None
        self._source = "generic"
        self._head_motion_scale = 1.0
        self._micro_motion_scale = 1.0
        self._posture_lean_x = 0.0
        self._posture_source = "generic"
        self._dominant_side: str | None = None
        self._gesture_frequency_per_minute: float | None = None
        self._gestures: tuple[Mapping[str, Any], ...] = ()
        self._gesture_ids: frozenset[str] = frozenset()
        self._motion_usable = False
        profile_fingerprint = "generic"

        if bodyprint_package is not None:
            try:
                validate_bodyprint_package(bodyprint_package)
                canonical = canonical_bodyprint_json(bodyprint_package)
            except Exception as exc:
                raise BodyMotionMixerError(str(exc)) from exc

            manifest = bodyprint_package["manifest"]
            package_id = str(manifest["id"])
            if package_id != bodyprint_id:
                raise BodyMotionMixerError("bodyprint package id does not match runtime bodyprint_id")

            self._profile_id = package_id
            profile_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            profile = bodyprint_package["motion_profile"]
            metrics = profile["metrics"]
            priors = profile["priors"]

            motion_confidence = _unit(manifest["confidence"]["motion"], "manifest.confidence.motion")
            body_coverage = _unit(priors["body_tracking_coverage"], "motion_profile.priors.body_tracking_coverage")
            self._motion_usable = motion_confidence >= 0.20 and body_coverage >= 0.20

            if self._motion_usable:
                head_activity = _finite(metrics["head_activity_per_second"], "head_activity_per_second")
                hand_activity = _finite(metrics["hand_activity_per_second"], "hand_activity_per_second")
                gesture_range = _finite(metrics["gesture_range"], "gesture_range")
                posture = _finite(metrics["posture_lean_x"], "posture_lean_x")
                gesture_frequency = _finite(
                    metrics["gesture_frequency_per_minute"], "gesture_frequency_per_minute"
                )

                self._source = "profile"
                self._head_motion_scale = _activity_scale(head_activity)
                combined_micro = max(0.0, hand_activity) * 0.65 + max(0.0, gesture_range) * 0.35
                self._micro_motion_scale = _activity_scale(combined_micro)
                self._posture_lean_x = _posture_hint(posture)
                self._posture_source = "profile"
                self._gesture_frequency_per_minute = _round(gesture_frequency)
                dominant_side = priors["dominant_side"]
                if dominant_side not in {"left", "right", "balanced"}:
                    raise BodyMotionMixerError("motion_profile.priors.dominant_side is invalid")
                self._dominant_side = str(dominant_side)

                gestures = bodyprint_package["gestures"]
                self._gestures = tuple(gestures)
                self._gesture_ids = frozenset(str(item["id"]) for item in gestures)

        digest = hashlib.sha256(
            f"{session_id}:{bodyprint_id}:{profile_fingerprint}".encode("utf-8")
        ).digest()
        self._selection_seed = int.from_bytes(digest[0:8], "big")

    @property
    def profile_id(self) -> str | None:
        return self._profile_id

    @property
    def source(self) -> str:
        return self._source

    def _resolve_gesture(self, semantic: str | None) -> tuple[str | None, str]:
        if semantic is None:
            return None, "none"
        if not isinstance(semantic, str) or not semantic:
            raise BodyMotionMixerError("semantic gesture must be a non-empty string or null")

        if semantic.startswith("bodyprint:"):
            gesture_id = semantic.removeprefix("bodyprint:")
            if gesture_id not in self._gesture_ids:
                raise BodyMotionMixerError("explicit bodyprint gesture does not exist in validated package")
            if not self._motion_usable:
                raise BodyMotionMixerError("explicit bodyprint gesture requires usable motion evidence")
            return semantic, "explicit_profile"

        if not self._motion_usable or not self._gestures:
            return None, "semantic"

        # ModelRig owns the semantic gesture. This deterministic choice only
        # selects which extracted source trajectory may realize that cue.
        digest = hashlib.sha256(
            f"{self._selection_seed}:{semantic}".encode("utf-8")
        ).digest()
        index = int.from_bytes(digest[:8], "big") % len(self._gestures)
        return f"bodyprint:{self._gestures[index]['id']}", "profile_replay"

    def render(self, snapshot: RuntimeSnapshot, *, timestamp_ms: int) -> BodyMotionRuntimeFrame:
        if timestamp_ms < 0:
            raise BodyMotionMixerError("timestamp_ms must be non-negative")
        if snapshot.session_id != self._session_id:
            raise BodyMotionMixerError("snapshot belongs to another session")
        if snapshot.bodyprint_id != self._bodyprint_id:
            raise BodyMotionMixerError("snapshot belongs to another bodyprint")

        replay, gesture_source = self._resolve_gesture(snapshot.active_gesture)
        return BodyMotionRuntimeFrame(
            timestamp_ms=timestamp_ms,
            profile_id=self._profile_id,
            source=self._source,
            head_motion_scale=self._head_motion_scale,
            micro_motion_scale=self._micro_motion_scale,
            posture_lean_x=self._posture_lean_x,
            posture_source=self._posture_source,
            gesture_semantic=snapshot.active_gesture,
            gesture_replay=replay,
            gesture_source=gesture_source,
            dominant_side=self._dominant_side,
            gesture_frequency_per_minute=self._gesture_frequency_per_minute,
        )
