from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class EventRejected(ValueError):
    """Raised when an event violates BodyRig runtime ordering or semantics."""


class BodyState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WAITING_FOR_TOOL = "waiting_for_tool"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class CancelScope(str, Enum):
    UTTERANCE = "utterance"
    GESTURE = "gesture"
    ALL = "all"


@dataclass(frozen=True)
class RuntimeSnapshot:
    session_id: str
    bodyprint_id: str
    sequence: int
    state: BodyState
    active_utterance_id: str | None
    active_gesture: str | None
    health: str


class BodyRigRuntime:
    """Small renderer-neutral state machine for embodiment control.

    This class deliberately contains no renderer, audio or ML dependency.  It
    enforces the cross-system semantic boundary and can therefore be exercised
    in CI before a Unity/VRM adapter exists.
    """

    def __init__(self, *, session_id: str, bodyprint_id: str) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        if not bodyprint_id:
            raise ValueError("bodyprint_id is required")
        self._session_id = session_id
        self._bodyprint_id = bodyprint_id
        self._last_sequence = -1
        self._state = BodyState.IDLE
        self._active_utterance_id: str | None = None
        self._active_gesture: str | None = None
        self._cancelled_utterances: set[str] = set()
        self._health = "ok"

    @property
    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            session_id=self._session_id,
            bodyprint_id=self._bodyprint_id,
            sequence=self._last_sequence,
            state=self._state,
            active_utterance_id=self._active_utterance_id,
            active_gesture=self._active_gesture,
            health=self._health,
        )

    def _accept_sequence(self, sequence: int) -> None:
        if sequence < 0:
            raise EventRejected("sequence must be non-negative")
        if sequence <= self._last_sequence:
            raise EventRejected(
                f"stale sequence {sequence}; last accepted is {self._last_sequence}"
            )
        self._last_sequence = sequence

    def apply_state(self, *, sequence: int, state: str | BodyState) -> RuntimeSnapshot:
        self._accept_sequence(sequence)
        try:
            self._state = state if isinstance(state, BodyState) else BodyState(state)
        except ValueError as exc:
            raise EventRejected(f"unsupported body state: {state!r}") from exc
        if self._state != BodyState.SPEAKING:
            self._active_gesture = None
        return self.snapshot

    def apply_expression_plan(
        self, *, sequence: int, plan: Mapping[str, Any]
    ) -> RuntimeSnapshot:
        self._accept_sequence(sequence)
        try:
            self._state = BodyState(str(plan["state"]))
        except (KeyError, ValueError) as exc:
            raise EventRejected("expression plan requires a supported state") from exc

        gesture = plan.get("gesture")
        if gesture is None:
            self._active_gesture = None
        elif isinstance(gesture, Mapping):
            intent = gesture.get("intent")
            if not isinstance(intent, str) or not intent:
                raise EventRejected("gesture intent must be a non-empty string")
            self._active_gesture = intent
        else:
            raise EventRejected("gesture must be an object or null")
        return self.snapshot

    def start_speech(self, *, sequence: int, utterance_id: str) -> RuntimeSnapshot:
        self._accept_sequence(sequence)
        if not utterance_id:
            raise EventRejected("utterance_id is required")
        if utterance_id in self._cancelled_utterances:
            raise EventRejected("cancelled utterance cannot be restarted")
        self._active_utterance_id = utterance_id
        self._state = BodyState.SPEAKING
        return self.snapshot

    def accept_speech_frame(self, *, sequence: int, utterance_id: str) -> bool:
        """Accept a viseme/prosody frame if it still belongs to active speech.

        Cancelled or no-longer-active utterances are ignored after sequence
        ordering has been enforced.  This is the stale-queue protection used by
        future renderer/audio adapters.
        """

        self._accept_sequence(sequence)
        if utterance_id in self._cancelled_utterances:
            return False
        return utterance_id == self._active_utterance_id

    def end_speech(self, *, sequence: int, utterance_id: str) -> RuntimeSnapshot:
        self._accept_sequence(sequence)
        if utterance_id in self._cancelled_utterances:
            return self.snapshot
        if utterance_id != self._active_utterance_id:
            raise EventRejected("speech end does not match active utterance")
        self._active_utterance_id = None
        self._active_gesture = None
        self._state = BodyState.IDLE
        return self.snapshot

    def cancel(
        self,
        *,
        sequence: int,
        scope: str | CancelScope,
        utterance_id: str | None = None,
    ) -> RuntimeSnapshot:
        self._accept_sequence(sequence)
        try:
            resolved_scope = scope if isinstance(scope, CancelScope) else CancelScope(scope)
        except ValueError as exc:
            raise EventRejected(f"unsupported cancel scope: {scope!r}") from exc

        if resolved_scope == CancelScope.UTTERANCE:
            if not utterance_id:
                raise EventRejected("utterance cancellation requires utterance_id")
            self._cancelled_utterances.add(utterance_id)
            if self._active_utterance_id == utterance_id:
                self._active_utterance_id = None
                self._active_gesture = None
                self._state = BodyState.INTERRUPTED
        elif resolved_scope == CancelScope.GESTURE:
            self._active_gesture = None
        else:
            if self._active_utterance_id:
                self._cancelled_utterances.add(self._active_utterance_id)
            self._active_utterance_id = None
            self._active_gesture = None
            self._state = BodyState.INTERRUPTED
        return self.snapshot

    def set_health(self, *, sequence: int, health: str) -> RuntimeSnapshot:
        self._accept_sequence(sequence)
        if health not in {"ok", "degraded", "error"}:
            raise EventRejected(f"unsupported health value: {health!r}")
        self._health = health
        if health == "error":
            self._state = BodyState.ERROR
        return self.snapshot
