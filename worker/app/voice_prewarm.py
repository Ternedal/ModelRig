"""Optional background ASR model prewarm, without changing default startup."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import time

log = logging.getLogger(__name__)

# In-process diagnostics only; no HTTP endpoint or user content.
_state = "not_started"
_elapsed_seconds = None


def prewarm_status() -> dict:
    """Snapshot of initialization only (not proof of successful inference)."""
    return {"state": _state, "elapsed_seconds": _elapsed_seconds}


async def prewarm_asr() -> None:
    """Load the same singleton used by requests; never claim ready on failure."""
    from . import voice_asr

    global _state, _elapsed_seconds
    _state = "loading"
    _elapsed_seconds = None
    started = time.monotonic()
    try:
        # _get_model holds its own threading lock. A simultaneous real request
        # waits for that same initialization instead of loading a second model.
        await asyncio.to_thread(voice_asr._get_model)
    except asyncio.CancelledError:
        _state = "cancelled"
        _elapsed_seconds = round(time.monotonic() - started, 3)
        raise
    except Exception:
        _state = "failed"
        _elapsed_seconds = round(time.monotonic() - started, 3)
        # No transcript, path, model secret or raw exception in routine logs.
        log.warning("ASR prewarm failed after %.2fs", time.monotonic() - started)
    else:
        _state = "loaded"
        _elapsed_seconds = round(time.monotonic() - started, 3)
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
                    # Cancellation stops the coroutine, but cannot forcibly
                    # terminate an already running to_thread() native load.
                    # The ASR singleton lock still prevents duplicate loads.
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    lifespan.__wrapped__ = getattr(inner, "__wrapped__", inner)
    return lifespan
