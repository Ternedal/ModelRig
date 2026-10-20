"""Optional background ASR model prewarm, without changing default startup."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import threading
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
    loop = asyncio.get_running_loop()
    completed = loop.create_future()
    abandoned = threading.Event()

    def signal_done():
        if not completed.done():
            completed.set_result(None)

    def load_in_daemon():
        global _state, _elapsed_seconds
        # The singleton owns its own lock. Do not use asyncio.to_thread here:
        # asyncio.run() waits for the default executor even after cancellation.
        try:
            voice_asr._get_model()
        except Exception:
            if not abandoned.is_set():
                _state = "failed"
                _elapsed_seconds = round(time.monotonic() - started, 3)
                # Deliberately omit raw native exceptions, paths and transcripts.
                log.warning("ASR prewarm failed after %.2fs", time.monotonic() - started)
        else:
            if not abandoned.is_set():
                _state = "loaded"
                _elapsed_seconds = round(time.monotonic() - started, 3)
                log.info("ASR prewarm completed after %.2fs", time.monotonic() - started)
        finally:
            if not abandoned.is_set():
                try:
                    loop.call_soon_threadsafe(signal_done)
                except RuntimeError:
                    # The loop was shut down. Never resurrect an event loop.
                    pass

    # A native model load is not cancellable. A dedicated daemon avoids
    # blocking event-loop shutdown on an unbounded default-executor thread.
    # On cancellation, ignore late results; the shared ASR lock still
    # prevents a second simultaneous load in the same process.
    threading.Thread(target=load_in_daemon, name="asr-prewarm-loader", daemon=True).start()
    try:
        await completed
    except asyncio.CancelledError:
        abandoned.set()
        _state = "cancelled"
        _elapsed_seconds = round(time.monotonic() - started, 3)
        raise

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
                    # Shutdown cancels the wait without joining a native GPU load.
                    # The detached daemon ends with the worker process.
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    lifespan.__wrapped__ = getattr(inner, "__wrapped__", inner)
    return lifespan
