"""Kaliv Voice — TTS (text-to-speech) module.

Phase 2 of the Kaliv Voice MVP (see ALVA_VOICE_ROADMAP_DELTA.md). Built on Piper
for the MVP:
  - CPU-only, real-time (~10x real-time on a modern desktop CPU), tiny voices
    (~tens of MB). Frees the GPU entirely for ASR + the LLM. Verified via web
    2026-07-08.
  - VITS architecture exported to ONNX, embedded espeak-ng phonemization.

LICENSE NOTE (corrected from the delta doc's "free"): the old MIT rhasspy/piper
repo is archived read-only (Oct 2025). The active, maintained project is
OHF-Voice/piper1-gpl and is **GPL-3.0** (v1.4.2, April 2026). Fine for Anders'
private/personal use; flagged here because it's NOT permissive -- matters only
if this is ever shipped/redistributed. Individual VOICE models carry their own
MODEL_CARD license -- the Danish voice's card must be checked before shipping.

Like the ASR module, this is OPTIONAL. piper-tts is NOT a hard worker
dependency (keeps the base "download exe" rig light). Imported lazily; if it
isn't installed, the TTS endpoint returns a clean 501 with instructions and the
rest of the worker is unaffected.

NOT YET TESTED ON HARDWARE. Code + a test recipe (tools/alva_voice_tts_test.py).
Whether the Danish voice sounds good, and the real synth latency, can only be
confirmed on Anders' machine.
"""
from __future__ import annotations

import os
import threading
import wave
from typing import Optional

from .env_compat import env

_voice = None
_voice_lock = threading.Lock()
_load_error: Optional[str] = None


def _voice_name() -> str:
    # Danish medium voice (22.05 kHz). Overridable; x_low/low are 16 kHz and
    # faster/smaller if latency matters more than quality.
    return env("TTS_VOICE", "da_DK-talesyntese-medium")


def _voices_dir() -> str:
    # Where the .onnx + .onnx.json voice files live on the rig. Piper downloads
    # them here on first use (or the user pre-downloads them).
    explicit = env("TTS_VOICES_DIR")
    if explicit:
        return explicit
    # Default moved ~/.alva -> ~/.kaliv. Anders' voice files already live in
    # the old dir; keep using it if it exists so nothing breaks on rename.
    new = os.path.expanduser("~/.kaliv/piper-voices")
    old = os.path.expanduser("~/.alva/piper-voices")
    if not os.path.isdir(new) and os.path.isdir(old):
        return old
    return new


def is_available() -> bool:
    """True if piper-tts can be imported (installed)."""
    try:
        import piper  # noqa: F401  (the piper-tts package)
        return True
    except Exception:
        return False


def _get_voice():
    """Load (once) and return the Piper voice, or raise with a clear message."""
    global _voice, _load_error
    if _voice is not None:
        return _voice
    with _voice_lock:
        if _voice is not None:
            return _voice
        try:
            from piper import PiperVoice
        except Exception as e:
            _load_error = (
                "piper-tts is not installed. Kaliv Voice TTS is optional; install "
                "it on the rig with: pip install piper-tts"
            )
            raise RuntimeError(_load_error) from e

        vdir = _voices_dir()
        os.makedirs(vdir, exist_ok=True)
        model_path = os.path.join(vdir, f"{_voice_name()}.onnx")
        if not os.path.exists(model_path):
            _load_error = (
                f"Piper voice '{_voice_name()}' not found in {vdir}. Download it once with:\n"
                f"  python -m piper.download_voices {_voice_name()}\n"
                f"(run from {vdir}, or set ALVA_TTS_VOICES_DIR)"
            )
            raise RuntimeError(_load_error)
        try:
            _voice = PiperVoice.load(model_path)
        except Exception as e:
            _load_error = f"failed to load Piper voice '{_voice_name()}': {e}"
            raise RuntimeError(_load_error) from e
        return _voice


def synthesize_to_wav(text: str, out_path: str) -> dict:
    """Synthesize Danish text to a WAV file at out_path.

    Returns {out_path, sample_rate, duration, voice}. Whole-utterance synth for
    the MVP; sentence-by-sentence streaming (for time-to-first-audio) is a later
    phase that lives in the audio-queue layer, not here.
    """
    voice = _get_voice()
    with wave.open(out_path, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
        # Read back the params we just wrote for an honest duration/sample-rate.
        sr = wav_file.getframerate() or 22050
        frames = wav_file.getnframes()
    duration = round(frames / sr, 2) if sr else 0.0
    return {
        "out_path": out_path,
        "sample_rate": sr,
        "duration": duration,
        "voice": _voice_name(),
    }
