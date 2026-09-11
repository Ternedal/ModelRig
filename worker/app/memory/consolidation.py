from __future__ import annotations

import math
import time
from dataclasses import dataclass
from itertools import islice
from typing import Any, Iterable

from .extraction import (
    MAX_CANDIDATE_PREDICATE_CHARS,
    MAX_CANDIDATE_SUBJECT_CHARS,
    MAX_CANDIDATE_VALUE_CHARS,
    MAX_MEMORY_CANDIDATES,
    MAX_SOURCE_REF_CHARS,
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    MemoryCandidate,
)


MAX_CONSOLIDATION_CANDIDATES = MAX_MEMORY_CANDIDATES
MAX_CONSOLIDATION_RECORDS = 200

ACTION_CREATE = "create"
ACTION_REUSE = "reuse"
ACTION_REVIEW = "review"
CONSOLIDATION_ACTIONS = {ACTION_CREATE, ACTION_REUSE, ACTION_REVIEW}

_ALLOWED_KINDS = {
    "fact",
    "preference",
    "project",
    "relationship",
    "routine",
    "constraint",
    "note",
}
_ALLOWED_SENSITIVITIES = {"public", "operational", "private", "secret"}
_ALLOWED_SOURCES = {"user_explicit", "tool_observation", "imported", "inferred"}
_ALLOWED_REVIEW = {"pending", "confirmed", "rejected"}
_SENSITIVITY_RANK = {
    "public": 0,
    "operational": 1,
    "private": 2,
    "secret": 3,
}


class MemoryConsolidationError(RuntimeError):
    """A candidate batch cannot be consolidated without broadening authority."""


@dataclass(frozen=True)
class ExistingMemorySnapshot:
    id: str
    subject: str
    predicate: str
    value: str
    kind: str
    sensitivity: str
    source_type: str
    confidence: float
    review_status: str
    lifecycle_status: str
    updated_at: float
    expires_at: float | None


@dataclass(frozen=True)
class ConsolidationDecision:
    action: str
    candidate: MemoryCandidate
    existing_id: str | None
    expected_updated_at: float | None
    reason: str

    @property
    def mutates(self) -> bool:
        return self.action == ACTION_CREATE


@dataclass(frozen=True)
class ConsolidationPlan:
    decisions: tuple[ConsolidationDecision, ...]
    candidate_count: int
    record_count: int

    @property
    def mutation_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.mutates)

    @property
    def requires_review(self) -> bool:
        return any(decision.action == ACTION_REVIEW for decision in self.decisions)


class MemoryConsolidator:
    """Deterministic W02 deduplication and stale-fact review boundary.

    W01 #1201/#1202 intentionally removed model-owned structured semantics from
    automatically confirmed candidates. W02 revalidates that contract instead of
    recreating authority from model text. Confirmed inputs are therefore only
    complete server-normalized verbatim-user notes. Structured interpretations
    remain pending and a conflicting durable fact becomes an explicit review
    handoff; W02 never calls a correction/supersede operation automatically.
    """

    def __init__(self, *, clock=time.time):
        if not callable(clock):
            raise MemoryConsolidationError("consolidation clock must be callable")
        self._clock = clock

    def plan(
        self,
        candidates: Iterable[MemoryCandidate],
        existing_records: Iterable[object],
    ) -> ConsolidationPlan:
        candidate_rows = self._bounded(
            candidates,
            MAX_CONSOLIDATION_CANDIDATES,
            "candidate",
        )
        record_rows = self._bounded(
            existing_records,
            MAX_CONSOLIDATION_RECORDS,
            "existing memory",
        )
        validated = tuple(self._candidate(item) for item in candidate_rows)
        existing = tuple(self._snapshot(item) for item in record_rows)
        now = self._now()

        groups: dict[tuple[str, ...], list[MemoryCandidate]] = {}
        order: list[tuple[str, ...]] = []
        for candidate in validated:
            slot = self._candidate_slot(candidate)
            if slot not in groups:
                groups[slot] = []
                order.append(slot)
            groups[slot].append(candidate)

        decisions: list[ConsolidationDecision] = []
        for slot in order:
            cluster = groups[slot]
            unique = self._unique_candidates(cluster)
            if len(unique) != 1:
                reason = self._cluster_conflict_reason(unique)
                decisions.extend(
                    self._decision(ACTION_REVIEW, item, reason=reason)
                    for item in unique
                )
                continue

            candidate = unique[0]
            matches = self._matching_existing(candidate, existing)
            decisions.append(self._for_candidate(candidate, matches, now=now))

        return ConsolidationPlan(
            decisions=tuple(decisions),
            candidate_count=len(validated),
            record_count=len(existing),
        )

    def _for_candidate(
        self,
        candidate: MemoryCandidate,
        existing: list[ExistingMemorySnapshot],
        *,
        now: float,
    ) -> ConsolidationDecision:
        if not existing:
            return self._decision(ACTION_CREATE, candidate, reason="new_memory")
        if len(existing) != 1:
            return self._decision(
                ACTION_REVIEW,
                candidate,
                reason="ambiguous_existing_state",
            )

        current = existing[0]
        if current.review_status == "rejected":
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="existing_memory_rejected",
            )
        if current.kind != candidate.kind:
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="kind_mismatch",
            )
        if _SENSITIVITY_RANK[current.sensitivity] < _SENSITIVITY_RANK[candidate.sensitivity]:
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="sensitivity_underclassified",
            )
        if current.expires_at is not None and current.expires_at <= now:
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="expired_existing_requires_review",
            )

        if current.value == candidate.value:
            if current.review_status == "confirmed":
                return self._decision(
                    ACTION_REUSE,
                    candidate,
                    existing=current,
                    reason="existing_confirmed_duplicate",
                )
            if current.review_status == "pending" and candidate.review_status == "pending":
                return self._decision(
                    ACTION_REUSE,
                    candidate,
                    existing=current,
                    reason="existing_pending_duplicate",
                )
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="duplicate_review_upgrade_required",
            )

        # Confirmed W01 values are complete verbatim statements. Two distinct
        # statements are independent notes, not stale semantic versions merely
        # because the server-owned subject/predicate is intentionally generic.
        if self._is_confirmed_verbatim(candidate):
            return self._decision(
                ACTION_CREATE,
                candidate,
                reason="distinct_verbatim_statement",
            )

        # Structured meaning is pending under hardened W01. A different value in
        # an existing semantic slot is useful evidence of a possible stale fact,
        # but not authority to mutate reviewed history. Bind the exact row/token
        # into a review handoff and leave correction to local management.
        return self._decision(
            ACTION_REVIEW,
            candidate,
            existing=current,
            reason="stale_fact_requires_review",
        )

    @classmethod
    def _candidate(cls, value: Any) -> MemoryCandidate:
        if not isinstance(value, MemoryCandidate):
            raise MemoryConsolidationError("W02 requires MemoryCandidate inputs")
        cls._text("candidate subject", value.subject, MAX_CANDIDATE_SUBJECT_CHARS)
        cls._text("candidate predicate", value.predicate, MAX_CANDIDATE_PREDICATE_CHARS)
        cls._text("candidate value", value.value, MAX_CANDIDATE_VALUE_CHARS)
        cls._text("candidate source_ref", value.source_ref, MAX_SOURCE_REF_CHARS)
        if value.kind not in _ALLOWED_KINDS:
            raise MemoryConsolidationError("candidate kind is invalid")
        if value.sensitivity not in {"private", "secret"}:
            raise MemoryConsolidationError(
                "W02 candidates must preserve the W01 private/secret clamp"
            )
        if value.source_type not in _ALLOWED_SOURCES:
            raise MemoryConsolidationError("candidate source_type is invalid")
        if value.review_status not in {"pending", "confirmed"}:
            raise MemoryConsolidationError("candidate review_status is invalid")
        cls._confidence("candidate confidence", value.confidence)
        if not isinstance(value.evidence, str):
            raise MemoryConsolidationError("candidate evidence must be text")

        if value.review_status == "confirmed" and not cls._is_confirmed_verbatim(value):
            raise MemoryConsolidationError(
                "confirmed W02 candidate violates hardened W01 verbatim authority"
            )
        if value.sensitivity == "secret" and value.review_status != "pending":
            raise MemoryConsolidationError("secret candidate must remain pending")
        return value

    @staticmethod
    def _is_confirmed_verbatim(candidate: MemoryCandidate) -> bool:
        return (
            candidate.review_status == "confirmed"
            and candidate.source_type == "user_explicit"
            and candidate.subject == VERBATIM_USER_SUBJECT
            and candidate.predicate == VERBATIM_USER_PREDICATE
            and candidate.kind == "note"
            and candidate.sensitivity == "private"
            and candidate.confidence == 1.0
            and candidate.evidence == candidate.value
        )

    @classmethod
    def _snapshot(cls, raw: Any) -> ExistingMemorySnapshot:
        try:
            memory_id = cls._text("memory id", getattr(raw, "id"), 100)
            subject = cls._text("memory subject", getattr(raw, "subject"), 200)
            predicate = cls._text("memory predicate", getattr(raw, "predicate"), 200)
            value = cls._text("memory value", getattr(raw, "value"), MAX_CANDIDATE_VALUE_CHARS)
            kind = getattr(raw, "kind")
            sensitivity = getattr(raw, "sensitivity")
            source_type = getattr(raw, "source_type")
            confidence = cls._confidence("memory confidence", getattr(raw, "confidence"))
            review_status = getattr(raw, "review_status")
            lifecycle_status = getattr(raw, "lifecycle_status")
            updated_at = cls._timestamp("memory updated_at", getattr(raw, "updated_at"))
            expires_raw = getattr(raw, "expires_at")
        except AttributeError as exc:
            raise MemoryConsolidationError(
                "existing memory record is missing required fields"
            ) from exc

        if kind not in _ALLOWED_KINDS:
            raise MemoryConsolidationError("existing memory kind is invalid")
        if sensitivity not in _ALLOWED_SENSITIVITIES:
            raise MemoryConsolidationError("existing memory sensitivity is invalid")
        if source_type not in _ALLOWED_SOURCES:
            raise MemoryConsolidationError("existing memory source_type is invalid")
        if review_status not in _ALLOWED_REVIEW:
            raise MemoryConsolidationError("existing memory review_status is invalid")
        if lifecycle_status != "active":
            raise MemoryConsolidationError("W02 existing records must be active snapshots")
        expires_at = None if expires_raw is None else cls._timestamp(
            "memory expires_at", expires_raw
        )
        return ExistingMemorySnapshot(
            id=memory_id,
            subject=subject,
            predicate=predicate,
            value=value,
            kind=kind,
            sensitivity=sensitivity,
            source_type=source_type,
            confidence=confidence,
            review_status=review_status,
            lifecycle_status=lifecycle_status,
            updated_at=updated_at,
            expires_at=expires_at,
        )

    @classmethod
    def _matching_existing(
        cls,
        candidate: MemoryCandidate,
        existing: tuple[ExistingMemorySnapshot, ...],
    ) -> list[ExistingMemorySnapshot]:
        if cls._is_confirmed_verbatim(candidate):
            return [
                record
                for record in existing
                if record.subject == VERBATIM_USER_SUBJECT
                and record.predicate == VERBATIM_USER_PREDICATE
                and record.value == candidate.value
            ]
        subject = candidate.subject.casefold()
        predicate = candidate.predicate.casefold()
        return [
            record
            for record in existing
            if record.subject.casefold() == subject
            and record.predicate.casefold() == predicate
        ]

    @classmethod
    def _candidate_slot(cls, candidate: MemoryCandidate) -> tuple[str, ...]:
        if cls._is_confirmed_verbatim(candidate):
            return ("verbatim", candidate.value)
        return ("semantic", candidate.subject.casefold(), candidate.predicate.casefold())

    @staticmethod
    def _cluster_conflict_reason(candidates: list[MemoryCandidate]) -> str:
        values = {candidate.value for candidate in candidates}
        if len(values) > 1:
            return "conflicting_candidate_values"
        return "conflicting_candidate_metadata"

    @staticmethod
    def _decision(
        action: str,
        candidate: MemoryCandidate,
        *,
        existing: ExistingMemorySnapshot | None = None,
        reason: str,
    ) -> ConsolidationDecision:
        if action not in CONSOLIDATION_ACTIONS:
            raise MemoryConsolidationError("invalid consolidation action")
        return ConsolidationDecision(
            action=action,
            candidate=candidate,
            existing_id=None if existing is None else existing.id,
            expected_updated_at=None if existing is None else existing.updated_at,
            reason=reason,
        )

    @staticmethod
    def _unique_candidates(candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        result: list[MemoryCandidate] = []
        seen: set[MemoryCandidate] = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
        return result

    @staticmethod
    def _bounded(source: Iterable[Any], maximum: int, label: str) -> tuple[Any, ...]:
        try:
            values = tuple(islice(iter(source), maximum + 1))
        except TypeError as exc:
            raise MemoryConsolidationError(f"{label} collection is invalid") from exc
        if len(values) > maximum:
            raise MemoryConsolidationError(f"{label} collection exceeds {maximum} records")
        return values

    def _now(self) -> float:
        try:
            value = float(self._clock())
        except (TypeError, ValueError) as exc:
            raise MemoryConsolidationError("consolidation clock is invalid") from exc
        if not math.isfinite(value) or value < 0:
            raise MemoryConsolidationError("consolidation clock is invalid")
        return value

    @staticmethod
    def _text(name: str, value: Any, maximum: int) -> str:
        if not isinstance(value, str):
            raise MemoryConsolidationError(f"{name} must be text")
        cleaned = value.strip()
        if not cleaned:
            raise MemoryConsolidationError(f"{name} must not be empty")
        if len(cleaned) > maximum:
            raise MemoryConsolidationError(f"{name} exceeds {maximum} characters")
        return cleaned

    @staticmethod
    def _confidence(name: str, value: Any) -> float:
        if isinstance(value, bool):
            raise MemoryConsolidationError(f"{name} must be numeric")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise MemoryConsolidationError(f"{name} must be numeric") from exc
        if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
            raise MemoryConsolidationError(
                f"{name} must be finite and between 0 and 1"
            )
        return parsed

    @staticmethod
    def _timestamp(name: str, value: Any) -> float:
        if isinstance(value, bool):
            raise MemoryConsolidationError(f"{name} must be numeric")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise MemoryConsolidationError(f"{name} must be numeric") from exc
        if not math.isfinite(parsed) or parsed < 0:
            raise MemoryConsolidationError(f"{name} must be finite and non-negative")
        return parsed
