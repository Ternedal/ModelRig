#!/usr/bin/env python3
"""Loopback VoiceRig sidecar contract without requiring Chatterbox in CI."""
from __future__ import annotations

import io
import json
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile

from app import voice_sidecar


def wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x00" * 2400)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        assert self.path == "/api/tts/status"
        body = json.dumps({"ok": True, "voice": "Anders", "package": "anders.mrvoice"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        assert self.path == "/api/tts/synthesize"
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        assert request["text"] == "Hej"
        assert request["voice_package"] == "anders.mrvoice"
        body = wav_bytes()
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


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old_url = os.environ.get("VOICERIG_TTS_URL")
    old_remote = os.environ.get("VOICERIG_ALLOW_REMOTE")
    try:
        os.environ["VOICERIG_TTS_URL"] = f"http://127.0.0.1:{server.server_port}"
        os.environ.pop("VOICERIG_ALLOW_REMOTE", None)
        assert voice_sidecar.is_configured() is True
        assert voice_sidecar.status()["ok"] is True

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "speech.wav"
            result = voice_sidecar.synthesize_to_wav("Hej", str(target), "anders.mrvoice")
            assert target.is_file()
            assert result["sample_rate"] == 24000
            assert result["duration"] == 0.1
            assert result["backend"] == "mrvoice-sidecar"
            assert result["device"] == "cuda"

        os.environ["VOICERIG_TTS_URL"] = "https://example.com"
        assert voice_sidecar.is_configured() is False
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

    print("worker voice sidecar: OK")


if __name__ == "__main__":
    main()
