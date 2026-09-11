from __future__ import annotations

import inspect
import math
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from itertools import islice
from typing import Generic, TypeVar

from .retrieval import (
    MemoryRecordLike,
    MemoryRetrievalQuery,
    MemoryRetriever,
    RankedMemory,
    _PROVENANCE_WEIGHT,
    _bounded_int,
    _clamp01,
    _finite_number,
    _normalize,
    _normalize_target,
    _tokens,
)


MAX_SEMANTIC_INPUT_RECORDS = 200
MAX_SEMANTIC_CANDIDATES = 32
MAX_SEMANTIC_TEXT_CHARS = 4_096
MAX_SEMANTIC_VECTOR_DIMS = 8_192
DEFAULT_MIN_SEMANTIC_SCORE = 0.55


class SemanticMemoryError(RuntimeError):
    """Semantic memory retrieval could not complete with trustworthy evidence."""


@dataclass(frozen=True)
class SemanticMemoryConfig:
    """Explicit, default-off policy for local semantic augmentation."""

    enabled: bool = False
    max_candidates: int = MAX_SEMANTIC_CANDIDATES
    max_text_chars: int = MAX_SEMANTIC_TEXT_CHARS
    min_semantic_score: float = DEFAULT_MIN_SEMANTIC_SCORE


TMemory = TypeVar("TMemory", bound=MemoryRecordLike)
Embedder = Callable[[str], Awaitable[list[float]]]


@dataclass(frozen=True)
class SemanticRankedMemory(Generic[TMemory]):
    record: TMemory
    score: float
    lexical_score: float
    semantic_score: float
    subject_score: float
    recency_score: float
    confidence_score: float
    provenance_score: float


@dataclass(frozen=True)
class _PreparedQuery:
    text: str
    tokens: frozenset[str]
    subjects: frozenset[str]
    target: str
    allow_private_cloud: bool
    max_results: int
    min_score: float
    half_life_days: float
    now: float


class HybridMemoryRetriever(Generic[TMemory]):
    """Optional local semantic augmentation over the deterministic R01 ranker.

    Disabled mode needs no embedder and delegates directly to ``MemoryRetriever``
    before adding a zero ``semantic_score`` field. That keeps ids, ordering,
    scores and all R01 component scores unchanged when the feature is off.

    When enabled, lifecycle/review/expiry/privacy/subject eligibility runs before
    any embedding call. Only already-eligible rows may be embedded. At most
    ``max_candidates`` rows are embedded, each semantic input is bounded, and
    the product adapter is deliberately local Ollama only.

    Semantic mode is strict rather than RAG-tolerant: malformed, non-finite,
    zero-length/zero-norm or dimension-changing vectors abort the semantic pass.
    Explicitly enabled semantic retrieval never silently downgrades to lexical.
    """

    def __init__(
        self,
        *,
        embed: Embedder | None = None,
        config: SemanticMemoryConfig | None = None,
    ) -> None:
        self._config = config or SemanticMemoryConfig()
        self._validate_config(self._config)
        if embed is not None and not callable(embed):
            raise SemanticMemoryError("semantic embedder must be callable")
        if self._config.enabled and embed is None:
            raise SemanticMemoryError("enabled semantic retrieval requires an embedder")
        self._embed = embed
        self._baseline = MemoryRetriever()

    @property
    def config(self) -> SemanticMemoryConfig:
        return self._config

    async def rank(
        self,
        records: Iterable[TMemory],
        query: MemoryRetrievalQuery,
    ) -> list[SemanticRankedMemory[TMemory]]:
        if not self._config.enabled:
            baseline = self._baseline.rank(records, query)
            return [self._from_baseline(item) for item in baseline]

        prepared = self._prepare_query(query)
        if prepared is None:
            return []

        try:
            bounded = tuple(islice(iter(records), MAX_SEMANTIC_INPUT_RECORDS + 1))
        except Exception as exc:
            raise SemanticMemoryError("semantic memory input could not be read") from exc
        if len(bounded) > MAX_SEMANTIC_INPUT_RECORDS:
            raise SemanticMemoryError(
                f"semantic memory input exceeds {MAX_SEMANTIC_INPUT_RECORDS} records"
            )

        eligible: list[TMemory] = []
        seen: set[str] = set()
        for record in bounded:
            memory_id = record.id if isinstance(record.id, str) else ""
            if not memory_id.strip() or memory_id in seen:
                continue
            seen.add(memory_id)
            if not self._baseline._eligible(
                record,
                target=prepared.target,
                allow_private_cloud=prepared.allow_private_cloud,
                now=prepared.now,
            ):
                continue
            if prepared.subjects and _normalize(record.subject) not in prepared.subjects:
                continue
            eligible.append(record)

        semantic_candidates = eligible[: self._config.max_candidates]
        semantic_scores: dict[str, float] = {}
        if semantic_candidates:
            query_vector = await self._embed_checked(self._semantic_query_text(prepared.text))
            expected_dims = len(query_vector)
            for record in semantic_candidates:
                vector = await self._embed_checked(
                    self._semantic_text(record),
                    expected_dims=expected_dims,
                )
                semantic_scores[record.id] = self._cosine_checked(
                    query_vector,
                    vector,
                )

        ranked: list[SemanticRankedMemory[TMemory]] = []
        for record in eligible:
            lexical = self._baseline._lexical_score(
                record,
                prepared.text,
                prepared.tokens,
            )
            semantic = semantic_scores.get(record.id, 0.0)
            if lexical <= 0 and semantic < self._config.min_semantic_score:
                # Recency/confidence/provenance cannot manufacture relevance.
                # A lexical miss needs independently strong semantic evidence.
                continue

            subject_score = self._baseline._subject_score(
                record,
                prepared.text,
                prepared.tokens,
            )
            recency_score = self._baseline._recency_score(
                record,
                now=prepared.now,
                half_life_days=prepared.half_life_days,
            )
            confidence_score = _clamp01(record.confidence)
            provenance_score = _PROVENANCE_WEIGHT[str(record.source_type)]
            relevance = max(lexical, semantic)
            score = _clamp01(
                0.72 * relevance
                + 0.10 * subject_score
                + 0.08 * recency_score
                + 0.07 * confidence_score
                + 0.03 * provenance_score
            )
            if score < prepared.min_score:
                continue
            ranked.append(
                SemanticRankedMemory(
                    record=record,
                    score=score,
                    lexical_score=lexical,
                    semantic_score=semantic,
                    subject_score=subject_score,
                    recency_score=recency_score,
                    confidence_score=confidence_score,
                    provenance_score=provenance_score,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.score,
                -max(item.lexical_score, item.semantic_score),
                -item.semantic_score,
                -item.lexical_score,
                -self._safe_updated_at(item.record.updated_at),
                str(item.record.id),
            )
        )
        return ranked[: prepared.max_results]

    async def _embed_checked(
        self,
        text: str,
        *,
        expected_dims: int | None = None,
    ) -> list[float]:
        if self._embed is None:
            raise SemanticMemoryError("semantic embedder is not configured")
        try:
            result = self._embed(text)
            if not inspect.isawaitable(result):
                raise SemanticMemoryError("semantic embedder must be async")
            raw = await result
        except SemanticMemoryError:
            raise
        except Exception as exc:
            raise SemanticMemoryError("local semantic embedding failed") from exc

        if not isinstance(raw, (list, tuple)) or not raw:
            raise SemanticMemoryError("semantic embedding vector must be non-empty")
        if len(raw) > MAX_SEMANTIC_VECTOR_DIMS:
            raise SemanticMemoryError(
                f"semantic embedding exceeds {MAX_SEMANTIC_VECTOR_DIMS} dimensions"
            )
        if expected_dims is not None and len(raw) != expected_dims:
            raise SemanticMemoryError(
                "semantic embedding dimensions changed within one retrieval"
            )

        vector: list[float] = []
        norm_sq = 0.0
        for value in raw:
            if isinstance(value, bool):
                raise SemanticMemoryError("semantic embedding values must be numeric")
            try:
                parsed = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise SemanticMemoryError(
                    "semantic embedding values must be numeric"
                ) from exc
            if not math.isfinite(parsed):
                raise SemanticMemoryError("semantic embedding values must be finite")
            vector.append(parsed)
            norm_sq += parsed * parsed
        if norm_sq <= 0.0 or not math.isfinite(norm_sq):
            raise SemanticMemoryError("semantic embedding vector must have non-zero norm")
        return vector

    def _semantic_query_text(self, text: str) -> str:
        bounded = text[: self._config.max_text_chars]
        if not bounded:
            raise SemanticMemoryError("semantic query text must not be empty")
        return bounded

    def _semantic_text(self, record: TMemory) -> str:
        prefix = f"subject: {record.subject}\npredicate: {record.predicate}\nvalue: "
        budget = self._config.max_text_chars - len(prefix)
        if budget <= 0:
            raise SemanticMemoryError("semantic text budget is too small")
        return prefix + record.value[:budget]

    @staticmethod
    def _cosine_checked(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            raise SemanticMemoryError("semantic vectors are dimensionally invalid")
        dot = sum(left * right for left, right in zip(a, b))
        na = math.sqrt(sum(value * value for value in a))
        nb = math.sqrt(sum(value * value for value in b))
        if not all(math.isfinite(value) for value in (dot, na, nb)):
            raise SemanticMemoryError("semantic cosine is non-finite")
        if na <= 0.0 or nb <= 0.0:
            raise SemanticMemoryError("semantic cosine requires non-zero vectors")
        cosine = dot / (na * nb)
        if not math.isfinite(cosine):
            raise SemanticMemoryError("semantic cosine is non-finite")
        # Negative similarity is no relevance, not negative authority.
        return _clamp01(cosine)

    @staticmethod
    def _prepare_query(query: MemoryRetrievalQuery) -> _PreparedQuery | None:
        if not isinstance(query, MemoryRetrievalQuery):
            return None
        if not isinstance(query.text, str):
            return None
        if not isinstance(query.subjects, tuple):
            return None
        if not isinstance(query.allow_private_cloud, bool):
            return None

        target = _normalize_target(query.target)
        if target not in {"local", "cloud"}:
            return None
        text = _normalize(query.text)
        tokens = _tokens(text)
        if not tokens:
            return None

        subjects: set[str] = set()
        for subject in query.subjects:
            if not isinstance(subject, str) or not subject.strip():
                return None
            subjects.add(_normalize(subject))

        max_results = _bounded_int(query.max_results, lower=0, upper=100)
        min_score = _finite_number(query.min_score)
        half_life = _finite_number(query.recency_half_life_days)
        now = time.time() if query.now is None else _finite_number(query.now)
        if (
            max_results is None
            or max_results == 0
            or min_score is None
            or min_score < 0
            or min_score > 1
            or half_life is None
            or half_life <= 0
            or now is None
        ):
            return None
        return _PreparedQuery(
            text=text,
            tokens=tokens,
            subjects=frozenset(subjects),
            target=target,
            allow_private_cloud=query.allow_private_cloud,
            max_results=max_results,
            min_score=min_score,
            half_life_days=half_life,
            now=now,
        )

    @staticmethod
    def _validate_config(config: SemanticMemoryConfig) -> None:
        if not isinstance(config, SemanticMemoryConfig):
            raise SemanticMemoryError("SemanticMemoryConfig is required")
        if not isinstance(config.enabled, bool):
            raise SemanticMemoryError("semantic enabled flag must be boolean")
        if (
            isinstance(config.max_candidates, bool)
            or not isinstance(config.max_candidates, int)
            or config.max_candidates < 1
            or config.max_candidates > MAX_SEMANTIC_CANDIDATES
        ):
            raise SemanticMemoryError(
                f"semantic max_candidates must be between 1 and {MAX_SEMANTIC_CANDIDATES}"
            )
        if (
            isinstance(config.max_text_chars, bool)
            or not isinstance(config.max_text_chars, int)
            or config.max_text_chars < 128
            or config.max_text_chars > MAX_SEMANTIC_TEXT_CHARS
        ):
            raise SemanticMemoryError(
                f"semantic max_text_chars must be between 128 and {MAX_SEMANTIC_TEXT_CHARS}"
            )
        threshold = _finite_number(config.min_semantic_score)
        if threshold is None or threshold <= 0 or threshold > 1:
            raise SemanticMemoryError(
                "semantic min_semantic_score must be within (0, 1]"
            )

    @staticmethod
    def _safe_updated_at(value: object) -> float:
        parsed = _finite_number(value)
        return 0.0 if parsed is None else parsed

    @staticmethod
    def _from_baseline(
        item: RankedMemory[TMemory],
    ) -> SemanticRankedMemory[TMemory]:
        return SemanticRankedMemory(
            record=item.record,
            score=item.score,
            lexical_score=item.lexical_score,
            semantic_score=0.0,
            subject_score=item.subject_score,
            recency_score=item.recency_score,
            confidence_score=item.confidence_score,
            provenance_score=item.provenance_score,
        )
