"""Alva Voice — ASR (speech-to-text) module.

Phase 1 of the Alva Voice MVP (see ALVA_VOICE_ROADMAP_DELTA.md). Deliberately
built on faster-whisper, NOT Parakeet/NeMo, for the MVP:
  - MIT-licensed (Parakeet is under NVIDIA Open Model License).
  - No NeMo/PyTorch-heavy toolchain -- CTranslate2 backend, ~2.5 GB VRAM at
    INT8, verified to run alongside an LLM on a single RTX 3060 (web-checked
    2026-07-08). RTX 3060 hits RTF ~0.15 on large-v3, well inside real-time.
  - Silero VAD is BUILT IN (vad_filter=True) -- no separate VAD module needed
    for the MVP.

This module is OPTIONAL. faster-whisper is not a hard dependency of the worker
(that would break the light "download exe, no toolchain" rig setup for users
who don't want Voice). It's imported lazily; if faster-whisper isn't installed,
the ASR endpoint returns a clean 501 telling the user how to enable it, and the
rest of the worker (RAG, chat) is unaffected.

Model default is large-v3 at int8 -- best Danish quality that fits the VRAM
budget. Overridable via env for smaller/faster options on tighter hardware.

NOT YET TESTED ON HARDWARE. This is code + a test recipe (see
tools/alva_voice_asr_test.py). Anders' RTX 3060 run is the real verification --
ASR quality and VRAM headroom can only be confirmed there.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

# Lazy singleton: the model is heavy (~2.5 GB VRAM), load once, on first use.
_model = None
_model_lock = threading.Lock()
_load_error: Optional[str] = None


def _model_name() -> str:
    # large-v3 = best multilingual/Danish accuracy. int8 keeps VRAM ~2.5 GB so
    # it coexists with the LLM. Smaller options (medium, small) via env for
    # tighter GPUs or lower latency at some accuracy cost.
    return os.environ.get("ALVA_ASR_MODEL", "large-v3")


def _compute_type() -> str:
    return os.environ.get("ALVA_ASR_COMPUTE", "int8")


def _device() -> str:
    return os.environ.get("ALVA_ASR_DEVICE", "cuda")


def is_available() -> bool:
    """True if faster-whisper can be imported (installed)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    """Load (once) and return the WhisperModel, or raise with a clear message."""
    global _model, _load_error
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
        except Exception as e:  # not installed
            _load_error = (
                "faster-whisper is not installed. Alva Voice ASR is optional; "
                "install it on the rig with: pip install faster-whisper"
            )
            raise RuntimeError(_load_error) from e
        try:
            _model = WhisperModel(_model_name(), device=_device(), compute_type=_compute_type())
        except Exception as e:
            # Common causes: no CUDA, wrong compute_type for the GPU, OOM.
            _load_error = (
                f"failed to load ASR model '{_model_name()}' on {_device()}/{_compute_type()}: {e}. "
                f"On a machine without a GPU, set ALVA_ASR_DEVICE=cpu ALVA_ASR_COMPUTE=int8."
            )
            raise RuntimeError(_load_error) from e
        return _model


def transcribe_wav(path: str, language: str = "da") -> dict:
    """Transcribe a 16 kHz mono WAV/audio file to Danish text.

    Returns {text, language, duration, segments:[{start,end,text}]}.

    Notes verified from faster-whisper docs (2026-07-08):
      - vad_filter=True uses the built-in Silero VAD to drop silence.
      - For a single recorded utterance (push-to-talk), we transcribe the whole
        file at once, so condition_on_previous_text can stay at its default.
        (For real-time STREAMING chunks it must be False to avoid drift -- that
        belongs to a later streaming phase, not this file-based MVP step.)
      - language='da' skips the ~50ms auto-detect pass and forces Danish.
    """
    model = _get_model()
    segments, info = model.transcribe(
        path,
        language=language,
        beam_size=5,
        vad_filter=True,
    )
    # segments is a generator -- materialize it (this is where work happens).
    seg_list = []
    text_parts = []
    for s in segments:
        seg_list.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        text_parts.append(s.text.strip())
    return {
        "text": " ".join(text_parts).strip(),
        "language": info.language,
        "duration": round(info.duration, 2),
        "segments": seg_list,
    }
