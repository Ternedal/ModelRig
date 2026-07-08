#!/usr/bin/env python3
"""Alva Voice ASR — test recipe for the rig (RTX 3060).

Claude cannot run this: it needs the actual GPU and a Danish audio file. This
is the on-device verification step for phase 1 of Alva Voice.

WHAT THIS PROVES (or not):
  - Whether faster-whisper installs and loads large-v3 on the RTX 3060.
  - Whether Danish transcription is actually good on your voice.
  - VRAM headroom (run `nvidia-smi` alongside to see it coexist with the LLM).
  - Rough real-time factor (transcription time vs audio duration).

STEP 0 — enable ASR on the rig (one-time):
    pip install faster-whisper

STEP 1 — record ~10s of Danish speech as 16 kHz mono WAV, e.g. da_test.wav.
    (Any recorder; then: ffmpeg -i in.m4a -ar 16000 -ac 1 da_test.wav)

STEP 2 — run this script pointing at the file:
    python tools/alva_voice_asr_test.py da_test.wav

STEP 3 — report back to Claude:
    - the transcription (is it correct Danish?),
    - the printed real-time factor,
    - peak VRAM from `nvidia-smi` while it ran.

If large-v3 is too slow or OOMs alongside the LLM, try a smaller model:
    ALVA_ASR_MODEL=medium python tools/alva_voice_asr_test.py da_test.wav
"""
import sys
import time


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/alva_voice_asr_test.py <audio.wav> [language]")
        return 2
    path = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else "da"

    # Import the worker module so we test the SAME code path the endpoint uses.
    sys.path.insert(0, "worker")
    from app import voice_asr

    if not voice_asr.is_available():
        print("faster-whisper is NOT installed. Run: pip install faster-whisper")
        return 1

    print(f"model={voice_asr._model_name()} device={voice_asr._device()} "
          f"compute={voice_asr._compute_type()}")
    print("loading model + transcribing (first run downloads the model)...")
    t0 = time.time()
    result = voice_asr.transcribe_wav(path, language=language)
    elapsed = time.time() - t0

    dur = result.get("duration", 0) or 0
    rtf = (elapsed / dur) if dur else float("nan")
    print("\n=== TRANSCRIPTION ===")
    print(result["text"])
    print("\n=== TIMING ===")
    print(f"audio duration : {dur:.2f}s")
    print(f"processing time: {elapsed:.2f}s  (incl. model load on first run)")
    print(f"real-time factor (RTF): {rtf:.2f}  (<1.0 = faster than real-time)")
    print(f"detected language: {result['language']}")
    print(f"segments: {len(result['segments'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
