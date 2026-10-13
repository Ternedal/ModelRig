"""Regression checks for the low-latency voice-specific Ollama profile.

Run: python -m unittest discover -s tests -p 'test_voice_fast_profile.py'
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import voice_pipeline


class VoiceProfileTest(unittest.TestCase):
    def test_local_voice_is_fast_and_cloud_does_not_inherit_local_options(self):
        async def exercise(cloud):
            seen = {}
            async def stream(messages, **kwargs):
                seen.update(kwargs)
                yield (json.dumps({"message": {"content": "Hej."}}) + "\n").encode()
            async def fake_asr(*args):
                return {"text": "Hej", "language": "da"}
            async def fake_tts(*args):
                return {"duration": 1}
            with patch.object(voice_pipeline.voice_asr, "is_available", return_value=True), \
                 patch.object(voice_pipeline.voice_tts, "is_available", return_value=True), \
                 patch.object(voice_pipeline.voice_asr, "transcribe_wav", return_value={"text": "Hej", "language": "da"}), \
                 patch.object(voice_pipeline.voice_tts, "synthesize_to_wav", return_value={"duration": 1}), \
                 patch.object(voice_pipeline.body_session, "note_speech"), \
                 patch.object(voice_pipeline.oc, "chat_stream", stream):
                import tempfile
                with tempfile.TemporaryDirectory() as directory:
                    await voice_pipeline.converse("unused.wav", out_dir=directory,
                        llm_base_url="https://example.com" if cloud else None)
            return seen
        local = asyncio.run(exercise(False))
        self.assertIs(local["think"], False)
        self.assertEqual(local["options"], {"num_ctx": 8192, "num_predict": 128})
        self.assertEqual(local["keep_alive"], "15m")
        cloud = asyncio.run(exercise(True))
        self.assertIsNone(cloud["think"])
        self.assertIsNone(cloud["options"])
        self.assertIsNone(cloud["keep_alive"])


if __name__ == "__main__":
    unittest.main()
