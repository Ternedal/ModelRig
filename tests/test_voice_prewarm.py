"""No-GPU checks for opt-in background ASR prewarm."""
import asyncio
from contextlib import asynccontextmanager
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app import voice_prewarm


class VoicePrewarmTests(unittest.TestCase):
    def test_default_off(self):
        @asynccontextmanager
        async def inner(app):
            yield
        async def run():
            with patch.dict(os.environ, {"MODELRIG_VOICE_PREWARM": "0"}), \
                 patch.object(voice_prewarm, "prewarm_asr", side_effect=AssertionError("unexpected prewarm")):
                async with voice_prewarm.compose_asr_prewarm_lifespan(inner)(None):
                    pass
        asyncio.run(run())

    def test_opt_in_nonblocking_and_cleanup(self):
        @asynccontextmanager
        async def inner(app):
            yield
        started = asyncio.Event()
        async def blocked():
            started.set()
            await asyncio.Event().wait()
        async def run():
            with patch.dict(os.environ, {"MODELRIG_VOICE_PREWARM": "1"}), \
                 patch.object(voice_prewarm, "prewarm_asr", blocked):
                async with voice_prewarm.compose_asr_prewarm_lifespan(inner)(None):
                    await asyncio.wait_for(started.wait(), timeout=2)
                tasks = [t for t in asyncio.all_tasks() if t.get_name() == "asr-prewarm" and not t.done()]
                self.assertFalse(tasks)
        asyncio.run(run())

    def test_success_and_failure_never_expose_exception(self):
        async def run():
            with patch("app.voice_asr._get_model", return_value=object()), \
                 patch.object(voice_prewarm, "log") as log:
                await voice_prewarm.prewarm_asr()
                log.info.assert_called_once()
            with patch("app.voice_asr._get_model", side_effect=RuntimeError("PRIVATE_PATH")), \
                 patch.object(voice_prewarm, "log") as log:
                await voice_prewarm.prewarm_asr()
                self.assertNotIn("PRIVATE_PATH", str(log.warning.call_args))
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
