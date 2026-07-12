"""Tests for the STREAMING voice path (v1.54.0).

The voice pipeline already split the LLM output on sentence boundaries and
synthesized each sentence as it arrived, but the endpoint buffered everything
into one response before replying. converse() now accepts on_transcript/on_chunk
callbacks so a streaming endpoint can deliver the transcript first and then each
sentence's audio the moment it's ready. These tests drive converse() with stubbed
ASR/TTS/LLM (no real models) and assert the callbacks fire correctly and in order.
"""
import asyncio
import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

passed = failed = 0
def check(cond, msg):
    global passed, failed
    if cond: passed += 1; print(f"  PASS: {msg}")
    else: failed += 1; print(f"  FAIL: {msg}")

from app import voice_pipeline as vp  # noqa: E402
import app.ollama_client as oc  # noqa: E402


def _write_silent_wav(path):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16)


def _install_stubs(reply_deltas):
    """Stub ASR (fixed transcript), TTS (writes a tiny WAV), and the LLM stream
    (yields the given deltas as ollama-style lines). Returns a restore() fn."""
    saved = {
        "asr_avail": vp.voice_asr.is_available,
        "tts_avail": vp.voice_tts.is_available,
        "transcribe": vp.voice_asr.transcribe_wav,
        "synth": vp.voice_tts.synthesize_to_wav,
        "chat_stream": oc.chat_stream,
    }
    vp.voice_asr.is_available = lambda: True
    vp.voice_tts.is_available = lambda: True
    vp.voice_asr.transcribe_wav = lambda path, lang: {"text": "hvad er klokken", "language": lang}
    vp.voice_tts.synthesize_to_wav = lambda text, wav: _write_silent_wav(wav)

    async def fake_stream(messages, model=None, base_url=None, api_key=None):
        for d in reply_deltas:
            # chat_stream yields bytes; _extract_delta calls .decode() on them.
            yield ('{"message":{"content":' + _json_str(d) + '}}').encode()
    oc.chat_stream = fake_stream

    def restore():
        vp.voice_asr.is_available = saved["asr_avail"]
        vp.voice_tts.is_available = saved["tts_avail"]
        vp.voice_asr.transcribe_wav = saved["transcribe"]
        vp.voice_tts.synthesize_to_wav = saved["synth"]
        oc.chat_stream = saved["chat_stream"]
    return restore


def _json_str(s):
    import json
    return json.dumps(s)


def run():
    tmp = tempfile.mkdtemp(prefix="voice_stream_test_")
    in_wav = os.path.join(tmp, "in.wav")
    _write_silent_wav(in_wav)

    # A reply with three sentences, streamed as several deltas that split a
    # sentence across chunk boundaries (the realistic case).
    deltas = ["Klokken er ", "tolv. Det er ", "middag. Held og lykke!"]
    restore = _install_stubs(deltas)
    try:
        transcripts = []
        chunks = []

        async def on_transcript(t): transcripts.append(t)
        async def on_chunk(c): chunks.append(c)

        result = asyncio.run(vp.converse(
            in_wav, language="da", out_dir=tmp,
            on_transcript=on_transcript, on_chunk=on_chunk,
        ))

        # on_transcript fires exactly once, before any chunks, with the ASR text.
        check(transcripts == ["hvad er klokken"],
              "on_transcript fires once with the ASR text")

        # Three sentences -> three chunks, each with text + a real WAV path + index.
        check(len(chunks) == 3, f"on_chunk fires once per sentence (got {len(chunks)})")
        check([c["index"] for c in chunks] == [0, 1, 2],
              "chunks are indexed in order 0,1,2")
        check(all(os.path.exists(c["wav"]) for c in chunks),
              "each chunk has a synthesized WAV on disk")
        check("tolv" in chunks[0]["text"] and "middag" in chunks[1]["text"],
              "sentences are split on boundaries across deltas")

        # The returned dict still has the full reply + all chunks (buffered callers
        # keep working unchanged).
        check("Held og lykke" in result["reply"], "returned reply is the full text")
        check(len(result["chunks"]) == 3, "returned dict still carries all chunks")

        # Backward compat: calling without callbacks must not raise.
        restore2 = _install_stubs(deltas)
        try:
            r2 = asyncio.run(vp.converse(in_wav, language="da", out_dir=tmp))
            check(len(r2["chunks"]) == 3, "converse works with NO callbacks (buffered path)")
        finally:
            restore2()
    finally:
        restore()

    print(f"\n===== VOICE STREAM: {passed} passed, {failed} failed =====")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    run()
