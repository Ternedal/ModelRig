from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Generic, Iterable, Protocol, TypeVar


_ALLOWED_SENSITIVITIES = {"public", "operational", "private"}
_PROVENANCE_WEIGHT = {
    "user_explicit": 1.0,
    "tool_observation": 0.8,
    "imported": 0.65,
    "inferred": 0.5,
}


class MemoryRecordLike(Protocol):
    id: str
    subject: str
    predicate: str
    value: str
    sensitivity: str
    source_type: str
    confidence: float
    review_status: str
    lifecycle_status: str
    updated_at: float
    expires_at: float | None


TMemory = TypeVar("TMemory", bound=MemoryRecordLike)


@dataclass(frozen=True)
class MemoryRetrievalQuery:
    text: str
    subjects: tuple[str, ...] = ()
    target: str = "local"
    allow_private_cloud: bool = False
    max_results: int = 12
    min_score: float = 0.10
    recency_half_life_days: float = 45.0
    now: float | None = None


@dataclass(frozen=True)
class RankedMemory(Generic[TMemory]):
    record: TMemory
    score: float
    lexical_score: float
    subject_score: float
    recency_score: float
    confidence_score: float
    provenance_score: float


class MemoryRetriever:
    """Deterministic, model-independent first-stage memory retrieval.

    This module deliberately does not call an embedding model or an LLM. It
    selects only already-reviewed memory candidates and leaves final prompt
    compilation/escaping to the existing memory context compiler.

    Authority rules are fail-closed:
    - only active + confirmed + unexpired records are selectable;
    - secret records are never selectable;
    - private cloud records require explicit caller consent;
    - unknown targets/sensitivity/provenance values are rejected;
    - malformed query/record authority fields return no authority;
    - relevance can rank data, but can never elevate an ineligible record.
    """

    def rank(
        self,
        records: Iterable[TMemory],
        query: MemoryRetrievalQuery,
    ) -> list[RankedMemory[TMemory]]:
        if not isinstance(query.text, str):
            return []
        if not isinstance(query.subjects, tuple):
            return []
        if not isinstance(query.allow_private_cloud, bool):
            return []

        target = _normalize_target(query.target)
        if target not in {"local", "cloud"}:
            return []

        query_text = _normalize(query.text)
        query_tokens = _tokens(query_text)
        if not query_tokens:
            return []

        subject_filter: set[str] = set()
        for item in query.subjects:
            if not isinstance(item, str) or not item.strip():
                return []
            subject_filter.add(_normalize(item))

        max_results = _bounded_int(query.max_results, lower=0, upper=100)
        if max_results is None or max_results == 0:
            return []

        min_score_raw = _finite_number(query.min_score)
        half_life = _finite_number(query.recency_half_life_days)
        now = time.time() if query.now is None else _finite_number(query.now)
        if (
            min_score_raw is None
            or min_score_raw < 0
            or min_score_raw > 1
            or half_life is None
            or half_life <= 0
            or now is None
        ):
            return []
        min_score = min_score_raw

        ranked: list[RankedMemory[TMemory]] = []
        seen: set[str] = set()
        for record in records:
            memory_id = record.id if isinstance(record.id, str) else ""
            if not memory_id.strip() or memory_id in seen:
                continue
            seen.add(memory_id)

            if not self._eligible(
                record,
                target=target,
                allow_private_cloud=query.allow_private_cloud,
                now=now,
            ):
                continue

            normalized_subject = _normalize(record.subject)
            if subject_filter and normalized_subject not in subject_filter:
                continue

            lexical = self._lexical_score(record, query_text, query_tokens)
            if lexical <= 0:
                # Recency/confidence may rank relevant records, but they must
                # never make unrelated memories appear relevant by themselves.
                continue

            subject_score = self._subject_score(record, query_text, query_tokens)
            recency_score = self._recency_score(record, now=now, half_life_days=half_life)
            confidence_score = _clamp01(record.confidence)
            provenance_score = _PROVENANCE_WEIGHT[str(record.source_type)]

            score = (
                0.72 * lexical
                + 0.10 * subject_score
                + 0.08 * recency_score
                + 0.07 * confidence_score
                + 0.03 * provenance_score
            )
            score = _clamp01(score)
            if score < min_score:
                continue

            ranked.append(
                RankedMemory(
                    record=record,
                    score=score,
                    lexical_score=lexical,
                    subject_score=subject_score,
                    recency_score=recency_score,
                    confidence_score=confidence_score,
                    provenance_score=provenance_score,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.score,
                -item.lexical_score,
                -_safe_number(item.record.updated_at),
                str(item.record.id),
            )
        )
        return ranked[:max_results]

    @staticmethod
    def _eligible(
        record: MemoryRecordLike,
        *,
        target: str,
        allow_private_cloud: bool,
        now: float,
    ) -> bool:
        for value in (record.id, record.subject, record.predicate, record.value):
            if not isinstance(value, str) or not value.strip():
                return False
        if str(record.lifecycle_status) != "active" or str(record.review_status) != "confirmed":
            return False

        sensitivity = str(record.sensitivity)
        if sensitivity not in _ALLOWED_SENSITIVITIES:
            return False
        if target == "cloud" and sensitivity == "private" and not allow_private_cloud:
            return False

        source_type = str(record.source_type)
        if source_type not in _PROVENANCE_WEIGHT:
            return False

        confidence = _finite_number(record.confidence)
        if confidence is None or confidence < 0 or confidence > 1:
            return False

        expires_at = record.expires_at
        if expires_at is not None:
            expiry = _finite_number(expires_at)
            if expiry is None or expiry <= now:
                return False
        return True

    @staticmethod
    def _lexical_score(
        record: MemoryRecordLike,
        query_text: str,
        query_tokens: frozenset[str],
    ) -> float:
        subject_text = _normalize(record.subject)
        predicate_text = _normalize(record.predicate)
        value_text = _normalize(record.value)

        subject_tokens = _tokens(subject_text)
        predicate_tokens = _tokens(predicate_text)
        value_tokens = _tokens(value_text)
        combined = subject_tokens | predicate_tokens | value_tokens

        subject_overlap = _coverage(query_tokens, subject_tokens)
        predicate_overlap = _coverage(query_tokens, predicate_tokens)
        value_overlap = _coverage(query_tokens, value_tokens)
        combined_overlap = _coverage(query_tokens, combined)

        score = max(
            subject_overlap,
            0.95 * predicate_overlap,
            0.80 * value_overlap,
            0.85 * combined_overlap,
        )
        if query_text and query_text in subject_text:
            score = max(score, 1.0)
        if query_text and query_text in predicate_text:
            score = max(score, 0.98)
        if query_text and query_text in value_text:
            score = max(score, 0.92)
        return _clamp01(score)

    @staticmethod
    def _subject_score(
        record: MemoryRecordLike,
        query_text: str,
        query_tokens: frozenset[str],
    ) -> float:
        subject = _normalize(record.subject)
        if query_text == subject:
            return 1.0
        return _coverage(query_tokens, _tokens(subject))

    @staticmethod
    def _recency_score(
        record: MemoryRecordLike,
        *,
        now: float,
        half_life_days: float,
    ) -> float:
        updated = _finite_number(record.updated_at)
        if updated is None or updated <= 0:
            return 0.0
        age_days = max(0.0, now - updated) / 86_400.0
        return _clamp01(0.5 ** (age_days / half_life_days))


def _normalize_target(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return _normalize(enum_value)


def _normalize(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value)).casefold().strip()


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def _coverage(query_tokens: frozenset[str], field_tokens: frozenset[str]) -> float:
    if not query_tokens or not field_tokens:
        return 0.0
    return len(query_tokens & field_tokens) / len(query_tokens)


def _bounded_int(value: object, *, lower: int, upper: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number < lower:
        return lower
    if number > upper:
        return upper
    return number


def _clamp01(value: object) -> float:
    number = _safe_number(value)
    return max(0.0, min(number, 1.0))


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _safe_number(value: object) -> float:
    number = _finite_number(value)
    return 0.0 if number is None else number
