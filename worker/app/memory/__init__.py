from .retrieval import MemoryRetrievalQuery, MemoryRetriever, RankedMemory
from .semantic import (
    DEFAULT_MIN_SEMANTIC_SCORE,
    MAX_SEMANTIC_CANDIDATES,
    MAX_SEMANTIC_INPUT_RECORDS,
    MAX_SEMANTIC_TEXT_CHARS,
    MAX_SEMANTIC_VECTOR_DIMS,
    HybridMemoryRetriever,
    SemanticMemoryConfig,
    SemanticMemoryError,
    SemanticRankedMemory,
)
from .storage import (
    MAX_MEMORY_READ_CANDIDATES,
    MAX_MEMORY_READ_CHARS,
    MAX_MEMORY_READ_SUBJECTS,
    MemoryReadRequest,
    SharedMemoryReadError,
    SharedMemoryReader,
    SharedMemoryRecord,
)


async def embed_memory_text_local(text: str) -> list[float]:
    """Lazily enter the ModelRig-specific local Ollama adapter.

    Keeping this import inside the call preserves the shared package's neutral
    import boundary for R01/R02/R03 core users that never enable semantics.
    """
    from .local_embeddings import embed_memory_text_local as _embed

    return await _embed(text)


__all__ = [
    "DEFAULT_MIN_SEMANTIC_SCORE",
    "MAX_MEMORY_READ_CANDIDATES",
    "MAX_MEMORY_READ_CHARS",
    "MAX_MEMORY_READ_SUBJECTS",
    "MAX_SEMANTIC_CANDIDATES",
    "MAX_SEMANTIC_INPUT_RECORDS",
    "MAX_SEMANTIC_TEXT_CHARS",
    "MAX_SEMANTIC_VECTOR_DIMS",
    "HybridMemoryRetriever",
    "MemoryReadRequest",
    "MemoryRetrievalQuery",
    "MemoryRetriever",
    "RankedMemory",
    "SemanticMemoryConfig",
    "SemanticMemoryError",
    "SemanticRankedMemory",
    "SharedMemoryReadError",
    "SharedMemoryReader",
    "SharedMemoryRecord",
    "embed_memory_text_local",
]
