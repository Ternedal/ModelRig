"""CPU-only tests for the opt-in ASR cold/warm timing CLI."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "asr_cold_warm_probe.py"
spec = importlib.util.spec_from_file_location("asr_cold_warm_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_outputs_timing_but_no_transcript_or_audio_path(self):
        calls = []
        fake_asr = types.ModuleType("app.voice_asr")
        secret = "PRIVATE TRANSCRIPT NEVER LOG"
        def transcribe(path, language="da"):
            self.assertEqual(language, "da")
            calls.append(path)
            return {"text": secret}
        fake_asr.transcribe_wav = transcribe
        fake_asr._get_model = lambda: object()
        fake_asr._device = lambda: "cuda"
        fake_asr._model_name = lambda: "large-v3"
        fake_asr._compute_type = lambda: "int8"
        fake_app = types.ModuleType("app")
        fake_app.voice_asr = fake_asr
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "private-audio.wav"
            audio.write_bytes(b"fake audio")
            out = io.StringIO()
            with patch.object(sys, "argv", ["probe", "--audio", str(audio), "--runs", "3"]), \
                 patch.dict(sys.modules, {"app": fake_app, "app.voice_asr": fake_asr}), \
                 contextlib.redirect_stdout(out):
                self.assertEqual(probe.main(), 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["language"], "da")
            self.assertIn("model_load_seconds", payload)
            self.assertIn("first_inference_seconds", payload)
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(payload["warm_seconds"]), 2)
            self.assertNotIn(secret, out.getvalue())
            self.assertNotIn(str(audio), out.getvalue())

    def test_failure_does_not_leak_exception_details(self):
        fake_asr = types.ModuleType("app.voice_asr")
        def fail(_path, language="da"):
            raise RuntimeError("secret user audio path and transcript")
        fake_asr.transcribe_wav = fail
        fake_asr._get_model = lambda: object()
        fake_app = types.ModuleType("app")
        fake_app.voice_asr = fake_asr
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "sensitive.wav"
            audio.write_bytes(b"x")
            out = io.StringIO()
            with patch.object(sys, "argv", ["probe", "--audio", str(audio)]), \
                 patch.dict(sys.modules, {"app": fake_app, "app.voice_asr": fake_asr}), \
                 contextlib.redirect_stdout(out):
                self.assertEqual(probe.main(), 1)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload, {"ok": False, "error_type": "RuntimeError"})
            self.assertNotIn("secret user", out.getvalue())
            self.assertNotIn(str(audio), out.getvalue())

    def test_rejects_single_run(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "test.wav"
            audio.write_bytes(b"x")
            with patch.object(sys, "argv", ["probe", "--audio", str(audio), "--runs", "1"]), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    probe.main()
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
