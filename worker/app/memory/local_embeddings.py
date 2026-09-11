from __future__ import annotations

from .. import ollama_client


async def embed_memory_text_local(text: str) -> list[float]:
    """Embed memory text through ModelRig's local Ollama embedding client only.

    This adapter intentionally exposes no base URL, API key or cloud override.
    It reuses ``MODELRIG_OLLAMA_URL``/``MODELRIG_EMBED_MODEL`` from the existing
    local RAG stack and delegates vector validation to the semantic retriever.
    """
    return await ollama_client.embed(text)
