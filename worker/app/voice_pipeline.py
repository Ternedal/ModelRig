"""Alva Voice — pipeline orchestration (ASR -> LLM -> TTS).

Phase 3 of the Alva Voice MVP (V-MVP.3 in ALVA_VOICE_ROADMAP_DELTA.md). Ties
the two building blocks (voice_asr, voice_tts) together with the existing
streaming Ollama client into one spoken turn:

    audio in --ASR--> Danish text --LLM(stream)--> tokens
      --sentence chunk--> per-sentence TTS --> audio chunks out

THE KEY METRIC is time-to-first-audio: as the LLM streams, we split on sentence
boundaries (. ! ?) and synthesize each COMPLETE sentence immediately, instead
of waiting for the whole reply. So Alva can start speaking the first sentence
while the LLM is still generating the rest. This module measures and returns
that first-audio latency.

This is a RIG-SIDE orchestration for terminal testing -- it writes a WAV per
sentence and reports timings. The Android layer (mic capture, live playback,
barge-in) sits on top of this later and is only testable on the phone.

Optional, like the other Voice modules: if faster-whisper or piper-tts isn't
installed, the endpoint returns a clean 501. NOT YET HARDWARE-TESTED -- this is
the third untested Voice layer; the full chain (does it actually hear you,
answer, and speak, and how fast?) can only be proven on Anders' rig.
"""
from __future__ import annotations

import os
import re
import time

from . import ollama_client as oc
from . import voice_asr
from . import voice_tts

# Split point: end-of-sentence punctuation followed by space/end. Keeping it
# simple for the MVP -- Danish abbreviations (f.eks., bl.a.) can cause an early
# split, which is acceptable for a first spoken chunk (worst case: a slightly
# short first utterance). A proper Danish text normalizer is a phase-2 item.
_SENTENCE_END = re.compile(r"([.!?])(\s|$)")


def _extract_delta(ndjson_line: bytes) -> str:
    """Pull the incremental message content out of one Ollama NDJSON line."""
    import json
    try:
        obj = json.loads(ndjson_line.decode().strip())
    except Exception:
        return ""
    msg = obj.get("message") or {}
    return msg.get("content", "") or ""


async def converse(
    audio_path: str,
    language: str = "da",
    model: str | None = None,
    out_dir: str = "/tmp/alva_voice",
    llm_base_url: str | None = None,
    llm_api_key: str | None = None,
) -> dict:
    """Run one full spoken turn from an audio file.

    llm_base_url/llm_api_key optionally point the LLM step at a DIFFERENT Ollama
    upstream -- specifically Ollama Cloud -- so a spoken question can be answered
    by a large cloud model while ASR and TTS stay local on the rig. ASR/TTS
    cannot move: the models live here. The key is used for this call only and is
    never persisted.

    Returns:
      {
        transcript, reply, model, language,
        time_to_first_audio_s,   # from LLM start to first sentence WAV ready
        total_s,                 # whole pipeline
        chunks: [{index, text, wav, synth_s}],
      }
    Raises RuntimeError (surfaced as 501 by the endpoint) if a Voice backend
    isn't installed.
    """
    if not voice_asr.is_available():
        raise RuntimeError("ASR not enabled (pip install faster-whisper)")
    if not voice_tts.is_available():
        raise RuntimeError("TTS not enabled (pip install piper-tts)")
    os.makedirs(out_dir, exist_ok=True)
    t_start = time.time()

    # 1. ASR: audio -> Danish text.
    asr = voice_asr.transcribe_wav(audio_path, language=language)
    transcript = asr["text"]

    # 2+3+4. Stream the LLM; chunk on sentence boundaries; TTS each sentence as
    # soon as it completes, so first audio is ready ASAP.
    messages = [{"role": "user", "content": transcript}]
    buffer = ""
    reply_parts: list[str] = []
    chunks: list[dict] = []
    first_audio_at: float | None = None
    llm_start = time.time()

    async def _synth(sentence: str, idx: int) -> None:
        nonlocal first_audio_at
        wav = os.path.join(out_dir, f"chunk_{idx:03d}.wav")
        s0 = time.time()
        voice_tts.synthesize_to_wav(sentence, wav)
        synth_s = round(time.time() - s0, 2)
        if first_audio_at is None:
            first_audio_at = time.time()
        chunks.append({"index": idx, "text": sentence, "wav": wav, "synth_s": synth_s})

    idx = 0
    async for line in oc.chat_stream(messages, model=model,
                                    base_url=llm_base_url, api_key=llm_api_key):
        delta = _extract_delta(line)
        if not delta:
            continue
        buffer += delta
        reply_parts.append(delta)
        # Emit every complete sentence currently in the buffer.
        while True:
            m = _SENTENCE_END.search(buffer)
            if not m:
                break
            end = m.end()
            sentence = buffer[:end].strip()
            buffer = buffer[end:]
            if sentence:
                await _synth(sentence, idx)
                idx += 1
    # Flush any trailing text with no terminal punctuation.
    tail = buffer.strip()
    if tail:
        await _synth(tail, idx)

    reply = "".join(reply_parts).strip()
    ttfa = round((first_audio_at - llm_start), 2) if first_audio_at else None
    return {
        "transcript": transcript,
        "reply": reply,
        "model": model or oc.GEN_MODEL,
        "language": asr["language"],
        "time_to_first_audio_s": ttfa,
        "total_s": round(time.time() - t_start, 2),
        "chunks": chunks,
    }
