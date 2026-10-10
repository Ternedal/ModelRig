"""Regression: overlap TTS and token reception, without unbounded synthesis.

All stubs, no model/GPU/internet. Failed callbacks/LLM must fail closed.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
from app import voice_pipeline as vp  # noqa: E402
from app import ollama_client as oc  # noqa: E402


def wav(path):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00\x00" * 32)


def packet(text):
    return json.dumps({"message": {"content": text}}).encode("utf-8")


class Stubs:
    def __init__(self, *, stream, synth):
        self.stream = stream
        self.synth = synth

    def __enter__(self):
        self.saved = {
            "asr": vp.voice_asr.is_available,
            "tts": vp.voice_tts.is_available,
            "transcribe": vp.voice_asr.transcribe_wav,
            "synth": vp.voice_tts.synthesize_to_wav,
            "stream": oc.chat_stream,
            "body": vp.body_session.note_speech,
        }
        vp.voice_asr.is_available = lambda: True
        vp.voice_tts.is_available = lambda: True
        vp.voice_asr.transcribe_wav = lambda path, language: {
            "text": "testspørgsmål", "language": language,
        }
        vp.voice_tts.synthesize_to_wav = self.synth
        vp.body_session.note_speech = lambda **kwargs: None
        oc.chat_stream = self.stream
        return self

    def __exit__(self, exc_type, exc, tb):
        vp.voice_asr.is_available = self.saved["asr"]
        vp.voice_tts.is_available = self.saved["tts"]
        vp.voice_asr.transcribe_wav = self.saved["transcribe"]
        vp.voice_tts.synthesize_to_wav = self.saved["synth"]
        vp.body_session.note_speech = self.saved["body"]
        oc.chat_stream = self.saved["stream"]


with tempfile.TemporaryDirectory(prefix="voice-overlap-contract-") as directory:
    input_wav = os.path.join(directory, "input.wav")
    wav(input_wav)
    second_token_consumed = threading.Event()
    synthesized = []
    seen = []

    async def early_two(messages, model=None, base_url=None, api_key=None):
        yield packet("Første.")
        # This must run while the first Piper synthesis is still executing.
        await asyncio.sleep(0.015)
        seen.append("second-token-consumed")
        second_token_consumed.set()
        yield packet(" Anden.")

    def delayed_synth(text, path):
        if "Første" in text:
            assert second_token_consumed.wait(2), (
                "LLM consumer blocked on TTS before second token was consumed"
            )
        synthesized.append(text)
        wav(path)
        return {"duration": 0.001}

    callback_chunks = []
    async def chunk(chunk):
        callback_chunks.append(chunk["text"])

    with Stubs(stream=early_two, synth=delayed_synth):
        result = asyncio.run(vp.converse(
            input_wav, out_dir=directory, on_chunk=chunk,
        ))
    assert second_token_consumed.is_set()
    assert synthesized == ["Første.", "Anden."]
    assert callback_chunks == ["Første.", "Anden."]
    assert [c["index"] for c in result["chunks"]] == [0, 1]
    assert result["reply"] == "Første. Anden."
    assert len(result["chunks"]) == 2
    assert result["time_to_first_audio_s"] is not None

    # No concurrent synthesis: even for a fast multi-sentence stream, the
    # second speaker must wait for the first task's completion.
    active = [0]
    peak = [0]
    def serial_synth(text, path):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        try:
            import time
            time.sleep(0.01)
            wav(path)
            return {"duration": 0.001}
        finally:
            active[0] -= 1

    async def three(messages, model=None, base_url=None, api_key=None):
        yield packet("En. To. Tre.")

    with Stubs(stream=three, synth=serial_synth):
        result = asyncio.run(vp.converse(input_wav, out_dir=directory))
    assert peak == [1] and active == [0]
    assert len(result["chunks"]) == 3
    assert [c["text"] for c in result["chunks"]] == ["En.", "To.", "Tre."]

    # If the LLM aborts after the first complete sentence, the already
    # scheduled TTS must be joined before the original failure is returned.
    finished = threading.Event()
    async def broken_stream(messages, model=None, base_url=None, api_key=None):
        yield packet("Starter.")
        await asyncio.sleep(0.015)
        raise RuntimeError("simulated model stream interruption")

    def joined_synth(text, path):
        wav(path)
        finished.set()
        return {"duration": 0.001}

    with Stubs(stream=broken_stream, synth=joined_synth):
        try:
            asyncio.run(vp.converse(input_wav, out_dir=directory))
        except RuntimeError as exc:
            assert "model stream interruption" in str(exc), str(exc)
        else:
            raise AssertionError("LLM stream error got swallowed")
    assert finished.is_set(), "last TTS ran after the caller returned (or was lost)"

    # Synthesis failure is never converted into a successful speech response.
    def failing_synth(text, path):
        raise RuntimeError("simulated Piper failure")

    with Stubs(stream=three, synth=failing_synth):
        try:
            asyncio.run(vp.converse(input_wav, out_dir=directory))
        except RuntimeError as exc:
            assert "Piper failure" in str(exc), str(exc)
        else:
            raise AssertionError("TTS failure got swallowed")

print("PASS: bounded one-task TTS overlap, transcript/chunk order and fail-closed errors")
