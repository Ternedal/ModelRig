from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from .retrieval import MemoryRetrievalQuery
from .semantic import HybridMemoryRetriever
from .storage import MemoryReadRequest, SharedMemoryReader


CONTEXT_SERVICE_SCHEMA = "kaliv-memory-context-service/v1"
CONTEXT_RECEIPT_SCHEMA = "kaliv-memory-context-receipt/v1"
MAX_TURN_QUERY_CHARS = 4_096
MAX_TURN_SUBJECTS = 64
MAX_TURN_RESULTS = 50
MAX_TURN_CONTEXT_CHARS = 12_000
SOURCE_CANDIDATE_LIMIT = 100
SOURCE_CHARACTER_BUDGET = 50_000


class MemoryContextServiceError(RuntimeError):
    """The context-for-turn service could not complete safely."""


class MemoryContextRequestError(MemoryContextServiceError):
    """The caller supplied a malformed or over-broad R04 request."""


@dataclass(frozen=True)
class ContextForTurnRequest:
    query: str
    target: str = "local"
    subjects: tuple[str, ...] = ()
    max_results: int = 12
    max_context_chars: int = MAX_TURN_CONTEXT_CHARS


@dataclass(frozen=True)
class ContextForTurnReceipt:
    schema: str
    target: str
    semantic_enabled: bool
    candidate_count: int
    ranked_count: int
    included_ids: tuple[str, ...]
    excluded_count: int
    exclusion_reasons: dict[str, int]
    character_count: int
    byte_count: int
    context_sha256: str
    sent_to_model: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "target": self.target,
            "semantic_enabled": self.semantic_enabled,
            "candidate_count": self.candidate_count,
            "ranked_count": self.ranked_count,
            "included_ids": list(self.included_ids),
            "excluded_count": self.excluded_count,
            "exclusion_reasons": dict(self.exclusion_reasons),
            "character_count": self.character_count,
            "byte_count": self.byte_count,
            "context_sha256": self.context_sha256,
            "sent_to_model": self.sent_to_model,
        }


@dataclass(frozen=True)
class ContextForTurnResult:
    context: str
    receipt: ContextForTurnReceipt

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_SERVICE_SCHEMA,
            "context": self.context,
            "receipt": self.receipt.to_dict(),
        }


class CompiledContextLike(Protocol):
    text: str
    included_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    character_count: int


class ContextCompilerLike(Protocol):
    def compile(
        self,
        records,
        *,
        target: str,
        allow_private_cloud: bool,
        max_chars: int,
        max_records: int,
    ) -> CompiledContextLike: ...


class MemoryContextForTurnService:
    """Read-only Memory 4 context builder with exact pre-model receipt.

    Private-cloud authority is deliberately not part of ``ContextForTurnRequest``.
    R04 cannot grant it: cloud-target requests are always built with
    ``allow_private_cloud=False``. A later integration slice must add a separate,
    authenticated policy boundary before that can ever change.
    """

    def __init__(
        self,
        *,
        reader: SharedMemoryReader,
        retriever: HybridMemoryRetriever,
        compiler: ContextCompilerLike,
    ) -> None:
        if not isinstance(reader, SharedMemoryReader):
            raise MemoryContextServiceError("SharedMemoryReader is required")
        if not isinstance(retriever, HybridMemoryRetriever):
            raise MemoryContextServiceError("HybridMemoryRetriever is required")
        if not callable(getattr(compiler, "compile", None)):
            raise MemoryContextServiceError("context compiler is required")
        self._reader = reader
        self._retriever = retriever
        self._compiler = compiler

    @property
    def semantic_enabled(self) -> bool:
        return self._retriever.config.enabled

    async def context_for_turn(
        self,
        request: ContextForTurnRequest,
    ) -> ContextForTurnResult:
        query, target, subjects, max_results, max_context_chars = self._validate(
            request
        )

        candidates = self._reader.read_candidates(
            MemoryReadRequest(
                target=target,
                subjects=subjects,
                # R04 has no authority-bearing request field for private cloud.
                allow_private_cloud=False,
                max_candidates=SOURCE_CANDIDATE_LIMIT,
                max_chars=SOURCE_CHARACTER_BUDGET,
            )
        )
        ranked = await self._retriever.rank(
            candidates,
            MemoryRetrievalQuery(
                text=query,
                subjects=subjects,
                target=target,
                allow_private_cloud=False,
                max_results=max_results,
            ),
        )

        compiled = self._compiler.compile(
            [item.record for item in ranked],
            target=target,
            allow_private_cloud=False,
            max_chars=max_context_chars,
            max_records=max_results,
        )
        if not isinstance(compiled.text, str):
            raise MemoryContextServiceError("context compiler returned non-text data")
        if compiled.character_count != len(compiled.text):
            raise MemoryContextServiceError("context compiler character count mismatch")

        candidate_ids = {record.id for record in candidates}
        ranked_ids = {item.record.id for item in ranked}
        included_ids = tuple(compiled.included_ids)
        included_set = set(included_ids)
        if (
            len(included_set) != len(included_ids)
            or not included_set.issubset(ranked_ids)
            or not ranked_ids.issubset(candidate_ids)
        ):
            raise MemoryContextServiceError("context compiler/retriever identity mismatch")

        not_relevant = len(candidate_ids - ranked_ids)
        context_budget = len(ranked_ids - included_set)
        exclusion_reasons = {
            "not_relevant_or_below_threshold": not_relevant,
            "context_budget": context_budget,
        }
        excluded_count = not_relevant + context_budget

        context_bytes = compiled.text.encode("utf-8")
        receipt = ContextForTurnReceipt(
            schema=CONTEXT_RECEIPT_SCHEMA,
            target=target,
            semantic_enabled=self.semantic_enabled,
            candidate_count=len(candidates),
            ranked_count=len(ranked),
            included_ids=included_ids,
            excluded_count=excluded_count,
            exclusion_reasons=exclusion_reasons,
            character_count=len(compiled.text),
            byte_count=len(context_bytes),
            context_sha256=hashlib.sha256(context_bytes).hexdigest(),
            sent_to_model=False,
        )
        return ContextForTurnResult(context=compiled.text, receipt=receipt)

    @staticmethod
    def _validate(
        request: ContextForTurnRequest,
    ) -> tuple[str, str, tuple[str, ...], int, int]:
        if not isinstance(request, ContextForTurnRequest):
            raise MemoryContextRequestError("ContextForTurnRequest is required")
        if not isinstance(request.query, str):
            raise MemoryContextRequestError("turn query must be text")
        query = request.query.strip()
        if not query or query != request.query:
            raise MemoryContextRequestError(
                "turn query must be canonical non-empty text"
            )
        if len(query) > MAX_TURN_QUERY_CHARS:
            raise MemoryContextRequestError(
                f"turn query exceeds {MAX_TURN_QUERY_CHARS} characters"
            )

        if not isinstance(request.target, str) or request.target not in {"local", "cloud"}:
            raise MemoryContextRequestError("turn target must be local or cloud")

        if not isinstance(request.subjects, tuple):
            raise MemoryContextRequestError("turn subjects must be a tuple")
        if len(request.subjects) > MAX_TURN_SUBJECTS:
            raise MemoryContextRequestError(
                f"turn subject filter exceeds {MAX_TURN_SUBJECTS} values"
            )
        subjects: list[str] = []
        seen: set[str] = set()
        for subject in request.subjects:
            if not isinstance(subject, str):
                raise MemoryContextRequestError("turn subject must be text")
            cleaned = subject.strip()
            if not cleaned or cleaned != subject or len(cleaned) > 200:
                raise MemoryContextRequestError(
                    "turn subject must be canonical bounded text"
                )
            if cleaned in seen:
                raise MemoryContextRequestError("turn subjects must be unique")
            seen.add(cleaned)
            subjects.append(cleaned)

        max_results = MemoryContextForTurnService._bounded_int(
            "max_results", request.max_results, minimum=1, maximum=MAX_TURN_RESULTS
        )
        max_context_chars = MemoryContextForTurnService._bounded_int(
            "max_context_chars",
            request.max_context_chars,
            minimum=1,
            maximum=MAX_TURN_CONTEXT_CHARS,
        )
        return query, request.target, tuple(subjects), max_results, max_context_chars

    @staticmethod
    def _bounded_int(name: str, value: Any, *, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise MemoryContextRequestError(f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise MemoryContextRequestError(
                f"{name} must be between {minimum} and {maximum}"
            )
        return value
