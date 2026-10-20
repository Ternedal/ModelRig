"""Run the real PS helper against loopback fixtures, never physical evidence.

Windows CI runs this with both Windows PowerShell 5.1 and PowerShell 7. The
ordinary Linux suite also runs it when pwsh is installed. The fixtures simulate
API contracts and write a synthetic WAV; they do not execute ASR/TTS or a GPU.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test-installed-voice.ps1"
COMMIT = "3d52cc97735b9572225cc5776d9ebc16656951b6"
ARTIFACT = "9a7cfbaa2e69565e30fab387076d1e099d9d65173218e0cf677ce84a7f1ddea6"
REQUESTED_SHELL = os.environ.get("MODELRIG_POWERSHELL_EXECUTABLE")
SHELL = shutil.which(REQUESTED_SHELL or "pwsh")
if REQUESTED_SHELL and not SHELL:
    raise RuntimeError(f"Required PowerShell executable not found: {REQUESTED_SHELL}")


class Fixture:
    """Only the endpoints the installed diagnostic is allowed to use."""

    def __init__(self, case: str):
        self.case = case
        self.requests: list[tuple[str, str, str]] = []
        self.transcribed = False
        self.servers: list[ThreadingHTTPServer] = []
        self.threads: list[threading.Thread] = []

    def start(self, role: str) -> int:
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.handle_request(None)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.handle_request(body)

            def handle_request(self, body):
                fixture.requests.append((role, self.command, self.path))
                code, payload, headers = fixture.respond(role, self.path, body)
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.servers.append(server)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.threads.append(thread)
        return server.server_port

    def close(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)

    def respond(self, role: str, path: str, body):
        case = self.case
        if path == "/healthz":
            version = "2.0.16" if case == f"old-{role}" else "2.0.17"
            return 200, {"status": "ok", "service": f"modelrig-{role}", "version": version}, {}
        if role != "worker":
            return 404, {}, {}
        if path == "/health/full":
            artifact = ARTIFACT
            if case == "wrong-artifact" or (case == "replaced-worker" and self.transcribed):
                artifact = "f" * 64
            return 200, {
                "build": {
                    "frozen": False if case == "source-worker" else True,
                    "commit_sha": "0" * 40 if case == "wrong-commit" else COMMIT,
                    "artifact_sha256": artifact,
                    "code_sha256": "a" * 64,
                },
                "capabilities": {
                    "asr": "true" if case == "string-capability" else True,
                    "tts": True, "cuda": case != "no-cuda",
                },
            }, {}
        if path == "/voice/asr/status":
            if case == "redirect":
                return 302, {}, {"Location": "/trap"}
            if case == "oversized":
                return 200, b'{"padding":"' + b"x" * 65536 + b'"}', {}
            if case == "array-status":
                return 200, [{"available": True, "device": "cuda"}], {}
            return 200, {
                "available": False if case == "no-asr" else True,
                "device": "cpu" if case == "cpu-asr" else "cuda",
                "model": "other-model" if case == "changed-config" and self.transcribed else "large-v3",
                "compute_type": "int8", "cuda_dll_dirs": ["fixture-cuda"] if self.transcribed else [],
            }, {}
        if path == "/voice/tts/status":
            return 200, {"available": case != "no-tts", "voice": "fixture-da"}, {}
        if path == "/voice/tts/synthesize" and body:
            target = Path(body["out_path"])
            if case == "bad-wav":
                target.write_bytes(b"not a WAV" * 20)
            elif case != "missing-wav":
                with wave.open(str(target), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(struct.pack("<h", 100) * 16000)
            return 200, {
                "out_path": str(target), "duration": 1.0,
                "provider": "voicerig" if case == "voicerig" else "piper",
            }, {}
        if path == "/voice/asr/transcribe" and body:
            assert Path(body["path"]).is_file() and body["language"] == "da"
            if case == "asr-503":
                return 503, {"detail": "fixture: cublas64_12.dll cannot be loaded"}, {}
            self.transcribed = True
            return 200, {
                "text": "" if case == "empty-transcript" else "Hej Kaliv. Dette er en dansk lydtest.",
                "duration": 1.0,
                "segments": [] if case == "empty-segments" else [{"start": 0, "end": 1, "text": "Hej Kaliv."}],
            }, {}
        return 404, {}, {}


@unittest.skipUnless(SHELL, "PowerShell unavailable; mandatory Windows jobs exercise both 5.1 and 7")
class InstalledVoiceCheck(unittest.TestCase):
    def run_case(self, case: str):
        fixture = Fixture(case)
        try:
            server_port = fixture.start("server")
            worker_port = fixture.start("worker")
            with tempfile.TemporaryDirectory(prefix="installed voice fixture ") as temporary:
                rig = Path(temporary)
                sentinel = rig / "config.env"
                sentinel.write_text("fixture configuration must stay unchanged\n", encoding="utf-8")
                env = dict(os.environ, HTTP_PROXY="http://127.0.0.1:1", HTTPS_PROXY="http://127.0.0.1:1",
                           ALL_PROXY="http://127.0.0.1:1", NO_PROXY="")
                result = subprocess.run([
                    SHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(SCRIPT), "-RigRoot", str(rig),
                    "-ServerPort", str(server_port), "-WorkerPort", str(worker_port),
                    "-InferenceTimeoutSeconds", "5",
                ], capture_output=True, text=True, errors="replace", timeout=30, env=env)
                reports = list((rig / "diagnostics").glob("*/installed-voice.json"))
                self.assertEqual(len(reports), 1, result.stdout + result.stderr)
                report = json.loads(reports[0].read_text(encoding="utf-8-sig"))
                self.assertEqual(report["schema"], "kaliv-installed-voice-diagnostic/v1")
                self.assertTrue(report["synthetic_audio"])
                self.assertIs(report["v1_accepted"], False)
                self.assertEqual(set(p.name for p in rig.iterdir()), {"diagnostics", "config.env"})
                self.assertEqual(sentinel.read_text(), "fixture configuration must stay unchanged\n")
                self.assertFalse(any(path == "/trap" for _, _, path in fixture.requests))
                return result, report, fixture.requests
        finally:
            fixture.close()

    def test_synthetic_roundtrip_and_both_existing_providers(self):
        for case in ("piper", "voicerig"):
            with self.subTest(case=case):
                result, report, requests = self.run_case(case)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(report["status"], "diagnostic_pass")
                self.assertTrue(all(c["passed"] for c in report["checks"]))
                self.assertEqual(report["tts"]["provider"], case)
                self.assertEqual([p for _, method, p in requests if method == "POST"],
                                 ["/voice/tts/synthesize", "/voice/asr/transcribe"])
                self.assertEqual(report["before"]["build"], report["after"]["build"])

    def test_rejects_bad_identity_and_unavailable_or_cpu_voice_before_inference(self):
        for case in ("old-server", "old-worker", "source-worker", "wrong-commit", "wrong-artifact",
                     "string-capability", "no-cuda", "no-asr", "cpu-asr", "no-tts",
                     "redirect", "oversized", "array-status"):
            with self.subTest(case=case):
                result, report, requests = self.run_case(case)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(report.get("error"))
                self.assertFalse(any(method == "POST" for _, method, _ in requests))

    def test_rejects_failed_inference_and_changes_during_inference(self):
        for case in ("missing-wav", "bad-wav", "asr-503", "empty-transcript", "empty-segments",
                     "replaced-worker", "changed-config"):
            with self.subTest(case=case):
                result, report, requests = self.run_case(case)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(report.get("error"))
                if case in {"missing-wav", "bad-wav"}:
                    self.assertNotIn(("worker", "POST", "/voice/asr/transcribe"), requests)
                if case == "asr-503":
                    self.assertIn("503", report["error"])
                    self.assertIn("cublas64_12.dll", report["error"])


if __name__ == "__main__":
    unittest.main()
