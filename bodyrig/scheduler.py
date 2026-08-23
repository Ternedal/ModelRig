from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Mapping

from .body_motion_mixer import BodyMotionMixer, BodyMotionMixerError
from .face_mixer import FaceBehaviorMixer, FaceMixerError
from .runtime import BodyState, RuntimeSnapshot
from .voicerig_adapter import SpeechTrack, TimingMode, VoiceRigContractError


class SchedulerError(ValueError):
    """Raised when renderer-neutral timeline state is inconsistent."""


@dataclass(frozen=True)
class RenderFrame:
    """Renderer-neutral animation hints for one instant on the session clock."""

    timestamp_ms: int
    state: BodyState
    gesture: str | None
    gaze_target: str | None
    gaze_strength: float
    emotion: str
    emotion_intensity: float
    energy: float
    mouth_open: float
    visemes: tuple[tuple[str, float], ...]
    speech_timing_mode: TimingMode | None
    blink: float
    breath: float
    head_yaw_hint: float
    head_pitch_hint: float
    face_profile_id: str | None = None
    face_channels: tuple[tuple[str, float], ...] = ()
    face_channel_sources: tuple[tuple[str, str], ...] = ()
    body_motion_profile_id: str | None = None
    body_motion_source: str = "generic"
    head_motion_scale: float = 1.0
    micro_motion_scale: float = 1.0
    posture_lean_x: float = 0.0
    posture_source: str = "generic"
    resolved_gesture: str | None = None
    gesture_resolution_source: str = "none"
    dominant_side_hint: str | None = None
    gesture_frequency_per_minute: float | None = None


class EmbodimentScheduler:
    """Deterministic animation mixer with no renderer or ML dependency.

    Output values are semantic/procedural hints rather than bone rotations or
    morph-target names. A renderer adapter owns retargeting and final blending.
    M2.2 may optionally personalize renderer-neutral facial hints from a
    validated M2.1 face-behavior profile. M2.3 may optionally personalize body
    motion from a validated M1.2 bodyprint package. Omitting either profile
    preserves the corresponding generic procedural path.
    """

    def __init__(
        self,
        *,
        session_id: str,
        bodyprint_id: str,
        face_behavior: Mapping[str, Any] | None = None,
        bodyprint_package: Mapping[str, Any] | None = None,
    ) -> None:
        if not session_id or not bodyprint_id:
            raise ValueError("session_id and bodyprint_id are required")
        self._session_id = session_id
        self._bodyprint_id = bodyprint_id
        digest = hashlib.sha256(f"{session_id}:{bodyprint_id}".encode("utf-8")).digest()
        self._phase_a = int.from_bytes(digest[0:4], "big") / 2**32
        self._phase_b = int.from_bytes(digest[4:8], "big") / 2**32
        self._blink_period_ms = 3300 + int.from_bytes(digest[8:10], "big") % 1900
        self._tracks: dict[str, tuple[SpeechTrack, int]] = {}
        self._cancelled: set[str] = set()
        try:
            self._face_mixer = (
                FaceBehaviorMixer(
                    session_id=session_id,
                    bodyprint_id=bodyprint_id,
                    face_behavior=face_behavior,
                )
                if face_behavior is not None
                else None
            )
        except FaceMixerError as exc:
            raise SchedulerError(str(exc)) from exc
        try:
            self._body_motion_mixer = (
                BodyMotionMixer(
                    session_id=session_id,
                    bodyprint_id=bodyprint_id,
                    bodyprint_package=bodyprint_package,
                )
                if bodyprint_package is not None
                else None
            )
        except BodyMotionMixerError as exc:
            raise SchedulerError(str(exc)) from exc

    def attach_speech(self, track: SpeechTrack, *, started_at_ms: int) -> None:
        if started_at_ms < 0:
            raise SchedulerError("speech start timestamp must be non-negative")
        if track.utterance_id in self._cancelled:
            raise SchedulerError("cancelled utterance cannot be reattached")
        self._tracks[track.utterance_id] = (track, started_at_ms)

    def cancel_utterance(self, utterance_id: str) -> None:
        if not utterance_id:
            raise SchedulerError("utterance_id is required")
        self._cancelled.add(utterance_id)
        self._tracks.pop(utterance_id, None)

    def _validate_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        if snapshot.session_id != self._session_id:
            raise SchedulerError("snapshot belongs to another session")
        if snapshot.bodyprint_id != self._bodyprint_id:
            raise SchedulerError("snapshot belongs to another bodyprint")

    def _blink(self, timestamp_ms: int) -> float:
        phase_ms = int(self._phase_a * self._blink_period_ms)
        position = (timestamp_ms + phase_ms) % self._blink_period_ms
        # A deterministic 160 ms close/open pulse. M2.2 replaces this only when
        # a validated source-specific face behavior profile is explicitly used.
        if position >= 160:
            return 0.0
        if position <= 80:
            return position / 80.0
        return (160 - position) / 80.0

    def _procedural(self, snapshot: RuntimeSnapshot, timestamp_ms: int) -> tuple[float, float, float, float]:
        seconds = timestamp_ms / 1000.0
        breath = 0.5 + 0.5 * math.sin(
            2.0 * math.pi * (seconds / 4.2 + self._phase_a)
        )

        state_scale = {
            BodyState.IDLE: 1.0,
            BodyState.LISTENING: 0.65,
            BodyState.THINKING: 0.85,
            BodyState.SPEAKING: 0.55,
            BodyState.WAITING_FOR_TOOL: 0.75,
            BodyState.INTERRUPTED: 0.35,
            BodyState.ERROR: 0.15,
        }[snapshot.state]
        energy_scale = 0.55 + 0.9 * snapshot.energy
        yaw = 0.05 * state_scale * energy_scale * math.sin(
            2.0 * math.pi * (seconds / 6.7 + self._phase_b)
        )
        pitch = 0.035 * state_scale * energy_scale * math.sin(
            2.0 * math.pi * (seconds / 5.1 + self._phase_a * 0.7)
        )

        gaze_strength = 0.0 if snapshot.gaze_target in {None, "none"} else 0.9
        if gaze_strength:
            # Briefly soften direct gaze on a deterministic cadence to avoid the
            # dead-eyed constant-lock look. The target itself is never changed.
            glance_cycle = (timestamp_ms + int(self._phase_b * 7100)) % 7100
            if glance_cycle < 360:
                gaze_strength = 0.35 + 0.55 * (glance_cycle / 360.0)

        return breath, yaw, pitch, gaze_strength

    def render(self, snapshot: RuntimeSnapshot, *, timestamp_ms: int) -> RenderFrame:
        if timestamp_ms < 0:
            raise SchedulerError("timestamp_ms must be non-negative")
        self._validate_snapshot(snapshot)

        mouth_open = 0.0
        visemes: tuple[tuple[str, float], ...] = ()
        timing_mode: TimingMode | None = None
        utterance_id = snapshot.active_utterance_id
        if snapshot.state == BodyState.SPEAKING and utterance_id:
            attached = self._tracks.get(utterance_id)
            if utterance_id not in self._cancelled and attached is not None:
                track, started_at_ms = attached
                offset_ms = timestamp_ms - started_at_ms
                if offset_ms >= 0:
                    try:
                        speech_frame = track.sample(offset_ms)
                    except VoiceRigContractError as exc:
                        raise SchedulerError(str(exc)) from exc
                    mouth_open = speech_frame.mouth_open
                    visemes = speech_frame.visemes
                    timing_mode = track.mode

        breath, yaw, pitch, gaze_strength = self._procedural(snapshot, timestamp_ms)
        blink = self._blink(timestamp_ms)
        face_profile_id: str | None = None
        face_channels: tuple[tuple[str, float], ...] = ()
        face_channel_sources: tuple[tuple[str, str], ...] = ()
        if self._face_mixer is not None:
            try:
                face = self._face_mixer.render(
                    snapshot,
                    timestamp_ms=timestamp_ms,
                    speech_mouth_open=mouth_open,
                )
            except FaceMixerError as exc:
                raise SchedulerError(str(exc)) from exc
            face_profile_id = face.profile_id
            face_channels = tuple((channel.name, channel.value) for channel in face.channels)
            face_channel_sources = tuple((channel.name, channel.source) for channel in face.channels)
            blink = max(face.value("blink_left"), face.value("blink_right"))

        body_motion_profile_id: str | None = None
        body_motion_source = "generic"
        head_motion_scale = 1.0
        micro_motion_scale = 1.0
        posture_lean_x = 0.0
        posture_source = "generic"
        resolved_gesture: str | None = None
        gesture_resolution_source = "semantic" if snapshot.active_gesture else "none"
        dominant_side_hint: str | None = None
        gesture_frequency_per_minute: float | None = None
        if self._body_motion_mixer is not None:
            try:
                motion = self._body_motion_mixer.render(snapshot, timestamp_ms=timestamp_ms)
            except BodyMotionMixerError as exc:
                raise SchedulerError(str(exc)) from exc
            body_motion_profile_id = motion.profile_id
            body_motion_source = motion.source
            head_motion_scale = motion.head_motion_scale
            micro_motion_scale = motion.micro_motion_scale
            posture_lean_x = motion.posture_lean_x
            posture_source = motion.posture_source
            resolved_gesture = motion.gesture_replay
            gesture_resolution_source = motion.gesture_source
            dominant_side_hint = motion.dominant_side
            gesture_frequency_per_minute = motion.gesture_frequency_per_minute

            yaw *= head_motion_scale
            pitch *= head_motion_scale
            breath = max(0.0, min(1.0, 0.5 + (breath - 0.5) * micro_motion_scale))

        return RenderFrame(
            timestamp_ms=timestamp_ms,
            state=snapshot.state,
            gesture=snapshot.active_gesture,
            gaze_target=snapshot.gaze_target,
            gaze_strength=gaze_strength,
            emotion=snapshot.emotion,
            emotion_intensity=snapshot.emotion_intensity,
            energy=snapshot.energy,
            mouth_open=mouth_open,
            visemes=visemes,
            speech_timing_mode=timing_mode,
            blink=blink,
            breath=breath,
            head_yaw_hint=yaw,
            head_pitch_hint=pitch,
            face_profile_id=face_profile_id,
            face_channels=face_channels,
            face_channel_sources=face_channel_sources,
            body_motion_profile_id=body_motion_profile_id,
            body_motion_source=body_motion_source,
            head_motion_scale=head_motion_scale,
            micro_motion_scale=micro_motion_scale,
            posture_lean_x=posture_lean_x,
            posture_source=posture_source,
            resolved_gesture=resolved_gesture,
            gesture_resolution_source=gesture_resolution_source,
            dominant_side_hint=dominant_side_hint,
            gesture_frequency_per_minute=gesture_frequency_per_minute,
        )
