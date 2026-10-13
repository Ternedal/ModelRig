"""Optional serialized model prewarm. Disabled unless explicitly enabled."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import logging
import os

log = logging.getLogger(__name__)


async def warm_voice_models() -> None:
    """Warm available local ASR and Piper models without simultaneous GPU loads."""
    from . import voice_asr, voice_tts
    if voice_asr.is_available():
        try:
            await asyncio.to_thread(voice_asr._get_model)
            log.info("Voice ASR prewarm completed")
        except Exception:
            log.exception("Voice ASR prewarm failed; normal requests may retry")
    # Only prewarm Piper explicitly, not the auto-selected VoiceRig HTTP provider.
    if os.getenv("MODELRIG_VOICE_PREWARM_PIPER", "0") == "1":
        if voice_tts.is_available():
            try:
                await asyncio.to_thread(voice_tts._get_voice)
                log.info("Piper voice prewarm completed")
            except Exception:
                log.exception("Piper prewarm failed; normal requests may retry")


def compose_voice_warmup_lifespan(inner):
    @asynccontextmanager
    async def lifespan(app):
        async with inner(app):
            task = None
            if os.getenv("MODELRIG_VOICE_PREWARM", "0") == "1":
                task = asyncio.create_task(warm_voice_models())
            try:
                yield
            finally:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    # Preserve the production scheduler lifespan identity contract for
    # introspection and existing lifecycle regression tests.
    lifespan.__wrapped__ = getattr(inner, "__wrapped__", inner)
    return lifespan
