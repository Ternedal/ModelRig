"""Kaliv Voice — TTS provider facade.

Default behavior is `TTS_PROVIDER=auto`:
  1. Prefer a local VoiceRig `.mrvoice` profile when one is installed and the
     VoiceRig sidecar is healthy.
  2. Fall back to Piper unchanged.

The public contract stays `synthesize_to_wav(text, out_path)`, so the rest of
ModelRig's sentence-streaming voice pipeline does not need to know which TTS
engine produced the WAV.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import urllib.error
import urllib.request
import wave
from typing import Optional

from .env_compat import env

_voice = None
_voice_lock = threading.Lock()
_load_error: Optional[str] = None

_VALID_PROVIDERS = {"auto", "piper", "voicerig"}


def _integration_env(name: str, default: str | None = None) -> str | None:
    """Read an integration-level env var without mangling its public name.

    ModelRig's env_compat helper deliberately maps Voice-era suffixes to
    KALIV_*/ALVA_* names. Integration knobs such as MODELRIG_VOICES_DIR and
    VOICERIG_TTS_URL are already fully-qualified names and must be read
    literally. For new TTS knobs we additionally accept the Kaliv/Alva aliases
    so existing environment conventions remain usable.
    """
    direct = os.environ.get(name)
    if direct is not None:
        return direct
    return env(name, default)


def _provider_setting() -> str:
    value = str(_integration_env("TTS_PROVIDER", "auto")).strip().lower()
    return value if value in _VALID_PROVIDERS else "auto"


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


def _mrvoice_dir() -> str:
    # MODELRIG_* names belong to the engine and do not pass through env_compat.
    return os.path.expanduser(os.environ.get("MODELRIG_VOICES_DIR", "~/.kaliv/voices"))


def _has_mrvoice() -> bool:
    root = _mrvoice_dir()
    try:
        return os.path.isdir(root) and any(name.endswith(".mrvoice") for name in os.listdir(root))
    except OSError:
        return False


def _voicerig_base_url() -> str:
    return str(_integration_env("VOICERIG_TTS_URL", "http://127.0.0.1:8765")).rstrip("/")


def _voicerig_timeout() -> float:
    try:
        return max(1.0, float(str(_integration_env("VOICERIG_TTS_TIMEOUT_SECONDS", "180"))))
    except ValueError:
        return 180.0


def _voicerig_status(timeout: float = 1.5) -> dict:
    req = urllib.request.Request(
        _voicerig_base_url() + "/api/tts/status",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("status payload is not an object")
        return body
    except Exception as exc:  # noqa: BLE001 - health probe must be fail-soft
        return {"ok": False, "detail": f"VoiceRig unavailable: {exc}"}


def _piper_available() -> bool:
    if _voice is not None:
        return True
    try:
        import piper  # noqa: F401
        return True
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).info(
            "piper-tts er ikke tilgængelig (tale-syntese slået fra): %r", exc
        )
        return False


def _select_provider() -> tuple[str, dict | None]:
    setting = _provider_setting()
    if setting == "piper":
        return "piper", None
    if setting == "voicerig":
        return "voicerig", _voicerig_status()
    if _has_mrvoice():
        vr = _voicerig_status()
        if vr.get("ok") is True:
            return "voicerig", vr
    return "piper", None


def is_available() -> bool:
    return bool(status().get("ok"))


def status() -> dict:
    provider, vr = _select_provider()
    if provider == "voicerig":
        ok = bool(vr and vr.get("ok"))
        return {
            "ok": ok,
            "provider": "voicerig",
            "voice": (vr or {}).get("voice"),
            "package": (vr or {}).get("package"),
            "device": (vr or {}).get("device"),
            "detail": None if ok else (vr or {}).get("detail", "VoiceRig unavailable"),
        }

    available = _piper_available()
    detail = None if available else "piper not installed"
    if _provider_setting() == "auto" and _has_mrvoice() and not available:
        vr = _voicerig_status()
        detail = (
            "VoiceRig profile is installed but sidecar is unavailable; "
            + str(vr.get("detail") or "unknown VoiceRig error")
            + "; Piper is also unavailable"
        )
    return {
        "ok": available,
        "provider": "piper",
        "voice": _voice_name() if available else None,
        "detail": detail,
    }


def _get_voice():
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


def _synthesize_piper(text: str, out_path: str) -> dict:
    voice = _get_voice()
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
        "provider": "piper",
    }


def _synthesize_voicerig(text: str, out_path: str) -> dict:
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        _voicerig_base_url() + "/api/tts/synthesize",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_voicerig_timeout()) as resp:
            raw = resp.read()
            headers = resp.headers
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"VoiceRig TTS failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"VoiceRig TTS is unavailable: {exc}") from exc

    if len(raw) < 44:
        raise RuntimeError("VoiceRig returned an empty or invalid WAV")

    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".voicerig-", suffix=".wav", dir=out_dir)
    os.close(fd)
    try:
        with open(temp_path, "wb") as fh:
            fh.write(raw)
        try:
            with wave.open(temp_path, "rb") as wav_file:
                sr = wav_file.getframerate()
                frames = wav_file.getnframes()
        except (wave.Error, EOFError) as exc:
            raise RuntimeError("VoiceRig returned a malformed WAV") from exc
        os.replace(temp_path, out_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    duration = round(frames / sr, 2) if sr else 0.0
    return {
        "out_path": out_path,
        "sample_rate": sr,
        "duration": duration,
        "voice": headers.get("X-VoiceRig-Voice", "VoiceRig"),
        "voice_id": headers.get("X-VoiceRig-Voice-ID"),
        "package": headers.get("X-VoiceRig-Package"),
        "device": headers.get("X-VoiceRig-Device"),
        "provider": "voicerig",
    }


def synthesize_to_wav(text: str, out_path: str) -> dict:
    """Synthesize text while preserving the historic ModelRig TTS contract.

    `auto` prefers an installed `.mrvoice` profile when VoiceRig is healthy.
    If VoiceRig is down, Piper remains the compatibility fallback.
    """
    provider, vr = _select_provider()
    if provider == "voicerig":
        if _provider_setting() == "voicerig" and not (vr or {}).get("ok"):
            raise RuntimeError((vr or {}).get("detail") or "VoiceRig TTS is unavailable")
        try:
            return _synthesize_voicerig(text, out_path)
        except RuntimeError:
            if _provider_setting() != "auto" or not _piper_available():
                raise
            logging.getLogger(__name__).warning(
                "VoiceRig synthesis failed; falling back to Piper", exc_info=True
            )
    return _synthesize_piper(text, out_path)
