"""Optional background ASR model prewarm, without changing default startup."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import time

log = logging.getLogger(__name__)


async def prewarm_asr() -> None:
    """Load the same singleton used by requests; never claim ready on failure."""
    from . import voice_asr

    started = time.monotonic()
    try:
        # _get_model holds its own threading lock. A simultaneous real request
        # waits for that same initialization instead of loading a second model.
        await asyncio.to_thread(voice_asr._get_model)
    except Exception:
        # No transcript, path, model secret or raw exception in routine logs.
        log.warning("ASR prewarm failed after %.2fs", time.monotonic() - started)
    else:
        log.info("ASR prewarm completed after %.2fs", time.monotonic() - started)


def compose_asr_prewarm_lifespan(inner):
    @asynccontextmanager
    async def lifespan(app):
        async with inner(app):
            task = None
            if os.getenv("MODELRIG_VOICE_PREWARM", "0") == "1":
                task = asyncio.create_task(prewarm_asr(), name="asr-prewarm")
            try:
                yield
            finally:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    lifespan.__wrapped__ = getattr(inner, "__wrapped__", inner)
    return lifespan
