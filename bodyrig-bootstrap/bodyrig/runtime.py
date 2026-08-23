from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from time import time

from .models import BodyCue, SpeechTiming


@dataclass
class RuntimeState:
    active_body_id: str | None = None
    utterance_id: str | None = None
    cue: dict | None = None
    speech: dict | None = None
    updated_at: float = field(default_factory=time)


class BodyRuntime:
    """Small in-memory V1 runtime coordinator.

    The renderer can poll this state now; a later WebSocket transport can publish
    the same semantic state without changing the ModelRig/VoiceRig contracts.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._state = RuntimeState()

    def activate(self, body_id: str) -> RuntimeState:
        with self._lock:
            self._state.active_body_id = body_id
            self._state.updated_at = time()
            return self.snapshot()

    def apply_cue(self, cue: BodyCue) -> RuntimeState:
        with self._lock:
            self._state.utterance_id = cue.utterance_id
            self._state.cue = cue.model_dump(exclude_none=True)
            self._state.speech = None
            self._state.updated_at = time()
            return self.snapshot()

    def apply_speech(self, timing: SpeechTiming) -> RuntimeState:
        with self._lock:
            if self._state.utterance_id != timing.utterance_id:
                raise ValueError("speech timing does not match active utterance")
            self._state.speech = timing.model_dump(exclude_none=True)
            self._state.updated_at = time()
            if timing.state == "stop":
                self._state.utterance_id = None
            return self.snapshot()

    def snapshot(self) -> RuntimeState:
        with self._lock:
            return RuntimeState(
                active_body_id=self._state.active_body_id,
                utterance_id=self._state.utterance_id,
                cue=dict(self._state.cue) if self._state.cue else None,
                speech=dict(self._state.speech) if self._state.speech else None,
                updated_at=self._state.updated_at,
            )
