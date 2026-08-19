"""Kaliv Voice — text-to-speech provider facade.

Portable VoiceRig `.mrvoice` profiles are preferred when one is installed in
`~/.kaliv/voices` (or KALIV_VOICES_DIR). Existing Piper behavior remains the
fallback when no portable profile is selected.

A portable profile can run either through Chatterbox in-process or through the
loopback VoiceRig sidecar. The latter keeps the prebuilt ModelRig worker small.
"""
from __future__ import annotations

import logging
import os
import threading
import wave
from typing import Optional

from .env_compat import env

_voice = None
_voice_lock = threading.Lock()
_load_error: Optional[str] = None
_logger = logging.getLogger(__name__)


def _voice_name() -> str:
    return env("TTS_VOICE", "da_DK-talesyntese-medium")


def _voices_dir() -> str:
    explicit = env("TTS_VOICES_DIR")
    if explicit:
        return explicit
    new = os.path.expanduser("~/.kaliv/piper-voices")
    old = os.path.expanduser("~/.alva/piper-voices")
    if not os.path.isdir(new) and os.path.isdir(old):
        return old
    return new


def _mrvoice_path():
    try:
        from . import voice_profiles
        return voice_profiles.default_profile_path()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("mrvoice discovery failed: %r", exc)
        return None


def _piper_available() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception as exc:  # noqa: BLE001
        _logger.info("piper-tts er ikke tilgængelig (tale-syntese slået fra): %r", exc)
        return False


def is_available() -> bool:
    package = _mrvoice_path()
    if package is not None:
        try:
            from . import voice_profiles, voice_sidecar
            return voice_profiles.is_available() or voice_sidecar.is_configured()
        except Exception:
            return False
    return _piper_available()


def status() -> dict:
    package = _mrvoice_path()
    if package is not None:
        try:
            from . import voice_profiles, voice_sidecar
            local = voice_profiles.status()
            if local.get("ok"):
                return local
            sidecar = voice_sidecar.status()
            if sidecar.get("ok"):
                return sidecar
            return {
                "ok": False,
                "backend": "mrvoice",
                "voice": local.get("voice") or sidecar.get("voice"),
                "package": package.name,
                "detail": (
                    f"in-process: {local.get('detail') or 'unavailable'}; "
                    f"sidecar: {sidecar.get('detail') or 'unavailable'}"
                ),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "backend": "mrvoice", "voice": None, "detail": str(exc)}
    available = _piper_available()
    return {
        "ok": available,
        "backend": "piper",
        "voice": _voice_name() if available else None,
        "detail": None if available else "piper not installed",
    }


def _get_piper_voice():
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
                f"(run from {vdir}, or set TTS_VOICES_DIR)"
            )
            raise RuntimeError(_load_error)
        try:
            _voice = PiperVoice.load(model_path)
        except Exception as e:
            _load_error = f"failed to load Piper voice '{_voice_name()}': {e}"
            raise RuntimeError(_load_error) from e
        return _voice


def _piper_synthesize_to_wav(text: str, out_path: str) -> dict:
    voice = _get_piper_voice()
    with wave.open(out_path, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
        try:
            sr = wav_file.getframerate() or 22050
            frames = wav_file.getnframes()
        except wave.Error:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            sr, frames = 22050, 0
    duration = round(frames / sr, 2) if sr else 0.0
    return {
        "out_path": out_path,
        "sample_rate": sr,
        "duration": duration,
        "voice": _voice_name(),
        "backend": "piper",
    }


def synthesize_to_wav(text: str, out_path: str) -> dict:
    """Synthesize using portable profile, otherwise legacy Piper."""
    package = _mrvoice_path()
    if package is None:
        return _piper_synthesize_to_wav(text, out_path)

    from . import voice_profiles, voice_sidecar

    if voice_profiles.is_available():
        try:
            return voice_profiles.synthesize_to_wav(text, out_path)
        except Exception as exc:
            if not voice_sidecar.is_configured():
                raise
            _logger.warning("in-process mrvoice synthesis failed; trying VoiceRig sidecar: %s", exc)

    if voice_sidecar.is_configured():
        return voice_sidecar.synthesize_to_wav(text, out_path, package.name)
    raise RuntimeError(".mrvoice is selected but no Chatterbox runtime is available")
