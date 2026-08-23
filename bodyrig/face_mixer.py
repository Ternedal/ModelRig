"""BodyRig M2.2 renderer-neutral facial runtime mixer.

This layer consumes the M2.1 facial-behavior profile and combines it with the
already-authoritative semantic runtime state and VoiceRig mouth timing. Output
channel names are BodyRig semantics, never renderer/VRM morph target names.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Mapping

from .face_behavior import canonical_face_behavior_json, validate_face_behavior
from .runtime import BodyState, RuntimeSnapshot


class FaceMixerError(ValueError):
    """Raised when M2.2 facial runtime input cannot be mixed safely."""


@dataclass(frozen=True)
class FaceChannel:
    """One bounded renderer-neutral facial channel and its evidence source."""

    name: str
    value: float
    source: str


@dataclass(frozen=True)
class FaceRuntimeFrame:
    """Renderer-neutral facial hints for one instant on the BodyRig clock."""

    timestamp_ms: int
    profile_id: str | None
    channels: tuple[FaceChannel, ...]

    def value(self, name: str) -> float:
        for channel in self.channels:
            if channel.name == name:
                return channel.value
        raise FaceMixerError(f"unknown facial channel: {name}")

    def source(self, name: str) -> str:
        for channel in self.channels:
            if channel.name == name:
                return channel.source
        raise FaceMixerError(f"unknown facial channel: {name}")


_CHANNEL_ORDER = (
    "blink_left",
    "blink_right",
    "jaw_open",
    "smile",
    "frown",
    "brow_inner_up",
    "brow_down",
)

_POSITIVE = frozenset({"happy", "joy", "joyful", "amused", "excited", "pleased", "warm"})
_SAD = frozenset({"sad", "concerned", "disappointed", "worried"})
_ANGRY = frozenset({"angry", "frustrated", "annoyed"})
_SURPRISED = frozenset({"surprised", "astonished"})
_THOUGHTFUL = frozenset({"thoughtful", "curious", "thinking"})


def _unit(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FaceMixerError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise FaceMixerError(f"{label} must be within [0,1]")
    return number


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 6)


def _semantic_face(emotion: str, intensity: float) -> dict[str, float]:
    """Map ModelRig semantic emotion to bounded BodyRig facial semantics.

    Unknown emotion names intentionally produce no invented facial mapping. The
    original semantic emotion remains available on RuntimeSnapshot/RenderFrame.
    """

    name = emotion.strip().lower()
    result = {
        "jaw_open": 0.0,
        "smile": 0.0,
        "frown": 0.0,
        "brow_inner_up": 0.0,
        "brow_down": 0.0,
    }
    if name in _POSITIVE:
        result["smile"] = 0.85 * intensity
        result["brow_inner_up"] = 0.12 * intensity
    elif name in _SAD:
        result["frown"] = 0.72 * intensity
        result["brow_inner_up"] = 0.55 * intensity
    elif name in _ANGRY:
        result["frown"] = 0.52 * intensity
        result["brow_down"] = 0.85 * intensity
    elif name in _SURPRISED:
        result["jaw_open"] = 0.55 * intensity
        result["brow_inner_up"] = 0.92 * intensity
    elif name in _THOUGHTFUL:
        result["brow_inner_up"] = 0.28 * intensity
        result["brow_down"] = 0.08 * intensity
    return result


class FaceBehaviorMixer:
    """Deterministically personalize facial semantics from an optional M2.1 profile."""

    def __init__(
        self,
        *,
        session_id: str,
        bodyprint_id: str,
        face_behavior: Mapping[str, Any] | None = None,
    ) -> None:
        if not session_id or not bodyprint_id:
            raise FaceMixerError("session_id and bodyprint_id are required")

        self._session_id = session_id
        self._bodyprint_id = bodyprint_id
        self._profile_id: str | None = None
        self._priors: dict[str, tuple[float, float] | None] = {
            key: None for key in ("jaw_open", "smile", "frown", "brow_inner_up", "brow_down")
        }
        self._blink_rates: dict[str, float | None] = {"left": None, "right": None}
        self._blink_rate_sources: dict[str, str] = {"left": "generic", "right": "generic"}

        profile_fingerprint = "generic"
        if face_behavior is not None:
            try:
                validate_face_behavior(face_behavior)
                canonical = canonical_face_behavior_json(face_behavior)
            except Exception as exc:
                raise FaceMixerError(str(exc)) from exc
            self._profile_id = str(face_behavior["id"])
            profile_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            priors = face_behavior["expression_priors"]
            for name in self._priors:
                prior = priors[name]
                if prior["samples"] > 0:
                    self._priors[name] = (
                        _unit(prior["mean"], f"expression_priors.{name}.mean"),
                        _unit(prior["coverage"], f"expression_priors.{name}.coverage"),
                    )

            blink = face_behavior["blink"]
            for side in ("left", "right"):
                rate = blink[side]["per_minute"]
                if blink[side]["samples"] >= 2 and rate is not None:
                    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
                        raise FaceMixerError(f"blink.{side}.per_minute must be numeric")
                    number = float(rate)
                    if not math.isfinite(number) or not 0.0 <= number <= 600.0:
                        raise FaceMixerError(f"blink.{side}.per_minute is out of range")
                    self._blink_rates[side] = number
                    self._blink_rate_sources[side] = "profile"

        digest = hashlib.sha256(
            f"{session_id}:{bodyprint_id}:{profile_fingerprint}".encode("utf-8")
        ).digest()
        generic_digest = hashlib.sha256(f"{session_id}:{bodyprint_id}".encode("utf-8")).digest()
        self._phase = {
            "left": int.from_bytes(digest[0:4], "big") / 2**32,
            "right": int.from_bytes(digest[4:8], "big") / 2**32,
        }
        self._generic_phase = int.from_bytes(generic_digest[0:4], "big") / 2**32
        self._generic_period_ms = 3300 + int.from_bytes(generic_digest[8:10], "big") % 1900

    @property
    def profile_id(self) -> str | None:
        return self._profile_id

    def blink_period_ms(self, side: str) -> int | None:
        """Return runtime cadence period; ``None`` means observed zero blink rate."""

        if side not in {"left", "right"}:
            raise FaceMixerError("blink side must be left or right")
        rate = self._blink_rates[side]
        if rate is None:
            return self._generic_period_ms
        if rate == 0.0:
            return None
        # Runtime safety bound: preserve ordering/rate differences without
        # permitting a malformed-but-schema-valid extreme to create >2 Hz pulses.
        return max(500, min(15_000, round(60_000.0 / rate)))

    def blink_source(self, side: str) -> str:
        if side not in {"left", "right"}:
            raise FaceMixerError("blink side must be left or right")
        return self._blink_rate_sources[side]

    def _blink(self, side: str, timestamp_ms: int) -> float:
        period_ms = self.blink_period_ms(side)
        if period_ms is None:
            return 0.0

        if self._blink_rate_sources[side] == "generic":
            phase = self._generic_phase
        else:
            phase = self._phase[side]
        phase_ms = int(phase * period_ms)
        position = (timestamp_ms + phase_ms) % period_ms
        pulse_ms = min(160, max(80, period_ms // 4))
        if position >= pulse_ms:
            return 0.0
        half = pulse_ms / 2.0
        if position <= half:
            return _bounded(position / half)
        return _bounded((pulse_ms - position) / half)

    def _personalize(self, channel: str, semantic_value: float) -> FaceChannel:
        prior = self._priors[channel]
        if prior is None:
            return FaceChannel(channel, _bounded(semantic_value), "semantic")
        mean, coverage = prior
        # Observed 0.0 is intentionally distinct from missing evidence: it
        # reduces the source-specific gain, while missing evidence keeps 1.0.
        gain = 1.0 + (mean - 0.5) * 0.6 * coverage
        return FaceChannel(channel, _bounded(semantic_value * gain), "profile_semantic")

    def render(
        self,
        snapshot: RuntimeSnapshot,
        *,
        timestamp_ms: int,
        speech_mouth_open: float = 0.0,
    ) -> FaceRuntimeFrame:
        if timestamp_ms < 0:
            raise FaceMixerError("timestamp_ms must be non-negative")
        if snapshot.session_id != self._session_id:
            raise FaceMixerError("snapshot belongs to another session")
        if snapshot.bodyprint_id != self._bodyprint_id:
            raise FaceMixerError("snapshot belongs to another bodyprint")

        speech_mouth = _unit(speech_mouth_open, "speech_mouth_open")
        semantic = _semantic_face(snapshot.emotion, _unit(snapshot.emotion_intensity, "emotion_intensity"))

        channels: list[FaceChannel] = [
            FaceChannel("blink_left", self._blink("left", timestamp_ms), self.blink_source("left")),
            FaceChannel("blink_right", self._blink("right", timestamp_ms), self.blink_source("right")),
        ]

        # While the runtime says SPEAKING, VoiceRig timing is authoritative. A
        # missing/late speech track therefore means closed mouth, not invented
        # semantic or source-derived jaw motion.
        if snapshot.state == BodyState.SPEAKING:
            channels.append(FaceChannel("jaw_open", speech_mouth, "speech"))
        else:
            channels.append(self._personalize("jaw_open", semantic["jaw_open"]))

        for name in ("smile", "frown", "brow_inner_up", "brow_down"):
            channels.append(self._personalize(name, semantic[name]))

        if tuple(channel.name for channel in channels) != _CHANNEL_ORDER:
            raise FaceMixerError("internal facial channel order mismatch")
        return FaceRuntimeFrame(
            timestamp_ms=timestamp_ms,
            profile_id=self._profile_id,
            channels=tuple(channels),
        )
