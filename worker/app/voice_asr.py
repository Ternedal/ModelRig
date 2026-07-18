"""Kaliv Voice — ASR (speech-to-text) module.

Phase 1 of the Kaliv Voice MVP (see ALVA_VOICE_ROADMAP_DELTA.md). Deliberately
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

import logging

import os
import threading

from .env_compat import env
from typing import Optional

# Lazy singleton: the model is heavy (~2.5 GB VRAM), load once, on first use.
_model = None
_model_lock = threading.Lock()
_load_error: Optional[str] = None
_dll_dirs_added = False
_registered_dll_dirs: list[str] = []


def registered_dll_dirs() -> list[str]:
    """Which CUDA DLL directories have been registered so far.

    Read-only: does NOT trigger registration. Empty until the model has been
    loaded on a cuda device (registration is lazy), or if the nvidia-* pip
    packages aren't installed. A status endpoint must answer instantly, so it
    reads this rather than doing the work.
    """
    return list(_registered_dll_dirs)


def _add_cuda_dll_dirs() -> list[str]:
    """Make CUDA runtime DLLs findable on Windows. Returns the dirs added.

    CTranslate2 (faster-whisper's backend) needs cublas64_12.dll and cuDNN at
    load time. `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` puts them in
    site-packages/nvidia/<pkg>/bin, which Windows does NOT search -- so the load
    fails with "Library cublas64_12.dll is not found or cannot be loaded".
    Verified on Anders' rig 2026-07-09: installing the pip packages alone wasn't
    enough, and he had to fall back to CPU.

    Python 3.8+ on Windows only searches directories registered via
    os.add_dll_directory() -- but that only covers libraries loaded with the
    new search flags. CTranslate2 resolves cuBLAS via the LEGACY search path,
    which only consults PATH (hardware-verified 2026-07-09: dirs registered,
    DLL on disk, load still failed; prepending PATH fixed it). So we do BOTH:
    register the dirs and prepend them to PATH. No-op on Linux/macOS (where
    the loader uses RPATH/LD_LIBRARY_PATH) and harmless if the packages
    aren't installed.
    """
    global _dll_dirs_added
    if _dll_dirs_added or not hasattr(os, "add_dll_directory"):
        return list(_registered_dll_dirs)
    added: list[str] = []
    try:
        import nvidia  # the namespace package created by nvidia-* wheels
    except Exception as exc:  # noqa: BLE001
        # No nvidia-* wheels means no CUDA DLL directories to register, which is
        # a legitimate CPU-only setup -- but it is also what a half-installed
        # CUDA stack looks like, and the difference decides whether Whisper runs
        # on the 3060 or crawls on the CPU.
        logging.getLogger(__name__).debug(
            "ingen nvidia-wheels fundet; springer CUDA DLL-registrering over: %r", exc)
        _dll_dirs_added = True
        return []
    for root in getattr(nvidia, "__path__", []):
        if not os.path.isdir(root):
            continue
        for pkg in os.listdir(root):
            bin_dir = os.path.join(root, pkg, "bin")
            if os.path.isdir(bin_dir):
                try:
                    os.add_dll_directory(bin_dir)
                    added.append(bin_dir)
                except OSError:
                    pass
    if added:
        # add_dll_directory() alone is NOT enough here. Hardware-verified on
        # Anders' rig 2026-07-09 (v1.12.2 logging): the dirs WERE registered,
        # cublas64_12.dll WAS on disk, and CTranslate2 still failed with
        # "Library cublas64_12.dll is not found or cannot be loaded" -- it
        # resolves cuBLAS through the legacy search path, which only consults
        # PATH. Prepending the same dirs to PATH fixed it on the spot
        # (manual `set PATH=...` -> voice worked end-to-end). We set both.
        os.environ["PATH"] = (
            os.pathsep.join(added) + os.pathsep + os.environ.get("PATH", "")
        )
    _dll_dirs_added = True
    _registered_dll_dirs.extend(added)
    return added


def _model_name() -> str:
    # large-v3 = best multilingual/Danish accuracy. int8 keeps VRAM ~2.5 GB so
    # it coexists with the LLM. Smaller options (medium, small) via env for
    # tighter GPUs or lower latency at some accuracy cost.
    return env("ASR_MODEL", "large-v3")


def _compute_type() -> str:
    return env("ASR_COMPUTE", "int8")


def _device() -> str:
    # Default cuda. On Windows the CUDA runtime DLLs shipped by the nvidia-*
    # pip wheels live where Windows won't look; _add_cuda_dll_dirs() registers
    # them before the model loads (see that function). If CUDA still won't come
    # up, fall back with ALVA_ASR_DEVICE=cpu + ALVA_ASR_MODEL=small.
    return env("ASR_DEVICE", "cuda")


def is_available() -> bool:
    """True if faster-whisper can be imported (installed)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception as exc:  # noqa: BLE001
        # Fail-closed is right: no faster-whisper, no speech recognition.
        # Silence is not. On the rig this catches CUDA/cuDNN mismatches and
        # broken wheels, and reports all of them as "unavailable" with no
        # reason -- which is the one failure mode most likely to cost an
        # evening, because ASR is the capability with the deepest native stack.
        logging.getLogger(__name__).info(
            "faster-whisper er ikke tilgængelig (tale-genkendelse slået fra): %r", exc)
        return False


def status() -> dict:
    """Cheap public health contract for the optional ASR subsystem.

    The worker health endpoint must not know private configuration helpers. This
    function owns that translation and deliberately does not load the model.
    """
    available = is_available()
    return {
        "ok": available,
        "device": _device() if available else None,
        "model": _model_name() if available else None,
        "detail": None if available else "faster-whisper not installed",
    }


def cuda_available() -> bool:
    """True if a CUDA device is actually usable, not merely configured. Uses
    CTranslate2's device count (faster-whisper's backend) so it reflects real GPU
    availability WITHOUT loading a model. False if CT2 is absent or there's no
    GPU -- honest for the worker's own GPU work (ASR); Ollama's GPU use is
    separate and reported via the ollama check."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
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
                "faster-whisper is not installed. Kaliv Voice ASR is optional; "
                "install it on the rig with: pip install faster-whisper"
            )
            raise RuntimeError(_load_error) from e
        # Register the CUDA DLL dirs BEFORE constructing the model -- CTranslate2
        # resolves cublas/cuDNN at load time, not at import time.
        if _device() == "cuda":
            _add_cuda_dll_dirs()
        try:
            _model = WhisperModel(_model_name(), device=_device(), compute_type=_compute_type())
        except Exception as e:
            # Common causes: no CUDA, missing CUDA runtime DLLs, wrong
            # compute_type for the GPU, OOM.
            msg = str(e).lower()
            if "cublas" in msg or "cudnn" in msg or "dll" in msg:
                _load_error = (
                    f"failed to load ASR model on CUDA: {e}\n"
                    "The CUDA runtime libraries aren't loadable. Install them into THIS "
                    "Python with:\n"
                    "  pip install nvidia-cublas-cu12 nvidia-cudnn-cu12\n"
                    "(the worker registers their DLL directories automatically). If it "
                    "still fails, run ASR on CPU:\n"
                    "  set ALVA_ASR_DEVICE=cpu & set ALVA_ASR_COMPUTE=int8 & set ALVA_ASR_MODEL=small"
                )
            else:
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

    AUDIO DECODE -- soundfile, NOT PyAV: faster-whisper by default decodes audio
    via PyAV (the `av` package), whose native DLLs are blocked by Windows
    Application Control / Smart App Control on some machines ("En politik for
    programkontrol har blokeret denne fil"). Verified on Anders' rig 2026-07-08.
    So when the input is a real file, we decode it ourselves with soundfile
    (small signed DLL, not blocked) into a mono float32 array and hand Whisper
    the samples -- PyAV is never touched. Whisper accepts a numpy array in place
    of a path. If soundfile isn't available or the input is already an array, we
    fall back to passing it straight through.
    """
    model = _get_model()
    audio_input = path
    if isinstance(path, str):
        try:
            import soundfile as sf
            data, sr = sf.read(path, dtype="float32")
            # Whisper wants 16 kHz mono. Downmix to mono; resample if needed.
            if getattr(data, "ndim", 1) > 1:
                data = data.mean(axis=1)
            if sr != 16000:
                # Lightweight linear resample to 16 kHz (avoids pulling in scipy).
                import numpy as np
                n_out = int(round(len(data) * 16000 / sr))
                if n_out > 0:
                    xp = np.linspace(0, 1, num=len(data), endpoint=False)
                    xq = np.linspace(0, 1, num=n_out, endpoint=False)
                    data = np.interp(xq, xp, data).astype("float32")
            audio_input = data
        except ImportError:
            # soundfile not installed -> let faster-whisper try its own decode
            # (may hit the PyAV block on Windows; the install note recommends
            # soundfile for exactly this reason).
            audio_input = path

    segments, info = model.transcribe(
        audio_input,
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
