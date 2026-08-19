"""Voice TTS regression and portable `.mrvoice` integration contracts.

Run: PYTHONPATH=worker python3 tests/worker_voice_tts_empty_synthesis.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import types
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import voice_profiles, voice_sidecar, voice_tts  # noqa: E402
from app.voice_pipeline import has_speech, strip_markdown  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class _SilentVoice:
    def synthesize_wav(self, text, wav_file):  # noqa: ARG002
        return None


class _RealishVoice:
    def synthesize_wav(self, text, wav_file):  # noqa: ARG002
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x01" * 2205)


_tmp = tempfile.mkdtemp(prefix="kaliv-tts-")


def synth(voice, text):
    out = os.path.join(_tmp, f"chunk_{abs(hash(text)) % 9999:04d}.wav")
    voice_tts._voice = voice  # type: ignore[attr-defined]
    voice_tts._load_error = None  # type: ignore[attr-defined]
    return out, voice_tts.synthesize_to_wav(text, out)


# Existing Piper regressions: ordinary audio, empty synthesis and speakability.
out, res = synth(_RealishVoice(), "Motoren suger luft ind.")
check(res is not None and res.get("duration", 0) > 0,
      f"almindelig tekst giver lyd med varighed (fik {res.get('duration') if res else None})")
check(os.path.exists(out) and os.path.getsize(out) > 44,
      "wav-filen er skrevet og har indhold")

try:
    out, res = synth(_SilentVoice(), "\u2014")
    crashed = None
except Exception as exc:  # noqa: BLE001
    crashed = f"{type(exc).__name__}: {exc}"
    res = None

check(crashed is None,
      f"tavs syntese kaster IKKE -- det var rig-fejlen (fik {crashed})")
check(res is not None and res.get("duration") == 0,
      "tavs syntese rapporteres som nul varighed, ikke som en fejl")
if crashed is None and os.path.exists(out):
    try:
        with wave.open(out, "rb") as fh:
            readable = fh.getnframes() == 0
    except Exception:  # noqa: BLE001
        readable = False
    check(readable, "filen der bliver tilbage er en gyldig, tom wav")

unspeakable = ["\u2014", "...", "!", "  \u2013  ", "**", "\u2022", "?!", "\u2026", "   "]
missed = [t for t in unspeakable if has_speech(t)]
check(not missed, f"ordloes tekst naar ikke TTS (slap igennem: {missed})")

speakable_texts = ["Motoren suger luft ind.", "Trin 1.", "ok", "42", "A."]
blocked = [t for t in speakable_texts if not has_speech(t)]
check(not blocked, f"aegte tekst blokeres ikke (blokeret: {blocked})")
check(strip_markdown("\u2014").strip() != "" and not has_speech(strip_markdown("\u2014")),
      "strip_markdown efterlader em-dash som ikke-tom, men has_speech fanger den")


# Portable .mrvoice package contracts.
def _build_package(path: Path, *, evil: bool = False) -> None:
    payloads = {
        "reference.wav": b"reference",
        "conditioning.pt": b"conditioning",
        "preview.wav": b"preview",
    }
    checksums = {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()}
    manifest = {
        "format": "modelrig-voice",
        "format_version": 1,
        "id": "anders-test",
        "name": "Anders",
        "language": "da",
        "engine": {"name": "chatterbox-multilingual", "model": "v3"},
        "files": {
            "reference": "reference.wav",
            "conditioning": "conditioning.pt",
            "preview": "preview.wav",
        },
        "defaults": {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8},
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("checksums.json", json.dumps(checksums))
        for name, raw in payloads.items():
            zf.writestr(name, raw)
        if evil:
            zf.writestr("../escape", b"no")


with tempfile.TemporaryDirectory(prefix="mrvoice-contract-") as tmp:
    root = Path(tmp)
    old_voices = os.environ.get("MODELRIG_VOICES_DIR")
    os.environ["MODELRIG_VOICES_DIR"] = str(root)
    try:
        package = root / "anders.mrvoice"
        _build_package(package)
        manifest = voice_profiles.validate_package(package)
        check(manifest["id"] == "anders-test", ".mrvoice manifest valideres")
        check(voice_profiles.default_profile_path() == package,
              "en enkelt profil bliver automatisk default")
        profiles = voice_profiles.list_profiles()
        check(len(profiles) == 1 and profiles[0]["default"] and profiles[0]["valid"],
              "profil-listen markerer den gyldige default")

        second = root / "second.mrvoice"
        _build_package(second)
        check(voice_profiles.default_profile_path() is None,
              "flere profiler kræver eksplicit default")
        (root / "default.txt").write_text("anders.mrvoice\n", encoding="utf-8")
        check(voice_profiles.default_profile_path() == package,
              "default.txt vælger den ønskede profil")

        evil = root / "evil.mrvoice"
        _build_package(evil, evil=True)
        try:
            voice_profiles.validate_package(evil)
            traversal_rejected = False
        except ValueError as exc:
            traversal_rejected = "invalid path" in str(exc)
        check(traversal_rejected, ".mrvoice path traversal afvises")

        calls: dict[str, object] = {}

        class _FakeLoaded:
            def to(self, device):
                calls["to"] = device
                return self

        class _FakeConditionals:
            @classmethod
            def load(cls, path, map_location="cpu"):
                calls["path"] = Path(path).name
                calls["map_location"] = map_location
                return _FakeLoaded()

        class _FakeModel:
            conds = None

            def prepare_conditionals(self, *_args, **_kwargs):
                raise AssertionError("saved conditioning unexpectedly rebuilt")

        fake_pkg = types.ModuleType("chatterbox")
        fake_pkg.__path__ = []
        fake_mtl = types.ModuleType("chatterbox.mtl_tts")
        fake_mtl.Conditionals = _FakeConditionals
        old_pkg = sys.modules.get("chatterbox")
        old_mtl = sys.modules.get("chatterbox.mtl_tts")
        sys.modules["chatterbox"] = fake_pkg
        sys.modules["chatterbox.mtl_tts"] = fake_mtl
        try:
            cond_root = root / "conditionals-contract"
            cond_root.mkdir()
            (cond_root / "conditioning.pt").write_bytes(b"fake")
            model = _FakeModel()
            voice_profiles._load_conditionals(model, cond_root, "cuda")
            check(calls == {
                "path": "conditioning.pt",
                "map_location": "cuda",
                "to": "cuda",
            } and model.conds is not None,
                  "Chatterbox Conditionals.load bruger map_location-kontrakten")
        finally:
            if old_pkg is None:
                sys.modules.pop("chatterbox", None)
            else:
                sys.modules["chatterbox"] = old_pkg
            if old_mtl is None:
                sys.modules.pop("chatterbox.mtl_tts", None)
            else:
                sys.modules["chatterbox.mtl_tts"] = old_mtl
    finally:
        if old_voices is None:
            os.environ.pop("MODELRIG_VOICES_DIR", None)
        else:
            os.environ["MODELRIG_VOICES_DIR"] = old_voices


# VoiceRig loopback sidecar contract without installing Chatterbox in CI.
def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x00" * 2400)
    return buf.getvalue()


class _SidecarHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        body = json.dumps({"ok": True, "voice": "Anders", "package": "anders.mrvoice"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path != "/api/tts/synthesize" or request.get("text") != "Hej":
            self.send_response(400)
            self.end_headers()
            return
        body = _wav_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-VoiceRig-Voice", "Anders")
        self.send_header("X-VoiceRig-Voice-ID", "anders-test")
        self.send_header("X-VoiceRig-Sample-Rate", "24000")
        self.send_header("X-VoiceRig-Duration", "0.1")
        self.send_header("X-VoiceRig-Device", "cuda")
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), _SidecarHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
old_url = os.environ.get("VOICERIG_TTS_URL")
old_remote = os.environ.get("VOICERIG_ALLOW_REMOTE")
try:
    os.environ["VOICERIG_TTS_URL"] = f"http://127.0.0.1:{server.server_port}"
    os.environ.pop("VOICERIG_ALLOW_REMOTE", None)
    check(voice_sidecar.is_configured(), "VoiceRig loopback-sidecar accepteres")
    check(voice_sidecar.status().get("ok") is True, "VoiceRig sidecar-status kan læses")

    with tempfile.TemporaryDirectory(prefix="mrvoice-sidecar-") as tmp:
        target = Path(tmp) / "speech.wav"
        result = voice_sidecar.synthesize_to_wav("Hej", str(target), "anders.mrvoice")
        check(target.is_file() and result["sample_rate"] == 24000
              and result["duration"] == 0.1 and result["device"] == "cuda",
              "sidecar-syntese skriver WAV og bevarer metadata")

    os.environ["VOICERIG_TTS_URL"] = "https://example.com"
    check(not voice_sidecar.is_configured(), "remote VoiceRig afvises som default")
finally:
    server.shutdown()
    server.server_close()
    if old_url is None:
        os.environ.pop("VOICERIG_TTS_URL", None)
    else:
        os.environ["VOICERIG_TTS_URL"] = old_url
    if old_remote is None:
        os.environ.pop("VOICERIG_ALLOW_REMOTE", None)
    else:
        os.environ["VOICERIG_ALLOW_REMOTE"] = old_remote

print(f"\n===== VOICE TTS + MRVOICE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
