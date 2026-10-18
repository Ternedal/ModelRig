"""No-GPU checks for opt-in background ASR prewarm."""
import asyncio
from contextlib import asynccontextmanager
import os
import sys
import threading
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
                 patch.object(voice_prewarm, "prewarm_asr", side_effect=AssertionError("unexpected prewarm")) as prewarm:
                async with voice_prewarm.compose_asr_prewarm_lifespan(inner)(None):
                    await asyncio.sleep(0)
                prewarm.assert_not_called()
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

    def test_cancelled_prewarm_is_not_reported_as_loaded(self):
        started = threading.Event()
        release = threading.Event()

        def slow_model():
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test model release timed out")
            return object()

        async def run():
            # Wait for the worker thread to enter model construction before
            # cancelling; one event-loop tick is not a reliable barrier.
            with patch("app.voice_asr._get_model", side_effect=slow_model):
                task = asyncio.create_task(voice_prewarm.prewarm_asr())
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertEqual(voice_prewarm.prewarm_status()["state"], "cancelled")
                finally:
                    release.set()
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        asyncio.run(run())

    def test_success_and_failure_never_expose_exception(self):
        async def run():
            with patch("app.voice_asr._get_model", return_value=object()), \
                 patch.object(voice_prewarm, "log") as log:
                await voice_prewarm.prewarm_asr()
                log.info.assert_called_once()
                self.assertEqual(voice_prewarm.prewarm_status()["state"], "loaded")
                self.assertGreaterEqual(voice_prewarm.prewarm_status()["elapsed_seconds"], 0)
            with patch("app.voice_asr._get_model", side_effect=RuntimeError("PRIVATE_PATH")), \
                 patch.object(voice_prewarm, "log") as log:
                await voice_prewarm.prewarm_asr()
                self.assertNotIn("PRIVATE_PATH", str(log.warning.call_args))
                self.assertEqual(voice_prewarm.prewarm_status()["state"], "failed")
                self.assertGreaterEqual(voice_prewarm.prewarm_status()["elapsed_seconds"], 0)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
