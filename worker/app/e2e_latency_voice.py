"""Default-off real-event voice qualification for #2063.

This route is intentionally separate from normal voice chat. It proves one
causal chain:
ASR perception -> canonical reported user-turn -> exact cognition RUN ->
C23 response_intent -> TTS utterance -> phone playback-start receipt.

It does not claim physical PASS until the phone actually calls /started.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import body_session, voice_asr, voice_tts
from .consciousness_core.profile_source import load_cognitive_profile
from .consciousness_core.session_lifecycle import ProductionCognitiveSession
from .e2e_latency_runtime import EndToEndLatencyObserver

FLAG = "KALIV_E2E_LATENCY_QUALIFICATION_ENABLED"
SHA_ENV = "KALIV_E2E_LATENCY_CANDIDATE_GIT_SHA"
ROOT_ENV = "KALIV_E2E_LATENCY_EVIDENCE_ROOT"
_MOUNTED = "e2e_latency_voice_mounted"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class QualificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    audio_base64: str = Field(min_length=1, max_length=32 * 1024 * 1024)
    language: str = Field(default="da", min_length=1, max_length=16)


def enabled() -> bool:
    return os.getenv(FLAG, "0") == "1"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/experimental/e2e-latency", tags=["experimental-e2e-latency"])

    @router.post("/voice")
    async def qualify_voice(body: QualificationBody, request: Request) -> dict[str, Any]:
        candidate = os.getenv(SHA_ENV, "")
        root_raw = os.getenv(ROOT_ENV, "")
        if _SHA40.fullmatch(candidate) is None or not root_raw:
            raise HTTPException(status_code=503, detail="qualification environment unavailable")
        root = Path(root_raw).resolve()
        if not voice_asr.is_available() or not voice_tts.is_available():
            raise HTTPException(status_code=503, detail="voice qualification backend unavailable")

        cognitive = getattr(request.app.state, "consciousness_session", None)
        if not isinstance(cognitive, ProductionCognitiveSession):
            raise HTTPException(status_code=503, detail="consciousness session unavailable")
        loaded = load_cognitive_profile()
        if loaded is None:
            raise HTTPException(status_code=503, detail="qualification cognitive profile unavailable")
        if body_session.current_session(create=True) is None:
            raise HTTPException(status_code=503, detail="qualification body session unavailable")

        try:
            audio = base64.b64decode(body.audio_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid qualification audio") from exc
        if not audio:
            raise HTTPException(status_code=422, detail="invalid qualification audio")

        qid = "e2e-" + uuid.uuid4().hex
        # The end-to-end clock starts when one bounded real audio input has been
        # accepted by the worker, before evidence-file IO, ASR, cognition or TTS.
        # Sampling after ASR would under-report the user-visible latency.
        perception_sample = cognitive.trusted_clock.sample()

        evidence_dir = root / qid
        audio_path = evidence_dir / "input.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=False)
        audio_path.write_bytes(audio)

        try:
            asr = await asyncio.to_thread(voice_asr.transcribe_wav, str(audio_path), body.language)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="qualification ASR failed") from exc
        transcript = str(asr.get("text") or "").strip()
        if not transcript:
            raise HTTPException(status_code=409, detail="qualification ASR produced no speech")

        admission = cognitive.submit_reported_user_turn(
            turn_id=qid,
            user_text=transcript,
            source_ref="voice-asr:" + qid,
        )
        event = admission.cognition_event
        if event is None or not admission.cognition_event_queued:
            raise HTTPException(status_code=409, detail="qualification event was not newly admitted")

        observer = EndToEndLatencyObserver(
            candidate_git_sha=candidate,
            event_id=event.event_id,
            observer_id=qid,
            clock=cognitive.trusted_clock,
        )
        perception = observer.perception_received(
            input_kind="voice-audio",
            input_id=qid,
            sample=perception_sample,
        )

        try:
            step = await cognitive.step(
                profile=loaded.profile,
                required_event_id=event.event_id,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail="qualification cognition failed") from exc
        plan = step.supervisor_step.plan
        if plan.decision != "RUN" or event.event_id not in plan.selected_event_ids:
            raise HTTPException(status_code=409, detail="qualification event did not RUN exactly")
        transition_ref = step.live_state.last_transition_receipt_ref
        if not transition_ref or step.live_state.completed_cycles < 1:
            raise HTTPException(status_code=409, detail="qualification cognition lacks transition proof")

        cognition = observer.cognition_completed(
            transition_receipt_ref=transition_ref,
            completed_cycles=step.live_state.completed_cycles,
        )
        guidance = cognitive.consume_response_guidance(user_turn_event_id=event.event_id)
        if guidance is None or not guidance.text.strip():
            raise HTTPException(status_code=409, detail="qualification cognition produced no outward guidance")

        wav_path = evidence_dir / "reply.wav"
        try:
            tts = await asyncio.to_thread(voice_tts.synthesize_to_wav, guidance.text, str(wav_path))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="qualification TTS failed") from exc
        utterance_id = qid + "-0"
        body_session.note_speech(
            utterance_id=utterance_id,
            wav_path=str(wav_path),
            headers=tts if isinstance(tts, dict) else None,
            sentence=guidance.text,
        )
        body_runtime = body_session.current_session(create=False)
        if body_runtime is None:
            raise HTTPException(status_code=503, detail="qualification body session unavailable")

        outward_path = evidence_dir / "outward_started.json"
        if not body_runtime.bind_e2e_outward(
            utterance_id=utterance_id,
            outward_receipt_path=str(outward_path),
            outward_clock_sample=cognitive.trusted_clock.sample,
            **observer.outward_binding(),
        ):
            raise HTTPException(status_code=503, detail="qualification outward binding unavailable")

        perception_path = evidence_dir / "perception_received.json"
        cognition_path = evidence_dir / "cognition_completed.json"
        _atomic_json(perception_path, perception)
        _atomic_json(cognition_path, cognition)

        return {
            "schema": "kaliv-system/end-to-end-latency-voice-turn/v1",
            "qualification_id": qid,
            "event_id": event.event_id,
            "runtime_epoch": observer.runtime_epoch,
            "observer_id": observer.observer_id,
            "utterance_id": utterance_id,
            "audio_base64": base64.b64encode(wav_path.read_bytes()).decode("ascii"),
            "source_receipts": {
                "perception": str(perception_path),
                "cognition": str(cognition_path),
                "outward": str(outward_path),
            },
            "outward_started": False,
            "release_gate_satisfied": False,
            "production_activation": False,
        }

    return router


def mount(app: FastAPI) -> bool:
    if not enabled():
        return False
    if getattr(app.state, _MOUNTED, False):
        return True
    app.include_router(build_router())
    setattr(app.state, _MOUNTED, True)
    return True
