"""Regression for WAV primary decoder and M4A fallback. No GPU required."""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app import voice_asr


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "Hvad er klokken?"


class FakeModel:
    def __init__(self):
        self.received = None

    def transcribe(self, audio, **kwargs):
        self.received = audio
        return iter([FakeSegment()]), types.SimpleNamespace(language="da", duration=1.0)


class DecodeTest(unittest.TestCase):
    def test_m4a_unsupported_by_soundfile_uses_faster_whisper_decoder(self):
        model = FakeModel()
        fake_sf = types.ModuleType("soundfile")
        def unsupported(*args, **kwargs):
            raise RuntimeError("Error opening test.m4a: Format not recognised.")
        fake_sf.read = unsupported
        fake_audio = types.ModuleType("faster_whisper.audio")
        sentinel = object()
        fake_audio.decode_audio = lambda path, sampling_rate: sentinel
        with patch.object(voice_asr, "_get_model", return_value=model), \
             patch.dict(sys.modules, {"soundfile": fake_sf, "faster_whisper.audio": fake_audio}):
            result = voice_asr.transcribe_wav("test.m4a")
        self.assertIs(model.received, sentinel)
        self.assertEqual(result["text"], "Hvad er klokken?")

    def test_unrelated_decoder_error_is_not_silenced(self):
        fake_sf = types.ModuleType("soundfile")
        def denied(*args, **kwargs):
            raise RuntimeError("Permission denied")
        fake_sf.read = denied
        with patch.object(voice_asr, "_get_model", return_value=FakeModel()), \
             patch.dict(sys.modules, {"soundfile": fake_sf}):
            with self.assertRaisesRegex(RuntimeError, "Permission denied"):
                voice_asr.transcribe_wav("test.m4a")


if __name__ == "__main__":
    unittest.main()
