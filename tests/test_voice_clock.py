"""Clock requests must return a real local time without invoking an LLM."""
import asyncio
import os
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app import voice_pipeline


class ClockVoiceTest(unittest.TestCase):
    def test_clock_uses_local_timezone_and_bypasses_llm(self):
        async def never_chat(*args, **kwargs):
            raise AssertionError("Clock requests must not call the language model")
            yield b""
        with patch.object(voice_pipeline.voice_asr, "is_available", return_value=True), \
             patch.object(voice_pipeline.voice_tts, "is_available", return_value=True), \
             patch.object(voice_pipeline.voice_asr, "transcribe_wav", return_value={"text": "Hvad er klokken lige nu?", "language": "da"}), \
             patch.object(voice_pipeline.voice_tts, "synthesize_to_wav", return_value={"duration": 1.0}), \
             patch.object(voice_pipeline.body_session, "note_speech"), \
             patch.object(voice_pipeline.oc, "chat_stream", never_chat):
            with tempfile.TemporaryDirectory() as directory:
                result = asyncio.run(voice_pipeline.converse("test.wav", out_dir=directory))
        self.assertRegex(result["reply"], r"^Klokken er [0-2][0-9]:[0-5][0-9]\.$")
        self.assertNotIn("[indsæt", result["reply"].lower())
        self.assertEqual(len(result["chunks"]), 1)
        timings = result["timings"]
        self.assertGreaterEqual(timings["asr_s"], 0)
        self.assertGreaterEqual(timings["tts_s"], 0)
        self.assertGreaterEqual(timings["to_first_audio_from_request_s"], 0)
        self.assertGreaterEqual(result["total_s"], timings["asr_s"])


if __name__ == "__main__":
    unittest.main()
