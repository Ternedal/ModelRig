"""BodyRig embodiment runtime bootstrap."""

from .bodyprint import BodyprintValidationError, validate_manifest
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
