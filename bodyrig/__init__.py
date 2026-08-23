"""BodyRig embodiment runtime bootstrap."""

from .body_motion_mixer import (
    BodyMotionMixer,
    BodyMotionMixerError,
    BodyMotionRuntimeFrame,
)
from .bodyprint import BodyprintValidationError, validate_manifest
from .face_behavior import (
    FaceBehaviorError,
    build_face_behavior,
    canonical_face_behavior_json,
    validate_face_behavior,
)
from .face_mixer import (
    FaceBehaviorMixer,
    FaceChannel,
    FaceMixerError,
    FaceRuntimeFrame,
)
from .fingerprint import (
    FingerprintConfig,
    FingerprintError,
    build_bodyprint,
    canonical_bodyprint_json,
    gesture_intent,
    validate_bodyprint_package,
)
from .runtime import (
    BodyRigRuntime,
    BodyState,
    CancelScope,
    EventRejected,
    RuntimeSnapshot,
)
from .scheduler import EmbodimentScheduler, RenderFrame, SchedulerError
from .shape import (
    ShapeConfig,
    ShapeProfileError,
    build_shape_profile,
    canonical_shape_json,
    validate_shape_profile,
)
from .voicerig_adapter import (
    SpeechFrame,
    SpeechTrack,
    TimingMode,
    VoiceRigContractError,
    timed_track,
    wav_envelope_track,
)

__all__ = [
    "BodyMotionMixer",
    "BodyMotionMixerError",
    "BodyMotionRuntimeFrame",
    "BodyRigRuntime",
    "BodyState",
    "CancelScope",
    "EventRejected",
    "RuntimeSnapshot",
    "BodyprintValidationError",
    "validate_manifest",
    "FaceBehaviorError",
    "build_face_behavior",
    "canonical_face_behavior_json",
    "validate_face_behavior",
    "FaceBehaviorMixer",
    "FaceChannel",
    "FaceMixerError",
    "FaceRuntimeFrame",
    "FingerprintConfig",
    "FingerprintError",
    "build_bodyprint",
    "canonical_bodyprint_json",
    "gesture_intent",
    "validate_bodyprint_package",
    "ShapeConfig",
    "ShapeProfileError",
    "build_shape_profile",
    "canonical_shape_json",
    "validate_shape_profile",
    "EmbodimentScheduler",
    "RenderFrame",
    "SchedulerError",
    "SpeechFrame",
    "SpeechTrack",
    "TimingMode",
    "VoiceRigContractError",
    "timed_track",
    "wav_envelope_track",
]
