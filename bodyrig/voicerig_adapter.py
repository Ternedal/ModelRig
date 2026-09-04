from __future__ import annotations

from array import array
from bisect import bisect_right
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
import math
import sys
import wave
from typing import Iterable, Mapping, Sequence


class VoiceRigContractError(ValueError):
    """Raised when VoiceRig audio/metadata cannot be represented safely."""


class TimingMode(str, Enum):
    """Fidelity of speech timing supplied to BodyRig."""

    TIMED = "timed"
    AUDIO_ENVELOPE = "audio_envelope"


@dataclass(frozen=True)
class SpeechFrame:
    offset_ms: int
    mouth_open: float
    visemes: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class SpeechTrack:
    utterance_id: str
    mode: TimingMode
    duration_ms: int
    sample_rate: int
    frames: tuple[SpeechFrame, ...]

    def sample(self, offset_ms: int) -> SpeechFrame:
        if offset_ms < 0:
            raise VoiceRigContractError("speech offset must be non-negative")
        if not self.frames or offset_ms > self.duration_ms:
            return SpeechFrame(offset_ms=offset_ms, mouth_open=0.0)
        offsets = tuple(frame.offset_ms for frame in self.frames)
        index = bisect_right(offsets, offset_ms) - 1
        if index < 0:
            return SpeechFrame(offset_ms=offset_ms, mouth_open=0.0)
        return self.frames[index]


def _unit(value: object, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise VoiceRigContractError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise VoiceRigContractError(f"{field} must be within 0..1")
    return number


def _canonical_headers(headers: Mapping[str, object] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def timed_track(
    *,
    utterance_id: str,
    duration_ms: int,
    sample_rate: int,
    frames: Iterable[Mapping[str, object]],
) -> SpeechTrack:
    """Build a precise track only from explicitly supplied timing data.

    BodyRig never manufactures phonemes/visemes from text. A caller may use
    this mode only when an upstream component actually supplies timestamps.
    """

    if not utterance_id:
        raise VoiceRigContractError("utterance_id is required")
    if duration_ms <= 0:
        raise VoiceRigContractError("duration_ms must be positive")
    if sample_rate <= 0:
        raise VoiceRigContractError("sample_rate must be positive")

    output: list[SpeechFrame] = []
    previous = -1
    for raw in frames:
        try:
            offset_ms = int(raw["offset_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VoiceRigContractError("timed frame requires integer offset_ms") from exc
        if offset_ms < 0 or offset_ms > duration_ms:
            raise VoiceRigContractError("timed frame offset is outside utterance")
        if offset_ms <= previous:
            raise VoiceRigContractError("timed frame offsets must increase strictly")
        previous = offset_ms

        visemes_raw = raw.get("visemes") or ()
        parsed: list[tuple[str, float]] = []
        if isinstance(visemes_raw, Mapping):
            source: Sequence[tuple[object, object]] = tuple(visemes_raw.items())
        elif isinstance(visemes_raw, (list, tuple)):
            source = tuple(
                (item.get("id"), item.get("weight"))
                for item in visemes_raw
                if isinstance(item, Mapping)
            )
            if len(source) != len(visemes_raw):
                raise VoiceRigContractError("visemes must contain id/weight objects")
        else:
            raise VoiceRigContractError("visemes must be an object or list")

        for identifier, weight in source:
            if not isinstance(identifier, str) or not identifier:
                raise VoiceRigContractError("viseme id must be non-empty")
            parsed.append((identifier, _unit(weight, field="viseme weight")))

        if "mouth_open" in raw:
            mouth_open = _unit(raw["mouth_open"], field="mouth_open")
        else:
            mouth_open = max((weight for _, weight in parsed), default=0.0)
        output.append(
            SpeechFrame(
                offset_ms=offset_ms,
                mouth_open=mouth_open,
                visemes=tuple(parsed),
            )
        )

    if not output:
        raise VoiceRigContractError("timed track requires at least one frame")
    return SpeechTrack(
        utterance_id=utterance_id,
        mode=TimingMode.TIMED,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        frames=tuple(output),
    )


def wav_envelope_track(
    *,
    utterance_id: str,
    wav_bytes: bytes,
    headers: Mapping[str, object] | None = None,
    frame_ms: int = 20,
) -> SpeechTrack:
    """Derive an approximate mouth-energy track from VoiceRig's current WAV.

    VoiceRig RC25 returns a complete WAV plus sample-rate/duration headers but
    no phoneme or viseme timeline. This adapter therefore labels its output as
    AUDIO_ENVELOPE. It is useful for approximate mouth motion, never evidence
    of phoneme-accurate lipsync.
    """

    if not utterance_id:
        raise VoiceRigContractError("utterance_id is required")
    if not wav_bytes:
        raise VoiceRigContractError("VoiceRig WAV is empty")
    if frame_ms < 10 or frame_ms > 100:
        raise VoiceRigContractError("frame_ms must be within 10..100")

    try:
        with wave.open(BytesIO(wav_bytes), "rb") as stream:
            channels = stream.getnchannels()
            sample_rate = stream.getframerate()
            sample_width = stream.getsampwidth()
            frame_count = stream.getnframes()
            compression = stream.getcomptype()
            raw = stream.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise VoiceRigContractError("invalid VoiceRig WAV") from exc

    if channels < 1 or sample_rate <= 0 or frame_count <= 0:
        raise VoiceRigContractError("VoiceRig WAV has invalid audio geometry")
    if sample_width != 2 or compression != "NONE":
        raise VoiceRigContractError("BodyRig v0.1 envelope adapter requires PCM16 WAV")

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    expected_samples = frame_count * channels
    if len(samples) < expected_samples:
        raise VoiceRigContractError("VoiceRig WAV ended before declared frame count")

    samples_per_window = max(1, int(sample_rate * frame_ms / 1000)) * channels
    rms_values: list[float] = []
    for start in range(0, expected_samples, samples_per_window):
        chunk = samples[start : min(start + samples_per_window, expected_samples)]
        if not chunk:
            continue
        squared = sum(float(sample) * float(sample) for sample in chunk)
        rms_values.append(math.sqrt(squared / len(chunk)) / 32768.0)

    peak = max(rms_values, default=0.0)
    frames: list[SpeechFrame] = []
    smoothed = 0.0
    for index, rms in enumerate(rms_values):
        relative = 0.0 if peak <= 0.0 else min(1.0, rms / peak)
        gated = max(0.0, (relative - 0.05) / 0.95)
        smoothed = 0.72 * gated + 0.28 * smoothed
        frames.append(
            SpeechFrame(
                offset_ms=index * frame_ms,
                mouth_open=min(1.0, max(0.0, smoothed)),
            )
        )

    duration_ms = max(1, round(frame_count * 1000 / sample_rate))
    canonical = _canonical_headers(headers)

    header_rate = canonical.get("x-voicerig-sample-rate")
    if header_rate is not None:
        try:
            declared_rate = int(header_rate)
        except ValueError as exc:
            raise VoiceRigContractError("X-VoiceRig-Sample-Rate is invalid") from exc
        if declared_rate != sample_rate:
            raise VoiceRigContractError(
                "VoiceRig sample-rate header disagrees with WAV payload"
            )

    header_duration = canonical.get("x-voicerig-duration")
    if header_duration is not None:
        try:
            declared_ms = round(float(header_duration) * 1000)
        except ValueError as exc:
            raise VoiceRigContractError("X-VoiceRig-Duration is invalid") from exc
        tolerance_ms = max(80, frame_ms * 2)
        if abs(declared_ms - duration_ms) > tolerance_ms:
            raise VoiceRigContractError(
                "VoiceRig duration header disagrees with WAV payload"
            )

    return SpeechTrack(
        utterance_id=utterance_id,
        mode=TimingMode.AUDIO_ENVELOPE,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        frames=tuple(frames),
    )
