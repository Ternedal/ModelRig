"""Slice B of the Unity renderer roadmap: live render frames.

One embodiment session per worker, driven by what the chat already does:
a turn starts -> thinking; a tool runs -> waiting_for_tool; a TTS sentence
is synthesized -> speaking with an audio-envelope mouth track derived from
the WAV; the turn ends -> idle; the client interrupts -> interrupted.
Core owns every rule: BodyRigRuntime enforces state and sequence,
EmbodimentScheduler turns snapshots into frames (blink, breath, procedural
motion, mouth), voicerig_adapter derives the mouth track, and
render_frame_to_mapping writes the v0.1 wire. This module only sequences
events and hands frames out.

Honest limits, on purpose: with no active body the session is a no-op and
/body/frames answers 404; speech timing is synthesis time on the rig, not
playback time on the phone (a client may report playback start later);
and no emotion/gesture classification happens here -- frames say neutral
until a cue slice supplies more.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bodyrig.render_frame import render_frame_to_mapping  # noqa: E402
from bodyrig.runtime import BodyRigRuntime, BodyState, CancelScope, EventRejected  # noqa: E402
from bodyrig.scheduler import EmbodimentScheduler, SchedulerError  # noqa: E402
from bodyrig.voicerig_adapter import VoiceRigContractError, wav_envelope_track  # noqa: E402

FRAME_INTERVAL_S = 1 / 20


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
            # A bodyprint the motion mixer will not take must not stop the
            # body from moving at all: fall back to generic motion.
            self._scheduler = EmbodimentScheduler(session_id=self.session_id, bodyprint_id=bodyprint_id)
        self._utterance_ends: dict[str, int] = {}

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    # ---- events ------------------------------------------------------------

    def set_state(self, state: str | BodyState) -> None:
        with self._lock:
            try:
                self._runtime.apply_state(sequence=self._next(), state=state)
            except EventRejected:
                pass

    def speak(self, *, utterance_id: str, wav_bytes: bytes, headers: dict[str, Any] | None = None) -> int:
        """Attach a synthesized sentence and enter SPEAKING. Returns the track
        duration in ms so the caller can end the utterance when it is over."""
        with self._lock:
            try:
                track = wav_envelope_track(utterance_id=utterance_id, wav_bytes=wav_bytes, headers=headers)
            except VoiceRigContractError:
                return 0
            now = _now_ms()
            self._scheduler.attach_speech(track, started_at_ms=now)
            try:
                self._runtime.start_speech(sequence=self._next(), utterance_id=utterance_id)
            except EventRejected:
                return 0
            self._utterance_ends[utterance_id] = now + track.duration_ms
            return track.duration_ms

    def end_speech(self, utterance_id: str) -> None:
        with self._lock:
            self._utterance_ends.pop(utterance_id, None)
            try:
                self._runtime.end_speech(sequence=self._next(), utterance_id=utterance_id)
            except EventRejected:
                pass

    def interrupt(self) -> None:
        """Hard interruption: cancel everything, clear the mouth, go INTERRUPTED."""
        with self._lock:
            for utterance_id in list(self._utterance_ends):
                self._scheduler.cancel_utterance(utterance_id)
            self._utterance_ends.clear()
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
            # Utterances whose track has run out end themselves: the runtime
            # must not stay SPEAKING with a silent mouth.
            for utterance_id, end in list(self._utterance_ends.items()):
                if now >= end:
                    self._utterance_ends.pop(utterance_id, None)
                    try:
                        self._runtime.end_speech(sequence=self._next(), utterance_id=utterance_id)
                    except EventRejected:
                        pass
            frame = self._scheduler.render(self._runtime.snapshot, timestamp_ms=now)
            payload = render_frame_to_mapping(frame)
            payload["session_id"] = self.session_id
            payload["body_id"] = self.body_id
            return payload


_session: BodySession | None = None
_session_lock = threading.Lock()


def _bodyprint_of(active: Any) -> tuple[str, dict[str, Any] | None]:
    bodyprint = dict(active.stored.inspection.bodyprint)
    bodyprint_id = str(bodyprint.get("id") or bodyprint.get("bodyprint_id") or active.body_id)
    return bodyprint_id, bodyprint


def current_session(create: bool = True) -> BodySession | None:
    """The session for the active body, created on first use and replaced
    when the active body changes. None when no body is active."""
    global _session
    from .body_assets import resolve_active_body
    try:
        active = resolve_active_body()
    except HTTPException:
        return None
    with _session_lock:
        if _session is None or _session.body_id != active.body_id:
            if not create:
                return None
            bodyprint_id, package = _bodyprint_of(active)
            _session = BodySession(body_id=active.body_id, bodyprint_id=bodyprint_id, bodyprint_package=package)
        return _session


# ---- hooks used by the chat and voice paths (never raise into them) --------

def note_state(state: str) -> None:
    try:
        session = current_session(create=True)
        if session is not None:
            session.set_state(state)
    except Exception:
        pass


def note_speech(*, utterance_id: str, wav_path: str, headers: dict[str, Any] | None = None) -> None:
    try:
        session = current_session(create=True)
        if session is None:
            return
        with open(wav_path, "rb") as fh:
            session.speak(utterance_id=utterance_id, wav_bytes=fh.read(), headers=headers)
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
        return JSONResponse(session.frame())

    @router.post("/interrupt")
    def interrupt() -> JSONResponse:
        session = current_session(create=False)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body session")
        session.interrupt()
        return JSONResponse({"ok": True, "state": session.frame()["state"]})

    @router.post("/state/{name}")
    def set_state(name: str) -> JSONResponse:
        # For the client to report what only it knows -- listening while the
        # mic is open, idle when the user walked away.
        if name not in {s.value for s in BodyState}:
            raise HTTPException(status_code=422, detail="unknown body state")
        session = current_session(create=True)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body")
        session.set_state(name)
        return JSONResponse({"ok": True, "state": session.frame()["state"]})

    @router.get("/frames")
    async def frames(limit: int | None = None) -> StreamingResponse:
        # limit: stop after N frames. For tests and one-shot probes; a
        # renderer leaves it out and reads until it disconnects.
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

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return router
