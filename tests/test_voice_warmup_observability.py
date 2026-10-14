"""Voice startup warmup regression without CUDA or Piper installed."""
import asyncio
import os
import sys
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app import voice_warmup


class VoiceWarmupTests(unittest.TestCase):
    def test_serial_model_loads_and_duration_logging(self):
        events = []

        def load_asr():
            events.append("asr")

        def load_piper():
            events.append("piper")

        with patch.object(voice_warmup, "log") as log, \
             patch("app.voice_asr.is_available", return_value=True), \
             patch("app.voice_asr._get_model", side_effect=load_asr), \
             patch("app.voice_tts.is_available", return_value=True), \
             patch("app.voice_tts._get_voice", side_effect=load_piper), \
             patch.dict(os.environ, {"MODELRIG_VOICE_PREWARM_PIPER": "1"}):
            asyncio.run(voice_warmup.warm_voice_models())
        self.assertEqual(events, ["asr", "piper"])
        self.assertEqual(log.info.call_count, 2)
        self.assertIn("in %.2fs", log.info.call_args_list[0].args[0])
        self.assertGreaterEqual(log.info.call_args_list[0].args[1], 0)

    def test_disabled_piper_does_not_load(self):
        with patch("app.voice_asr.is_available", return_value=False), \
             patch("app.voice_tts._get_voice", side_effect=AssertionError("Piper loaded")), \
             patch.dict(os.environ, {"MODELRIG_VOICE_PREWARM_PIPER": "0"}):
            asyncio.run(voice_warmup.warm_voice_models())

    def test_lifespan_remains_nonblocking_and_cancels_task(self):
        @asynccontextmanager
        async def inner(app):
            yield

        started = asyncio.Event()

        async def slow_prewarm():
            started.set()
            await asyncio.Event().wait()

        lifespan = voice_warmup.compose_voice_warmup_lifespan(inner)
        async def exercise():
            with patch.object(voice_warmup, "warm_voice_models", slow_prewarm), \
                 patch.dict(os.environ, {"MODELRIG_VOICE_PREWARM": "1"}):
                async with lifespan(None):
                    await asyncio.wait_for(started.wait(), timeout=2)
                remaining = [t for t in asyncio.all_tasks()
                             if t.get_name() == "voice-model-prewarm" and not t.done()]
                self.assertFalse(remaining)
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
