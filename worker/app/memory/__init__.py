from .consolidation import (
    MAX_CONSOLIDATION_CANDIDATES,
    MAX_CONSOLIDATION_EXISTING,
    MAX_CONSOLIDATION_TEXT_CHARS,
    ConsolidationAction,
    ConsolidationPlan,
    ConsolidationReceipt,
    ExistingMemory,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from .extraction import (
    MAX_CANDIDATE_EVIDENCE_CHARS,
    MAX_CANDIDATE_PREDICATE_CHARS,
    MAX_CANDIDATE_SUBJECT_CHARS,
    MAX_CANDIDATE_VALUE_CHARS,
    MAX_COMPLETED_TURN_CHARS,
    MAX_MEMORY_CANDIDATES,
    MAX_MODEL_OUTPUT_CHARS,
    MAX_SOURCE_REF_CHARS,
    MEMORY_CANDIDATE_SCHEMA,
    CompletedMemoryTurn,
    MemoryCandidate,
    MemoryCandidateExtractor,
    MemoryExtractionError,
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


async def extract_memory_candidates_local(
    turn: CompletedMemoryTurn,
    *,
    model: str | None = None,
) -> tuple[MemoryCandidate, ...]:
    """Lazily enter the local-only Memory 4 candidate extraction adapter."""
    from .local_extraction import extract_memory_candidates_local as _extract

    return await _extract(turn, model=model)


__all__ = [
    "ConsolidationAction",
    "ConsolidationPlan",
    "ConsolidationReceipt",
    "DEFAULT_MIN_SEMANTIC_SCORE",
    "ExistingMemory",
    "MAX_CANDIDATE_EVIDENCE_CHARS",
    "MAX_CANDIDATE_PREDICATE_CHARS",
    "MAX_CANDIDATE_SUBJECT_CHARS",
    "MAX_CANDIDATE_VALUE_CHARS",
    "MAX_COMPLETED_TURN_CHARS",
    "MAX_CONSOLIDATION_CANDIDATES",
    "MAX_CONSOLIDATION_EXISTING",
    "MAX_CONSOLIDATION_TEXT_CHARS",
    "MAX_MEMORY_CANDIDATES",
    "MAX_MEMORY_READ_CANDIDATES",
    "MAX_MEMORY_READ_CHARS",
    "MAX_MEMORY_READ_SUBJECTS",
    "MAX_MODEL_OUTPUT_CHARS",
    "MAX_SEMANTIC_CANDIDATES",
    "MAX_SEMANTIC_INPUT_RECORDS",
    "MAX_SEMANTIC_TEXT_CHARS",
    "MAX_SEMANTIC_VECTOR_DIMS",
    "MAX_SOURCE_REF_CHARS",
    "MEMORY_CANDIDATE_SCHEMA",
    "CompletedMemoryTurn",
    "HybridMemoryRetriever",
    "MemoryCandidate",
    "MemoryCandidateExtractor",
    "MemoryConsolidationError",
    "MemoryConsolidator",
    "MemoryExtractionError",
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
]
