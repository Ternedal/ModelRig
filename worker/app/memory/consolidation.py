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
    MemoryCandidate,
)


MAX_CONSOLIDATION_CANDIDATES = MAX_MEMORY_CANDIDATES
MAX_CONSOLIDATION_RECORDS = 200

ACTION_CREATE = "create"
ACTION_REUSE = "reuse"
ACTION_SUPERSEDE = "supersede"
ACTION_REVIEW = "review"
CONSOLIDATION_ACTIONS = {
    ACTION_CREATE,
    ACTION_REUSE,
    ACTION_SUPERSEDE,
    ACTION_REVIEW,
}

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
    """Storage-neutral active-row projection used by the W02 planner.

    The projection deliberately excludes source references, protection envelopes,
    database handles and mutation methods. `updated_at` is retained only as the
    optimistic concurrency token required by a later explicit writer action.
    """

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
        return self.action in {ACTION_CREATE, ACTION_SUPERSEDE}


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
    """Deterministic Memory 4.0 W02 duplicate/stale-fact planner.

    W02 performs no model call and owns no storage connection. It accepts the
    already-bounded W01 candidate contract plus a bounded local-management view
    of active durable memory and emits explicit create/reuse/supersede/review
    decisions. Only a confirmed private `user_explicit` candidate can produce a
    supersede decision; pending/model-derived candidates can never replace
    durable reviewed state.
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
        validated_candidates = tuple(
            self._candidate(candidate) for candidate in candidate_rows
        )
        snapshots = tuple(self._snapshot(record) for record in record_rows)
        now = self._now()

        slots: dict[tuple[str, str], list[MemoryCandidate]] = {}
        slot_order: list[tuple[str, str]] = []
        for candidate in validated_candidates:
            slot = self._slot(candidate.subject, candidate.predicate)
            if slot not in slots:
                slots[slot] = []
                slot_order.append(slot)
            slots[slot].append(candidate)

        existing_by_slot: dict[tuple[str, str], list[ExistingMemorySnapshot]] = {}
        for record in snapshots:
            slot = self._slot(record.subject, record.predicate)
            existing_by_slot.setdefault(slot, []).append(record)

        decisions: list[ConsolidationDecision] = []
        for slot in slot_order:
            cluster = slots[slot]
            unique = self._unique_candidates(cluster)
            values = {candidate.value for candidate in unique}
            if len(values) != 1:
                for candidate in unique:
                    decisions.append(
                        self._decision(
                            ACTION_REVIEW,
                            candidate,
                            reason="conflicting_candidate_values",
                        )
                    )
                continue
            if len(unique) != 1:
                # Same slot/value but conflicting provenance, sensitivity,
                # review state, evidence or confidence is not an exact duplicate.
                # Do not pick whichever representation happened to arrive last.
                for candidate in unique:
                    decisions.append(
                        self._decision(
                            ACTION_REVIEW,
                            candidate,
                            reason="conflicting_candidate_metadata",
                        )
                    )
                continue

            candidate = unique[0]
            existing = existing_by_slot.get(slot, [])
            decisions.append(self._for_slot(candidate, existing, now=now))

        return ConsolidationPlan(
            decisions=tuple(decisions),
            candidate_count=len(validated_candidates),
            record_count=len(snapshots),
        )

    def _for_slot(
        self,
        candidate: MemoryCandidate,
        existing: list[ExistingMemorySnapshot],
        *,
        now: float,
    ) -> ConsolidationDecision:
        if not existing:
            return self._decision(ACTION_CREATE, candidate, reason="new_memory_slot")

        # Multiple active rows for one subject/predicate mean durable state is
        # already ambiguous. W02 never guesses which row deserves supersession.
        if len(existing) != 1:
            return self._decision(
                ACTION_REVIEW,
                candidate,
                reason="ambiguous_existing_slot",
            )

        current = existing[0]
        candidate_rank = _SENSITIVITY_RANK[candidate.sensitivity]
        current_rank = _SENSITIVITY_RANK[current.sensitivity]
        current_expired = (
            current.expires_at is not None and current.expires_at <= now
        )

        if current.review_status == "rejected":
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="existing_memory_rejected",
            )

        # Reusing a less restrictive durable row would silently declassify the
        # W01 proposal. A stricter exact duplicate may be reused, but a stale
        # stricter value may not be replaced by a less restrictive candidate.
        if current_rank < candidate_rank:
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="sensitivity_declassification",
            )

        if current.value == candidate.value:
            if (
                not current_expired
                and current.review_status == "confirmed"
            ):
                return self._decision(
                    ACTION_REUSE,
                    candidate,
                    existing=current,
                    reason="existing_confirmed_duplicate",
                )
            if (
                not current_expired
                and current.review_status == "pending"
                and candidate.review_status == "pending"
            ):
                return self._decision(
                    ACTION_REUSE,
                    candidate,
                    existing=current,
                    reason="existing_pending_duplicate",
                )
            if self._may_supersede(candidate, current):
                return self._decision(
                    ACTION_SUPERSEDE,
                    candidate,
                    existing=current,
                    reason=(
                        "refresh_expired_duplicate"
                        if current_expired
                        else "upgrade_pending_duplicate"
                    ),
                )
            return self._decision(
                ACTION_REVIEW,
                candidate,
                existing=current,
                reason="duplicate_requires_review",
            )

        # A pending candidate may coexist with one different durable value for
        # later explicit review. It never supersedes the current row.
        if candidate.review_status == "pending":
            return self._decision(
                ACTION_CREATE,
                candidate,
                existing=current,
                reason="pending_alternative_value",
            )

        if self._may_supersede(candidate, current):
            return self._decision(
                ACTION_SUPERSEDE,
                candidate,
                existing=current,
                reason="confirmed_explicit_stale_fact",
            )

        return self._decision(
            ACTION_REVIEW,
            candidate,
            existing=current,
            reason="stale_fact_requires_review",
        )

    @staticmethod
    def _may_supersede(
        candidate: MemoryCandidate,
        current: ExistingMemorySnapshot,
    ) -> bool:
        return (
            candidate.review_status == "confirmed"
            and candidate.source_type == "user_explicit"
            and candidate.sensitivity == "private"
            and current.sensitivity == "private"
            and current.review_status in {"pending", "confirmed"}
        )

    @classmethod
    def _candidate(cls, value: Any) -> MemoryCandidate:
        if not isinstance(value, MemoryCandidate):
            raise MemoryConsolidationError("W02 requires MemoryCandidate inputs")
        cls._text("candidate subject", value.subject, MAX_CANDIDATE_SUBJECT_CHARS)
        cls._text(
            "candidate predicate",
            value.predicate,
            MAX_CANDIDATE_PREDICATE_CHARS,
        )
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
        if value.review_status == "confirmed":
            if value.source_type != "user_explicit":
                raise MemoryConsolidationError(
                    "only user_explicit candidates may be confirmed"
                )
            if value.sensitivity != "private":
                raise MemoryConsolidationError(
                    "confirmed W02 candidates must be private"
                )
            if not isinstance(value.evidence, str) or value.value not in value.evidence:
                raise MemoryConsolidationError(
                    "confirmed candidate lost its exact-evidence binding"
                )
        if value.sensitivity == "secret" and value.review_status != "pending":
            raise MemoryConsolidationError("secret candidate must remain pending")
        return value

    @classmethod
    def _snapshot(cls, raw: Any) -> ExistingMemorySnapshot:
        try:
            memory_id = cls._text("memory id", getattr(raw, "id"), 100)
            subject = cls._text(
                "memory subject",
                getattr(raw, "subject"),
                MAX_CANDIDATE_SUBJECT_CHARS,
            )
            predicate = cls._text(
                "memory predicate",
                getattr(raw, "predicate"),
                MAX_CANDIDATE_PREDICATE_CHARS,
            )
            value = cls._text(
                "memory value",
                getattr(raw, "value"),
                MAX_CANDIDATE_VALUE_CHARS,
            )
            kind = getattr(raw, "kind")
            sensitivity = getattr(raw, "sensitivity")
            source_type = getattr(raw, "source_type")
            confidence = cls._confidence(
                "memory confidence",
                getattr(raw, "confidence"),
            )
            review_status = getattr(raw, "review_status")
            lifecycle_status = getattr(raw, "lifecycle_status")
            updated_at = cls._timestamp(
                "memory updated_at",
                getattr(raw, "updated_at"),
            )
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
            raise MemoryConsolidationError(
                "W02 existing records must be active snapshots"
            )
        expires_at = (
            None
            if expires_raw is None
            else cls._timestamp("memory expires_at", expires_raw)
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
            expected_updated_at=(
                None if existing is None else existing.updated_at
            ),
            reason=reason,
        )

    @staticmethod
    def _unique_candidates(
        candidates: list[MemoryCandidate],
    ) -> list[MemoryCandidate]:
        result: list[MemoryCandidate] = []
        seen: set[MemoryCandidate] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            result.append(candidate)
        return result

    @staticmethod
    def _slot(subject: str, predicate: str) -> tuple[str, str]:
        return (subject.casefold(), predicate.casefold())

    @staticmethod
    def _bounded(source: Iterable[Any], maximum: int, label: str) -> tuple[Any, ...]:
        try:
            values = tuple(islice(iter(source), maximum + 1))
        except TypeError as exc:
            raise MemoryConsolidationError(f"{label} collection is invalid") from exc
        if len(values) > maximum:
            raise MemoryConsolidationError(
                f"{label} collection exceeds {maximum} records"
            )
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
            raise MemoryConsolidationError(
                f"{name} must be finite and non-negative"
            )
        return parsed
