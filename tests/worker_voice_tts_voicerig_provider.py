"""Regression contract for VoiceRig -> ModelRig TTS provider selection.

Run:
    PYTHONPATH=worker python3 tests/worker_voice_tts_voicerig_provider.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import voice_tts  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class _RealishVoice:
    def synthesize_wav(self, text, wav_file):  # noqa: ARG002
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x01" * 2205)


tmp = tempfile.mkdtemp(prefix="modelrig-voicerig-provider-")
voices = os.path.join(tmp, "voices")
os.makedirs(voices, exist_ok=True)
open(os.path.join(voices, "anders.mrvoice"), "wb").close()

old_env = {
    "MODELRIG_VOICES_DIR": os.environ.get("MODELRIG_VOICES_DIR"),
    "TTS_PROVIDER": os.environ.get("TTS_PROVIDER"),
}
old_status = voice_tts._voicerig_status
old_synth = voice_tts._synthesize_voicerig
old_voice = voice_tts._voice

try:
    os.environ["MODELRIG_VOICES_DIR"] = voices
    os.environ["TTS_PROVIDER"] = "auto"

    voice_tts._voicerig_status = lambda timeout=1.5: {
        "ok": True,
        "voice": "Anders",
        "package": "anders.mrvoice",
        "device": "cuda",
    }

    def fake_voicerig(text, out_path):
        with wave.open(out_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(b"\x00\x01" * 2400)
        return {
            "out_path": out_path,
            "sample_rate": 24000,
            "duration": 0.1,
            "voice": "Anders",
            "provider": "voicerig",
        }

    voice_tts._synthesize_voicerig = fake_voicerig
    out = os.path.join(tmp, "voicerig.wav")
    res = voice_tts.synthesize_to_wav("Hej.", out)
    check(res.get("provider") == "voicerig", "auto vælger VoiceRig når .mrvoice + sidecar er klar")
    check(res.get("voice") == "Anders", "VoiceRig-stemmens navn bevares i kontrakten")
    check(os.path.exists(out) and os.path.getsize(out) > 44, "VoiceRig-path skriver en gyldig WAV")

    st = voice_tts.status()
    check(st.get("ok") is True and st.get("provider") == "voicerig",
          "status rapporterer VoiceRig som aktiv provider")

    voice_tts._voicerig_status = lambda timeout=1.5: {
        "ok": False,
        "detail": "sidecar offline",
    }
    voice_tts._voice = _RealishVoice()
    out = os.path.join(tmp, "piper.wav")
    res = voice_tts.synthesize_to_wav("Fallback.", out)
    check(res.get("provider") == "piper", "auto falder tilbage til Piper når VoiceRig er nede")
    check(res.get("duration", 0) > 0, "Piper-fallback producerer lyd")

    os.environ["TTS_PROVIDER"] = "voicerig"
    try:
        voice_tts.synthesize_to_wav("Skal fejle.", os.path.join(tmp, "fail.wav"))
        explicit_failed = False
    except RuntimeError as exc:
        explicit_failed = "sidecar offline" in str(exc)
    check(explicit_failed, "TTS_PROVIDER=voicerig falder ikke lydløst tilbage til Piper")

finally:
    voice_tts._voicerig_status = old_status
    voice_tts._synthesize_voicerig = old_synth
    voice_tts._voice = old_voice
    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

print(f"\n===== VOICERIG TTS PROVIDER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
