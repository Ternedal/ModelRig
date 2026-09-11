from .candidates import (
    CANDIDATE_SCHEMA,
    MAX_EXTRACTOR_RESPONSE_BYTES,
    MAX_MEMORY_CANDIDATES,
    MAX_TURN_CHARS,
    CandidateBatch,
    CompletedTurn,
    MemoryCandidate,
    MemoryCandidateError,
    parse_candidate_batch,
    prepare_completed_turn,
)
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


async def extract_memory_candidates_local(turn: CompletedTurn) -> CandidateBatch:
    """Lazily enter the ModelRig-specific local W01A extraction adapter."""
    from .local_extraction import extract_memory_candidates_local as _extract

    return await _extract(turn)


__all__ = [
    "CANDIDATE_SCHEMA",
    "DEFAULT_MIN_SEMANTIC_SCORE",
    "MAX_EXTRACTOR_RESPONSE_BYTES",
    "MAX_MEMORY_CANDIDATES",
    "MAX_MEMORY_READ_CANDIDATES",
    "MAX_MEMORY_READ_CHARS",
    "MAX_MEMORY_READ_SUBJECTS",
    "MAX_SEMANTIC_CANDIDATES",
    "MAX_SEMANTIC_INPUT_RECORDS",
    "MAX_SEMANTIC_TEXT_CHARS",
    "MAX_SEMANTIC_VECTOR_DIMS",
    "MAX_TURN_CHARS",
    "CandidateBatch",
    "CompletedTurn",
    "HybridMemoryRetriever",
    "MemoryCandidate",
    "MemoryCandidateError",
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
    "extract_memory_candidates_local",
    "parse_candidate_batch",
    "prepare_completed_turn",
]
