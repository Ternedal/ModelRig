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
_dll_directory_handles: list[object] = []


def registered_dll_dirs() -> list[str]:
    """Which CUDA DLL directories have been registered so far.

    Read-only: does NOT trigger registration. Empty until the model has been
    loaded on a cuda device (registration is lazy), or if the nvidia-* pip
    packages aren't installed. A status endpoint must answer instantly, so it
    reads this rather than doing the work.
    """
    return list(_registered_dll_dirs)


def _candidate_cuda_dll_dirs() -> list[str]:
    """Find local CUDA 12 DLLs without a full-disk scan or global PATH change.

    The frozen worker has its own Python environment and cannot import wheels
    installed in an existing rig venv. On Windows, reuse a *paired* cuBLAS 12
    and cuDNN 9 installation from the nearest trusted venvs directory. Also
    support explicitly configured directories and DLLs bundled by PyInstaller.
    Called only on the first CUDA model load; /status stays cheap.
    """
    import sys
    from pathlib import Path

    dirs: list[str] = []
    seen: set[str] = set()

    def add(candidate: Path) -> None:
        if not candidate.is_dir():
            return
        path = str(candidate.resolve())
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            dirs.append(path)

    # Packages installed in the same interpreter, when running unfrozen.
    try:
        import nvidia
        for root in getattr(nvidia, "__path__", []):
            for package in sorted(Path(root).iterdir()):
                add(package / "bin")
    except (ImportError, OSError):
        pass

    # Optional CUDA DLLs included inside the PyInstaller extraction directory.
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        for rel in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "ctranslate2"):
            add(Path(frozen_root) / rel)

    # Explicit operator override, e.g. two paths separated by semicolons on
    # Windows. The paths must exist; no registry or arbitrary recursive search.
    for raw in (env("CUDA_DLL_DIRS", "") or "").split(os.pathsep):
        if raw.strip():
            add(Path(raw.strip()))

    roots: list[Path] = []
    configured = os.environ.get("MODELRIG_VENVS_DIR", "").strip()
    if configured:
        roots.append(Path(configured))

    # A frozen EXE at C:\Rig\test\... or C:\Rig\bin\... discovers
    # C:\Rig\venvs; a normal venv Python discovers its sibling venvs.
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        sibling = parent / "venvs"
        if sibling.is_dir():
            roots.append(sibling)
            break

    for root in roots:
        try:
            environments = sorted(
                (entry for entry in root.iterdir() if entry.is_dir()),
                key=lambda p: (not p.name.lower().startswith("kalivvoice"), p.name.lower()),
            )[:100]
        except OSError:
            continue
        for venv in environments:
            site = venv / "Lib" / "site-packages"
            cublas = site / "nvidia" / "cublas" / "bin"
            cudnn = site / "ctranslate2"
            if not (cudnn / "cudnn64_9.dll").is_file():
                cudnn = site / "nvidia" / "cudnn" / "bin"
            if (cublas / "cublas64_12.dll").is_file() and (cudnn / "cudnn64_9.dll").is_file():
                add(cublas)
                add(cudnn)
                return dirs  # one compatible venv pair; don't mix environments
    return dirs


def _add_cuda_dll_dirs() -> list[str]:
    """Expose CUDA 12 DLLs to the frozen worker on first GPU inference.

    CTranslate2's legacy cuBLAS loader uses PATH, not just
    os.add_dll_directory(). Both are required; changes are process-local and
    never touch the user's persistent PATH or another worker process.
    """
    global _dll_dirs_added
    if _dll_dirs_added or not hasattr(os, "add_dll_directory"):
        return list(_registered_dll_dirs)

    added: list[str] = []
    for directory in _candidate_cuda_dll_dirs():
        try:
            # Keep the handle alive: closing it removes the DLL directory.
            handle = os.add_dll_directory(directory)
            _dll_directory_handles.append(handle)
            added.append(directory)
        except OSError:
            continue

    if added:
        os.environ["PATH"] = os.pathsep.join(added) + os.pathsep + os.environ.get("PATH", "")
    _registered_dll_dirs.extend(added)
    _dll_dirs_added = True
    return list(added)

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
            try:
                data, sr = sf.read(path, dtype="float32")
            except RuntimeError as exc:
                # On Windows libsndfile can fail to open a temporary pathname
                # even though Python can read its bytes. Retry in memory,
                # preserving the soundfile decoder and avoiding PyAV.
                import io
                try:
                    with open(path, "rb") as source:
                        wav_bytes = source.read()
                    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
                except Exception as retry_exc:
                    raise RuntimeError(
                        f"ASR could not decode input WAV (path={path!r}, "
                        f"bytes={len(wav_bytes) if 'wav_bytes' in locals() else 'unreadable'}, "
                        f"file_error={exc!s}, memory_error={retry_exc!s})"
                    ) from retry_exc
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
