"""Slice B of the Unity renderer roadmap: live render frames.

One embodiment session per worker, driven by what the chat already does:
a turn starts -> thinking; a tool runs -> waiting_for_tool; a TTS sentence
is synthesized -> speaking with an audio-envelope mouth track derived from
the WAV; the turn ends -> idle; the client interrupts -> interrupted.
Core owns every rule: BodyRigRuntime enforces state and sequence,
EmbodimentScheduler turns snapshots into frames (blink, breath, procedural
motion, mouth), voicerig_adapter derives the mouth track, and
render_frame_to_mapping writes the v0.1 wire. Optional semantic expression
intent crosses ModelRig -> BodyRig only as validated BodyCue v1.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bodyrig.body_cue import BodyCueError, expression_plan_from_body_cue, validate_body_cue  # noqa: E402
from bodyrig.render_frame import render_frame_to_mapping  # noqa: E402
from bodyrig.runtime import BodyRigRuntime, BodyState, CancelScope, EventRejected  # noqa: E402
from bodyrig.scheduler import EmbodimentScheduler, SchedulerError  # noqa: E402
from bodyrig.voicerig_adapter import VoiceRigContractError, wav_envelope_track  # noqa: E402

from . import body_cues  # noqa: E402
from .bodyrig_activation import bodyrig_enabled  # noqa: E402

FRAME_INTERVAL_S = 1 / 20
CLIENT_REPORTABLE_STATES = frozenset({"listening", "idle"})


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


class BodySession:
    """Runtime + scheduler for one body. Thread-safe; events are sequenced."""

    def __init__(self, *, body_id: str, bodyprint_id: str, bodyprint_package: dict[str, Any] | None = None):
        self.body_id = body_id
        self.session_id = f"body-{uuid.uuid4().hex[:12]}"
        self.started_ms = _now_ms()
        self._lock = threading.Lock()
        self._sequence = 0
        self._runtime = BodyRigRuntime(session_id=self.session_id, bodyprint_id=bodyprint_id)
        try:
            self._scheduler = EmbodimentScheduler(
                session_id=self.session_id, bodyprint_id=bodyprint_id,
                bodyprint_package=bodyprint_package,
            )
        except SchedulerError:
            self._scheduler = EmbodimentScheduler(session_id=self.session_id, bodyprint_id=bodyprint_id)
        self._utterance_ends: dict[str, int] = {}
        self._tracks: dict[str, Any] = {}
        self._max_tracks = 16
        self._last_body_cue: dict[str, Any] | None = None

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    @property
    def last_body_cue(self) -> dict[str, Any] | None:
        """Last successfully applied canonical BodyCue, for local proof/debug only."""
        return dict(self._last_body_cue) if self._last_body_cue is not None else None

    # ---- events ------------------------------------------------------------

    def set_state(self, state: str | BodyState, *, utterance_id: str | None = None) -> None:
        resolved_state = str(getattr(state, "value", state))
        with self._lock:
            try:
                self._runtime.apply_state(sequence=self._next(), state=state)
            except EventRejected:
                return
            cue = body_cues.cue_for_state(
                state=resolved_state,
                utterance_id=utterance_id,
                body_id=self.body_id,
            )
            if cue is not None and utterance_id is not None:
                self._apply_body_cue_locked(
                    cue,
                    state=resolved_state,
                    expected_utterance_id=utterance_id,
                )

    def apply_body_cue(
        self,
        cue: Mapping[str, Any],
        *,
        state: str,
        expected_utterance_id: str,
        expected_duration_ms: int | None = None,
    ) -> bool:
        """Public fail-closed semantic boundary used by tests/integration adapters.

        A caller must supply utterance authority. If the cue carries duration_ms,
        it is accepted only when the caller also supplies the matching VoiceRig
        track duration.
        """
        with self._lock:
            return self._apply_body_cue_locked(
                cue,
                state=state,
                expected_utterance_id=expected_utterance_id,
                expected_duration_ms=expected_duration_ms,
            )

    def _apply_body_cue_locked(
        self,
        cue: Mapping[str, Any],
        *,
        state: str,
        expected_utterance_id: str,
        expected_duration_ms: int | None = None,
    ) -> bool:
        try:
            checked = validate_body_cue(cue)
        except BodyCueError:
            return False
        if checked.get("body_id") not in (None, self.body_id):
            return False
        if not expected_utterance_id or checked["utterance_id"] != expected_utterance_id:
            return False
        if "duration_ms" in checked:
            if expected_duration_ms is None or checked["duration_ms"] != expected_duration_ms:
                return False
        if state == BodyState.SPEAKING.value:
            active = self._runtime.snapshot.active_utterance_id
            if active is None or checked["utterance_id"] != active:
                return False
        try:
            plan = expression_plan_from_body_cue(checked, state=state)
            self._runtime.apply_expression_plan(sequence=self._next(), plan=plan)
        except (BodyCueError, EventRejected):
            return False
        self._last_body_cue = checked
        return True

    def speak(self, *, utterance_id: str, wav_bytes: bytes, headers: dict[str, Any] | None = None,
              sentence: str = "") -> int:
        """Attach synthesized speech and apply only same-utterance BodyCue v1."""
        with self._lock:
            try:
                track = wav_envelope_track(utterance_id=utterance_id, wav_bytes=wav_bytes, headers=headers)
            except VoiceRigContractError:
                return 0
            now = _now_ms()
            self._remember_track(utterance_id, track)
            self._scheduler.attach_speech(track, started_at_ms=now)
            try:
                self._runtime.start_speech(sequence=self._next(), utterance_id=utterance_id)
            except EventRejected:
                return 0
            self._utterance_ends[utterance_id] = now + track.duration_ms
            cue = body_cues.cue_for_speech(
                sentence=sentence,
                utterance_id=utterance_id,
                body_id=self.body_id,
                duration_ms=track.duration_ms,
            )
            if cue is not None:
                self._apply_body_cue_locked(
                    cue,
                    state=BodyState.SPEAKING.value,
                    expected_utterance_id=utterance_id,
                    expected_duration_ms=track.duration_ms,
                )
            return track.duration_ms

    def _remember_track(self, utterance_id: str, track: Any) -> None:
        self._tracks[utterance_id] = track
        while len(self._tracks) > self._max_tracks:
            self._tracks.pop(next(iter(self._tracks)))

    def playback_started(self, utterance_id: str) -> bool:
        """Re-anchor a known sentence's mouth track to actual client playback."""
        with self._lock:
            track = self._tracks.get(utterance_id)
            if track is None:
                return False
            now = _now_ms()
            self._scheduler.attach_speech(track, started_at_ms=now)
            try:
                self._runtime.start_speech(sequence=self._next(), utterance_id=utterance_id)
            except EventRejected:
                return False
            self._utterance_ends[utterance_id] = now + track.duration_ms
            return True

    def playback_ended(self, utterance_id: str) -> bool:
        with self._lock:
            known = utterance_id in self._tracks
            self._utterance_ends.pop(utterance_id, None)
            self._tracks.pop(utterance_id, None)
            try:
                self._runtime.end_speech(sequence=self._next(), utterance_id=utterance_id)
            except EventRejected:
                pass
            return known

    def end_speech(self, utterance_id: str) -> None:
        with self._lock:
            self._utterance_ends.pop(utterance_id, None)
            try:
                self._runtime.end_speech(sequence=self._next(), utterance_id=utterance_id)
            except EventRejected:
                pass

    def interrupt(self) -> None:
        with self._lock:
            for utterance_id in list(self._utterance_ends):
                self._scheduler.cancel_utterance(utterance_id)
            self._utterance_ends.clear()
            self._tracks.clear()
            try:
                self._runtime.cancel(sequence=self._next(), scope=CancelScope.ALL)
            except EventRejected:
                pass
            try:
                self._runtime.apply_state(sequence=self._next(), state=BodyState.INTERRUPTED)
            except EventRejected:
                pass

    # ---- frames ------------------------------------------------------------

    def frame(self, timestamp_ms: int | None = None) -> dict[str, Any]:
        with self._lock:
            now = timestamp_ms if timestamp_ms is not None else _now_ms()
            for utterance_id, end in list(self._utterance_ends.items()):
                if now >= end:
                    self._utterance_ends.pop(utterance_id, None)
                    try:
                        self._runtime.end_speech(sequence=self._next(), utterance_id=utterance_id)
                    except EventRejected:
                        pass
            frame = self._scheduler.render(self._runtime.snapshot, timestamp_ms=now)
            return render_frame_to_mapping(frame)


_session: BodySession | None = None
_session_lock = threading.Lock()


def _bodyprint_of(active: Any) -> tuple[str, dict[str, Any] | None]:
    bodyprint = dict(active.stored.inspection.bodyprint)
    bodyprint_id = str(bodyprint.get("id") or bodyprint.get("bodyprint_id") or active.body_id)
    return bodyprint_id, bodyprint


def current_session(create: bool = True) -> BodySession | None:
    global _session
    from .body_assets import resolve_active_body
    try:
        active = resolve_active_body(max_age_s=2.0)
    except HTTPException:
        return None
    with _session_lock:
        if _session is None or _session.body_id != active.body_id:
            if not create:
                return None
            bodyprint_id, package = _bodyprint_of(active)
            _session = BodySession(body_id=active.body_id, bodyprint_id=bodyprint_id, bodyprint_package=package)
        return _session


def _session_headers(session: BodySession) -> dict[str, str]:
    return {
        "X-BodyRig-Body-ID": session.body_id,
        "X-BodyRig-Session-ID": session.session_id,
    }


# ---- hooks used by the chat and voice paths (never raise into them) --------

def note_state(state: str, *, utterance_id: str | None = None) -> None:
    if not bodyrig_enabled():
        return
    try:
        session = current_session(create=True)
        if session is not None:
            session.set_state(state, utterance_id=utterance_id)
    except Exception:
        pass


def note_speech(*, utterance_id: str, wav_path: str, headers: dict[str, Any] | None = None,
                sentence: str = "") -> None:
    if not bodyrig_enabled():
        return
    try:
        session = current_session(create=True)
        if session is None:
            return
        with open(wav_path, "rb") as fh:
            session.speak(utterance_id=utterance_id, wav_bytes=fh.read(), headers=headers, sentence=sentence)
    except Exception:
        pass


# ---- HTTP -----------------------------------------------------------------

def build_body_session_router() -> APIRouter:
    router = APIRouter(prefix="/body", tags=["body"])

    @router.get("/state")
    def state() -> JSONResponse:
        session = current_session(create=True)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body")
        return JSONResponse(session.frame(), headers=_session_headers(session))

    @router.post("/interrupt")
    def interrupt() -> JSONResponse:
        session = current_session(create=False)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body session")
        session.interrupt()
        return JSONResponse({"ok": True, "state": session.frame()["state"]})

    @router.post("/state/{name}")
    def set_state(name: str) -> JSONResponse:
        if name not in CLIENT_REPORTABLE_STATES:
            raise HTTPException(status_code=422, detail="state is not client-reportable")
        session = current_session(create=True)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body")
        session.set_state(name)
        return JSONResponse({"ok": True, "state": session.frame()["state"]})

    @router.post("/speech/{utterance_id}/started")
    def speech_started(utterance_id: str) -> JSONResponse:
        session = current_session(create=False)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body session")
        if not session.playback_started(utterance_id):
            raise HTTPException(status_code=404, detail="unknown utterance")
        return JSONResponse({"ok": True, "state": session.frame()["state"]})

    @router.post("/speech/{utterance_id}/ended")
    def speech_ended(utterance_id: str) -> JSONResponse:
        session = current_session(create=False)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body session")
        session.playback_ended(utterance_id)
        return JSONResponse({"ok": True, "state": session.frame()["state"]})

    @router.get("/frames")
    async def frames(limit: int | None = None) -> StreamingResponse:
        session = current_session(create=True)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body")
        if limit is not None and limit < 1:
            raise HTTPException(status_code=422, detail="limit must be >= 1")

        async def generate() -> AsyncIterator[bytes]:
            sent = 0
            while limit is None or sent < limit:
                current = current_session(create=False) or session
                yield ("data: " + json.dumps(current.frame(), separators=(",", ":")) + "\n\n").encode("utf-8")
                sent += 1
                if limit is not None and sent >= limit:
                    break
                await asyncio.sleep(FRAME_INTERVAL_S)

        headers = {
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            **_session_headers(session),
        }
        return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)

    return router
