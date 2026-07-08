#!/usr/bin/env python3
"""Alva Voice TTS — test recipe for the rig.

Claude cannot run this: it needs piper-tts + the Danish voice installed, and a
human to judge whether the voice sounds good. This is the on-device
verification for phase 2 of Alva Voice (V-MVP.2 in the delta doc).

WHAT THIS PROVES (or not):
  - Whether piper-tts installs and the Danish voice loads.
  - Whether the Danish speech is understandable / good enough.
  - Rough synthesis speed (should be well faster than real-time on CPU).

STEP 0 — enable TTS on the rig (one-time):
    pip install piper-tts

STEP 1 — download the Danish voice (one-time):
    mkdir -p ~/.alva/piper-voices && cd ~/.alva/piper-voices
    python -m piper.download_voices da_DK-talesyntese-medium
    (if that voice name isn't found, list options with:
     python -m piper.download_voices --help  or browse the Piper voices list;
     then set ALVA_TTS_VOICE to the exact name you downloaded.)

STEP 2 — run this script with some Danish text:
    python tools/alva_voice_tts_test.py "Hej, jeg er Alva. Hvordan kan jeg hjaelpe dig i dag?"

STEP 3 — listen to alva_tts_out.wav and report back to Claude:
    - does the Danish sound good / natural enough?
    - the printed synthesis time vs audio duration.
"""
import sys
import time


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else \
        "Hej, jeg er Alva. Hvordan kan jeg hjaelpe dig i dag?"
    out = sys.argv[2] if len(sys.argv) > 2 else "alva_tts_out.wav"

    sys.path.insert(0, "worker")
    from app import voice_tts

    if not voice_tts.is_available():
        print("piper-tts is NOT installed. Run: pip install piper-tts")
        return 1

    print(f"voice={voice_tts._voice_name()} voices_dir={voice_tts._voices_dir()}")
    print("synthesizing...")
    t0 = time.time()
    try:
        result = voice_tts.synthesize_to_wav(text, out)
    except RuntimeError as e:
        print(f"\nERROR: {e}")
        return 1
    elapsed = time.time() - t0

    dur = result.get("duration", 0) or 0
    rtf = (elapsed / dur) if dur else float("nan")
    print("\n=== RESULT ===")
    print(f"wrote: {result['out_path']}")
    print(f"sample rate: {result['sample_rate']} Hz")
    print(f"audio duration: {dur:.2f}s")
    print(f"synthesis time: {elapsed:.2f}s")
    print(f"real-time factor (RTF): {rtf:.2f}  (<1.0 = faster than real-time)")
    print(f"\nListen to {result['out_path']} and judge the Danish quality.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
