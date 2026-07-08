#!/usr/bin/env python3
"""Alva Voice — full pipeline test recipe (V-MVP.3) for the rig.

This is the payoff test: talk to Alva in a terminal and get spoken replies,
proving the whole chain AND the time-to-first-audio metric. Claude cannot run
it -- it needs both Voice backends installed, Ollama running with a model, a
Danish audio file, and a human to listen.

PREREQUISITES (all on the rig):
  pip install faster-whisper piper-tts
  # download the Danish Piper voice (see tools/alva_voice_tts_test.py step 1)
  # Ollama running with a model, e.g.:  ollama serve  +  ollama pull qwen2.5-coder:7b
  # a 16 kHz mono Danish WAV, e.g. da_test.wav (see tools/alva_voice_asr_test.py)

RUN:
  python tools/alva_voice_pipeline_test.py da_test.wav

WHAT IT PROVES (or not):
  - The full chain works end to end: your speech -> transcript -> LLM reply ->
    spoken audio chunks.
  - time_to_first_audio_s: how fast Alva starts speaking after the LLM begins.
    THIS is the metric that decides whether it feels like an assistant. Target
    is "first audio while the LLM is still generating the rest" -- if the first
    sentence's WAV is ready in ~1-2s, the experience is responsive.
  - VRAM headroom: run `nvidia-smi` alongside to confirm ASR + LLM coexist
    (Piper is CPU-only, so it doesn't add GPU load).

REPORT BACK to Claude:
  - the transcript (did ASR hear you correctly?),
  - the reply text,
  - time_to_first_audio_s and total_s,
  - whether the chunk WAVs sound good in order (play chunk_000.wav, 001, ...),
  - peak VRAM.

If time-to-first-audio is too high, the next optimization is a smaller ASR
model (ALVA_ASR_MODEL=medium) and/or a lower-quality-but-faster Piper voice.
"""
import asyncio
import sys
import time


async def run(path: str) -> int:
    sys.path.insert(0, "worker")
    from app import voice_asr, voice_tts, voice_pipeline

    missing = []
    if not voice_asr.is_available():
        missing.append("faster-whisper")
    if not voice_tts.is_available():
        missing.append("piper-tts")
    if missing:
        print(f"Missing backend(s): {', '.join(missing)}. Install and retry.")
        return 1

    print("running full pipeline (ASR -> LLM -> TTS)...")
    t0 = time.time()
    try:
        result = await voice_pipeline.converse(path, language="da")
    except Exception as e:
        print(f"\nERROR: {e}")
        print("(is Ollama running with a model? is the audio 16 kHz mono?)")
        return 1
    wall = time.time() - t0

    print("\n=== TRANSCRIPT (what ASR heard) ===")
    print(result["transcript"])
    print("\n=== REPLY (LLM) ===")
    print(result["reply"])
    print("\n=== TIMING ===")
    print(f"model: {result['model']}")
    print(f"time to first audio: {result['time_to_first_audio_s']}s  "
          f"<-- the metric that matters")
    print(f"total pipeline: {result['total_s']}s (wall {wall:.2f}s)")
    print(f"\n=== AUDIO CHUNKS ({len(result['chunks'])}) ===")
    for c in result["chunks"]:
        print(f"  [{c['index']}] synth {c['synth_s']}s  {c['wav']}")
        print(f"       \"{c['text']}\"")
    print("\nPlay the chunk WAVs in order to hear Alva's reply.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/alva_voice_pipeline_test.py <audio.wav>")
        return 2
    return asyncio.run(run(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
