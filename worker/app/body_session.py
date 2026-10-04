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
import os
import re
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

from . import body_cues  # noqa: E402

FRAME_INTERVAL_S = 1 / 20
CLIENT_REPORTABLE_STATES = frozenset({"listening", "idle"})
E2E_LATENCY_QUALIFICATION_FLAG = "KALIV_E2E_LATENCY_QUALIFICATION_ENABLED"
_E2E_SOURCE_SCHEMA = "kaliv-system/end-to-end-latency-source/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_EVENT_ID = re.compile(r"^cevt-[a-f0-9]{32}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


def e2e_latency_qualification_enabled() -> bool:
    """Only exact opt-in permits runtime correlation evidence."""
    return os.getenv(E2E_LATENCY_QUALIFICATION_FLAG, "0") == "1"


def _bounded_token(value: str, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded token")
    return value


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
        # Tracks kept for playback re-anchoring: the phone reports when it
        # actually starts playing a sentence, and the mouth restarts from
        # there. Bounded; a few sentences is all a turn ever needs in flight.
        self._tracks: dict[str, Any] = {}
        self._max_tracks = 16
        # Qualification-only correlation. Normal voice/body behavior never
        # consults this map. The worker qualification path may bind a canonical
        # cognition event to an utterance before the phone can report playback.
        self._e2e_outward_bindings: dict[str, dict[str, Any]] = {}
        self._e2e_outward_receipts: dict[str, dict[str, Any]] = {}

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
            plan = body_cues.plan_for_state(str(getattr(state, "value", state)))
            if plan is not None:
                self._apply_plan(plan)

    def _apply_plan(self, plan: dict[str, Any]) -> None:
        # Cues are best effort: a plan the runtime rejects is dropped, the
        # state it came with stands.
        try:
            self._runtime.apply_expression_plan(sequence=self._next(), plan=plan)
        except EventRejected:
            pass

    def speak(self, *, utterance_id: str, wav_bytes: bytes, headers: dict[str, Any] | None = None,
              sentence: str = "") -> int:
        """Attach a synthesized sentence and enter SPEAKING. Returns the track
        duration in ms so the caller can end the utterance when it is over."""
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
            plan = body_cues.plan_for_speech(sentence)
            if plan is not None:
                self._apply_plan(plan)
            return track.duration_ms

    def _remember_track(self, utterance_id: str, track: Any) -> None:
        self._tracks[utterance_id] = track
        while len(self._tracks) > self._max_tracks:
            self._tracks.pop(next(iter(self._tracks)))

    def bind_e2e_outward(
        self,
        *,
        utterance_id: str,
        candidate_git_sha: str,
        cognition_event_id: str,
        runtime_epoch: str,
        observer_id: str,
        outward_receipt_path: str | None = None,
    ) -> bool:
        """Bind one worker-authored cognition event to one synthesized utterance.

        This is deliberately not an HTTP surface. Android reports only playback
        truth; it never supplies candidate/event/observer identity.
        """
        if not e2e_latency_qualification_enabled():
            return False
        if utterance_id not in self._tracks:
            return False
        if _SHA40.fullmatch(candidate_git_sha) is None:
            raise ValueError("candidate_git_sha must be lowercase 40-hex")
        if _EVENT_ID.fullmatch(cognition_event_id) is None:
            raise ValueError("cognition_event_id must be canonical")
        _bounded_token(runtime_epoch, "runtime_epoch")
        _bounded_token(observer_id, "observer_id")
        with self._lock:
            if utterance_id not in self._tracks:
                return False
            existing = self._e2e_outward_bindings.get(utterance_id)
            receipt_path = None
            if outward_receipt_path is not None:
                if not isinstance(outward_receipt_path, str) or not outward_receipt_path.strip():
                    raise ValueError("outward_receipt_path must be nonblank")
                receipt_path = str(Path(outward_receipt_path).resolve())
            binding = {
                "candidate_git_sha": candidate_git_sha,
                "event_id": cognition_event_id,
                "runtime_epoch": runtime_epoch,
                "observer_id": observer_id,
                "outward_receipt_path": receipt_path,
            }
            if existing is not None and existing != binding:
                raise ValueError("utterance already bound to another qualification event")
            self._e2e_outward_bindings[utterance_id] = binding
            return True

    def e2e_outward_receipt(self, utterance_id: str) -> dict[str, Any] | None:
        with self._lock:
            receipt = self._e2e_outward_receipts.get(utterance_id)
            return None if receipt is None else dict(receipt)

    def playback_started(self, utterance_id: str) -> bool:
        """The client began playing this sentence NOW: restart its mouth track
        from this instant. Returns False for an utterance the session does not
        know (never synthesized here, or long gone)."""
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
            binding = self._e2e_outward_bindings.get(utterance_id)
            if binding is not None:
                receipt = {
                    "schema": _E2E_SOURCE_SCHEMA,
                    "phase": "outward_started",
                    "candidate_git_sha": binding["candidate_git_sha"],
                    "event_id": binding["event_id"],
                    "runtime_epoch": binding["runtime_epoch"],
                    "observer_id": binding["observer_id"],
                    "clock": {
                        "kind": "monotonic",
                        "unit": "milliseconds",
                        "origin": "single-observer",
                    },
                    "observed_at_ms": now,
                    "real_event": True,
                    "simulated": False,
                    "replay": False,
                    "details": {
                        "outward_kind": "voice+body",
                        "started": True,
                        "utterance_id": utterance_id,
                        "body_runtime_id": self.session_id,
                    },
                    "production_activation": False,
                }
                self._e2e_outward_receipts[utterance_id] = receipt
                receipt_path = binding.get("outward_receipt_path")
                if receipt_path:
                    path = Path(receipt_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
                    tmp.write_text(
                        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    os.replace(tmp, path)
            return True

    def playback_ended(self, utterance_id: str) -> bool:
        with self._lock:
            known = utterance_id in self._tracks
            self._utterance_ends.pop(utterance_id, None)
            self._tracks.pop(utterance_id, None)
            self._e2e_outward_bindings.pop(utterance_id, None)
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
        """Hard interruption: cancel everything, clear the mouth, go INTERRUPTED."""
        with self._lock:
            for utterance_id in list(self._utterance_ends):
                self._scheduler.cancel_utterance(utterance_id)
            self._utterance_ends.clear()
            self._tracks.clear()
            self._e2e_outward_bindings.clear()
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
            # The SSE data payload is exactly BodyRig RenderFrame v0.1. Stream
            # identity is HTTP metadata; adding it here would violate the
            # canonical schema's additionalProperties:false contract.
            return render_frame_to_mapping(frame)


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
        # Two seconds of staleness on WHICH body is active is invisible; a
        # full archive re-validation per frame is not.
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
    """Identity for one canonical frame response/stream, outside the v0.1 payload."""
    return {
        "X-BodyRig-Body-ID": session.body_id,
        "X-BodyRig-Session-ID": session.session_id,
    }


# ---- hooks used by the chat and voice paths (never raise into them) --------

def note_state(state: str) -> None:
    try:
        session = current_session(create=True)
        if session is not None:
            session.set_state(state)
    except Exception:
        pass


def note_speech(*, utterance_id: str, wav_path: str, headers: dict[str, Any] | None = None,
                sentence: str = "") -> None:
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
        # For the client to report what only it knows -- listening while the
        # mic is open, idle when the user walked away. Nothing else: thinking
        # and waiting_for_tool come from the turn, speaking from a synthesized
        # sentence, interrupted from /interrupt, error from a failure. A client
        # cannot declare the body to be speaking with no mouth to speak.
        if name not in CLIENT_REPORTABLE_STATES:
            raise HTTPException(status_code=422, detail="state is not client-reportable")
        session = current_session(create=True)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body")
        session.set_state(name)
        return JSONResponse({"ok": True, "state": session.frame()["state"]})

    @router.post("/speech/{utterance_id}/started")
    def speech_started(utterance_id: str) -> JSONResponse:
        # Playback truth from the phone: the mouth restarts from this instant.
        session = current_session(create=False)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body session")
        if not session.playback_started(utterance_id):
            raise HTTPException(status_code=404, detail="unknown utterance")
        payload: dict[str, Any] = {"ok": True, "state": session.frame()["state"]}
        receipt = session.e2e_outward_receipt(utterance_id)
        if receipt is not None:
            payload["qualification_outward_receipt"] = receipt
        return JSONResponse(payload)

    @router.post("/speech/{utterance_id}/ended")
    def speech_ended(utterance_id: str) -> JSONResponse:
        session = current_session(create=False)
        if session is None:
            raise HTTPException(status_code=404, detail="no active body session")
        session.playback_ended(utterance_id)
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

        headers = {
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            **_session_headers(session),
        }
        return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)

    return router
