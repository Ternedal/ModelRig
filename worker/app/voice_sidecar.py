"""Loopback client for VoiceRig's optional Chatterbox TTS sidecar.

The prebuilt ModelRig worker intentionally does not bundle the heavy PyTorch /
Chatterbox runtime. When a portable `.mrvoice` profile is selected and
Chatterbox is unavailable in-process, ModelRig can synthesize through the
VoiceRig process on 127.0.0.1 instead.

Remote destinations are refused by default. Set VOICERIG_ALLOW_REMOTE=1
only for an explicitly designed split-host deployment.
"""
from __future__ import annotations

import json
import os
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlparse

import httpx


def _base_url() -> str | None:
    raw = os.getenv("VOICERIG_TTS_URL", "http://127.0.0.1:8765").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and os.getenv("VOICERIG_ALLOW_REMOTE", "0") != "1":
        return None
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    return raw.rstrip("/")


def is_configured() -> bool:
    return _base_url() is not None


def status() -> dict:
    base = _base_url()
    if base is None:
        return {
            "ok": False,
            "backend": "mrvoice-sidecar",
            "detail": "VoiceRig sidecar is disabled or its URL is not allowed",
        }
    try:
        response = httpx.get(base + "/api/tts/status", timeout=0.5)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "backend": "mrvoice-sidecar",
            "url": base,
            "detail": f"VoiceRig sidecar unavailable: {exc}",
        }
    return {
        **body,
        "backend": "mrvoice-sidecar",
        "url": base,
    }


def _wav_meta(path: Path) -> tuple[int, float]:
    try:
        with wave.open(str(path), "rb") as f:
            sr = f.getframerate()
            frames = f.getnframes()
        return sr, round(frames / sr, 3) if sr else 0.0
    except wave.Error:
        return 0, 0.0


def synthesize_to_wav(text: str, out_path: str, package_name: str) -> dict:
    base = _base_url()
    if base is None:
        raise RuntimeError("VoiceRig sidecar is not configured for an allowed destination")
    try:
        timeout = max(5.0, float(os.getenv("VOICERIG_TTS_TIMEOUT_SECONDS", "180")))
    except ValueError:
        timeout = 180.0

    try:
        response = httpx.post(
            base + "/api/tts/synthesize",
            json={"text": text, "voice_package": package_name},
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"VoiceRig sidecar synthesis failed: {exc}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if "audio/wav" not in content_type and "audio/x-wav" not in content_type:
        raise RuntimeError("VoiceRig sidecar returned a non-WAV response")
    if not response.content:
        raise RuntimeError("VoiceRig sidecar returned empty audio")

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".wav.tmp") as tmp:
        temp_path = Path(tmp.name)
        tmp.write(response.content)
    try:
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)

    sr, duration = _wav_meta(target)
    try:
        sr = int(response.headers.get("x-voicerig-sample-rate", "")) or sr
    except ValueError:
        pass
    try:
        duration = float(response.headers.get("x-voicerig-duration", "")) or duration
    except ValueError:
        pass
    return {
        "out_path": str(target),
        "sample_rate": sr,
        "duration": round(duration, 3),
        "voice": response.headers.get("x-voicerig-voice") or package_name,
        "voice_id": response.headers.get("x-voicerig-voice-id"),
        "backend": "mrvoice-sidecar",
        "device": response.headers.get("x-voicerig-device"),
    }
