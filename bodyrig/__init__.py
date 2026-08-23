"""BodyRig embodiment runtime bootstrap."""

from .bodyprint import BodyprintValidationError, validate_manifest
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
from .voicerig_adapter import (
    SpeechFrame,
    SpeechTrack,
    TimingMode,
    VoiceRigContractError,
    timed_track,
    wav_envelope_track,
)

__all__ = [
    "BodyRigRuntime",
    "BodyState",
    "CancelScope",
    "EventRejected",
    "RuntimeSnapshot",
    "BodyprintValidationError",
    "validate_manifest",
    "FingerprintConfig",
    "FingerprintError",
    "build_bodyprint",
    "canonical_bodyprint_json",
    "gesture_intent",
    "validate_bodyprint_package",
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
