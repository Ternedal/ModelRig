"""Kaliv Voice — pipeline orchestration (ASR -> LLM -> TTS).

Phase 3 of the Kaliv Voice MVP (V-MVP.3 in ALVA_VOICE_ROADMAP_DELTA.md). Ties
the two building blocks (voice_asr, voice_tts) together with the existing
streaming Ollama client into one spoken turn:

    audio in --ASR--> Danish text --LLM(stream)--> tokens
      --sentence chunk--> per-sentence TTS --> audio chunks out

THE KEY METRIC is time-to-first-audio: as the LLM streams, we split on sentence
boundaries (. ! ?) and synthesize each COMPLETE sentence immediately, instead
of waiting for the whole reply. So Kaliv can start speaking the first sentence
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

import asyncio
import os
import re
import time
from typing import Awaitable, Callable

from . import ollama_client as oc
from . import voice_asr
from . import voice_tts


class VoiceBackendMissing(RuntimeError):
    """An optional Voice backend (faster-whisper / piper-tts) is not installed.

    Split out from plain RuntimeError so the endpoints can answer an honest 501
    (feature not enabled on this rig) for THIS case only. Every other
    RuntimeError from the pipeline means the backend IS installed but failed to
    load or run (voice model file missing, wrong voices dir, CUDA DLLs) --
    that's a 503. Conflating the two behind one status code cost an evening of
    debugging on 2026-07-09: isolated cmd-window tests passed while the worker
    kept answering 501, and nothing ever said why.
    """

# Split point: end-of-sentence punctuation followed by space/end. Keeping it
# simple for the MVP -- Danish abbreviations (f.eks., bl.a.) can cause an early
# split, which is acceptable for a first spoken chunk (worst case: a slightly
# short first utterance). A proper Danish text normalizer is a phase-2 item.
_SENTENCE_END = re.compile(r"([.!?])(\s|$)")

# --- Markdown -> speakable text ---------------------------------------------
# The LLM writes markdown (**bold**, `code`, - bullets, ### headings). Piper
# reads it literally, so Kaliv says "stjerne stjerne" out loud. Anders hit this
# on 2026-07-09. We strip formatting from what is SPOKEN; the chat still shows
# the original markdown.
#
# Deliberately conservative: only strip markers where they're unambiguously
# formatting, so ordinary text survives ("5 * 3" keeps its asterisk, and a
# lone underscore in a filename isn't touched).

_MD_CODE_FENCE = re.compile(r"```[\s\S]*?```")          # fenced blocks: drop entirely
_MD_INLINE_CODE = re.compile(r"`([^`\n]+)`")             # `code` -> code
_MD_BOLD_ITALIC = re.compile(r"(\*{1,3})(\S(?:.*?\S)?)\1")  # **x** *x* ***x*** -> x
_MD_UNDERSCORE = re.compile(r"(?<!\w)(_{1,3})(\S(?:.*?\S)?)\1(?!\w)")  # _x_ -> x
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)  # ### Title -> Title
_MD_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)   # - item -> item
_MD_NUMLIST = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)  # 1. item -> item
_MD_BLOCKQUOTE = re.compile(r"^\s*>\s?", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")          # [text](url) -> text
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")        # ![alt](url) -> alt
_MD_HRULE = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$", re.MULTILINE)
_MD_TABLE_PIPE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)  # table rows: drop
_WS = re.compile(r"[ \t]{2,}")

# Emojis and pictographs: Piper can't pronounce them, so it says the Unicode name
# or emits noise. The chat still shows them; the SPOKEN text drops them. (Anders
# hit this 2026-07-13: emojis stripped from the display were still read aloud,
# because the audio path never removed them.) Covers the standard emoji blocks --
# all high Unicode, so Danish text, digits and punctuation (<= U+00FF / ASCII)
# are untouched.
_EMOJI = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "\U0001F300-\U0001F5FF"  # misc symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F9FF"  # alchemical .. supplemental pictographs
    "\U0001FA00-\U0001FAFF"  # extended-A (chess, tools, etc.)
    "\U00002300-\U000023FF"  # misc technical (watch, hourglass, keyboard)
    "\U00002600-\U000026FF"  # misc symbols (sun, star, warning, ...)
    "\U00002700-\U000027BF"  # dingbats (check mark, sparkles, arrows)
    "\U00002B00-\U00002BFF"  # misc symbols & arrows (star, arrows)
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner (emoji sequences)
    "]+"
)


# One at a time, per backend. Not for safety against Anders -- he is one user --
# but because the model objects are shared, and because two Whisper decodes on a
# 12 GB card is how you meet an out-of-memory error at the worst moment.
_ASR_LOCK = asyncio.Lock()
_TTS_LOCK = asyncio.Lock()


def strip_markdown(text: str) -> str:
    """Turn markdown into something a TTS voice can read naturally.

    Fenced code blocks and table rows are dropped rather than spoken -- reading
    a table aloud pipe by pipe is worse than silence. Everything else keeps its
    words and loses its markers.
    """
    t = text
    t = _MD_CODE_FENCE.sub(" ", t)
    t = _MD_TABLE_PIPE.sub(" ", t)
    t = _MD_HRULE.sub(" ", t)
    t = _MD_IMAGE.sub(r"\1", t)
    t = _MD_LINK.sub(r"\1", t)
    t = _MD_INLINE_CODE.sub(r"\1", t)
    t = _MD_BOLD_ITALIC.sub(r"\2", t)
    t = _MD_UNDERSCORE.sub(r"\2", t)
    t = _MD_HEADING.sub("", t)
    t = _MD_BLOCKQUOTE.sub("", t)
    t = _MD_BULLET.sub("", t)
    t = _MD_NUMLIST.sub("", t)
    t = _EMOJI.sub(" ", t)  # emojis are unspeakable; drop them (chat keeps them)
    t = _WS.sub(" ", t)
    return t.strip()


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
    on_chunk: "Callable[[dict], Awaitable[None]] | None" = None,
    on_transcript: "Callable[[str], Awaitable[None]] | None" = None,
) -> dict:
    """Run one full spoken turn from an audio file.

    llm_base_url/llm_api_key optionally point the LLM step at a DIFFERENT Ollama
    upstream -- specifically Ollama Cloud -- so a spoken question can be answered
    by a large cloud model while ASR and TTS stay local on the rig. ASR/TTS
    cannot move: the models live here. The key is used for this call only and is
    never persisted.

    on_transcript, if given, is awaited with the ASR text the moment it's ready
    (before any LLM/TTS), so a streaming caller can show the transcript first.
    on_chunk, if given, is awaited with each sentence chunk dict the moment its
    WAV is synthesized -- this is what lets a streaming endpoint deliver audio
    sentence-by-sentence instead of waiting for the whole reply. The buffered
    caller passes neither and just reads the returned dict.

    Returns:
      {
        transcript, reply, model, language,
        time_to_first_audio_s,   # from LLM start to first sentence WAV ready
        total_s,                 # whole pipeline
        chunks: [{index, text, wav, synth_s}],
      }
    Raises VoiceBackendMissing (-> 501) if a backend isn't installed; any
    other RuntimeError (-> 503, logged in the worker console) if a Voice backend
    isn't installed.
    """
    if not voice_asr.is_available():
        raise VoiceBackendMissing("ASR not enabled (pip install faster-whisper)")
    if not voice_tts.is_available():
        raise VoiceBackendMissing("TTS not enabled (pip install piper-tts)")
    os.makedirs(out_dir, exist_ok=True)
    t_start = time.time()

    # 1. ASR: audio -> Danish text.
    #
    # transcribe_wav is seconds of blocking CUDA work. Called inline from an
    # async handler it froze the entire worker for its duration -- healthz,
    # RAG, every other request. Offloaded to a thread, but SERIALIZED: the
    # event loop used to serialize these by accident, and the faster-whisper
    # model is shared state. Keep the serialization; drop the freeze.
    async with _ASR_LOCK:
        asr = await asyncio.to_thread(voice_asr.transcribe_wav, audio_path, language)
    transcript = asr["text"]
    if on_transcript is not None:
        await on_transcript(transcript)

    # 2+3+4. Stream the LLM; chunk on sentence boundaries; TTS each sentence as
    # soon as it completes, so first audio is ready ASAP.
    messages = [{"role": "user", "content": transcript}]
    buffer = ""
    reply_parts: list[str] = []
    chunks: list[dict] = []
    first_audio_at: float | None = None
    idx = 0
    llm_start = time.time()

    async def _synth(sentence: str) -> None:
        nonlocal first_audio_at, idx
        # Speak the words, not the markup. The chat still shows the original
        # sentence; only the audio gets the stripped version. A sentence that is
        # ENTIRELY markup (a table row, a code fence) strips to nothing -- skip
        # it rather than synthesize an empty WAV.
        speakable = strip_markdown(sentence)
        if not speakable:
            return
        wav = os.path.join(out_dir, f"chunk_{idx:03d}.wav")
        s0 = time.time()
        # Piper is a subprocess and a loaded model: same reasoning as ASR.
        # Serialized so sentences still reach the phone in order.
        async with _TTS_LOCK:
            await asyncio.to_thread(voice_tts.synthesize_to_wav, speakable, wav)
        synth_s = round(time.time() - s0, 2)
        if first_audio_at is None:
            first_audio_at = time.time()
        chunk = {"index": idx, "text": sentence, "wav": wav, "synth_s": synth_s}
        chunks.append(chunk)
        if on_chunk is not None:
            await on_chunk(chunk)
        idx += 1

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
                await _synth(sentence)
    # Flush any trailing text with no terminal punctuation.
    tail = buffer.strip()
    if tail:
        await _synth(tail)

    reply = "".join(reply_parts).strip()
    ttfa = round((first_audio_at - llm_start), 2) if first_audio_at else None
    return {
        "transcript": transcript,
        "reply": reply,
        "model": model or oc.GEN_MODEL,
        # Which brain answered. The app shows this so it's obvious whether the
        # spoken reply came from the rig or from a cloud model.
        "via_cloud": bool(llm_base_url),
        "language": asr["language"],
        "time_to_first_audio_s": ttfa,
        "total_s": round(time.time() - t_start, 2),
        "chunks": chunks,
    }
