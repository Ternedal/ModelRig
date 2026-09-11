from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

from ..memory.consolidation import (
    MAX_CONSOLIDATION_EXISTING,
    ConsolidationAction,
    ConsolidationPlan,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from ..memory.extraction import (
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    MemoryCandidate,
)
from .memory import MemoryRecord, MemoryStore
from .memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from .memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter


class MemoryConsolidationApplyError(RuntimeError):
    """A W02 persistence handoff could not be applied without weakening authority."""


@dataclass(frozen=True)
class PersistenceDecision:
    outcome: str
    candidate: MemoryCandidate
    existing_id: str | None
    expected_updated_at: float | None
    reason: str

    @property
    def mutates(self) -> bool:
        return self.outcome == "create"


@dataclass(frozen=True)
class PersistencePlan:
    decisions: tuple[PersistenceDecision, ...]

    @property
    def mutation_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.mutates)

    @property
    def requires_review(self) -> bool:
        return any(decision.outcome == "review" for decision in self.decisions)


@dataclass(frozen=True)
class AppliedPersistence:
    outcome: str
    memory_id: str | None
    existing_id: str | None
    expected_updated_at: float | None
    reason: str


def plan_legacy_consolidation(
    store: MemoryStore,
    candidates: Iterable[MemoryCandidate],
) -> tuple[ConsolidationPlan, PersistencePlan]:
    existing = store.list(
        lifecycle_status="active",
        include_expired=False,
        include_secret=False,
        limit=MAX_CONSOLIDATION_EXISTING + 1,
    )
    neutral = MemoryConsolidator().plan(candidates, existing)
    return neutral, prepare_legacy_persistence(store, neutral)


def plan_protected_consolidation(
    reader: ProtectedMemoryReader,
    candidates: Iterable[MemoryCandidate],
) -> tuple[ConsolidationPlan, PersistencePlan]:
    existing = reader.list(
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
        lifecycle_status="active",
        include_expired=False,
        include_secret=False,
        limit=MAX_CONSOLIDATION_EXISTING + 1,
    )
    neutral = MemoryConsolidator().plan(candidates, existing)
    return neutral, prepare_protected_persistence(reader, neutral)


def prepare_legacy_persistence(
    store: MemoryStore,
    plan: ConsolidationPlan,
) -> PersistencePlan:
    actions = _actions(plan)
    conflicts = _structured_conflict_slots(actions)
    return PersistencePlan(
        tuple(
            _prepare_action(
                action,
                lambda candidate: _legacy_slot(store, candidate),
                force_review=_candidate_slot(action.candidate) in conflicts,
            )
            for action in actions
        )
    )


def prepare_protected_persistence(
    reader: ProtectedMemoryReader,
    plan: ConsolidationPlan,
) -> PersistencePlan:
    actions = _actions(plan)
    conflicts = _structured_conflict_slots(actions)
    return PersistencePlan(
        tuple(
            _prepare_action(
                action,
                lambda candidate: _protected_slot(reader, candidate),
                force_review=_candidate_slot(action.candidate) in conflicts,
            )
            for action in actions
        )
    )


def apply_legacy_persistence(
    store: MemoryStore,
    decision: PersistenceDecision,
) -> AppliedPersistence:
    _validate_persistence_decision(decision)
    if decision.outcome in {"review", "skip"}:
        return _applied(decision, memory_id=None)
    if decision.outcome == "reuse":
        current = _revalidate_reuse(_legacy_slot(store, decision.candidate), decision)
        return _applied(decision, memory_id=current.id)
    if decision.outcome == "create":
        _revalidate_create(_legacy_slot(store, decision.candidate), decision)
        try:
            created = store.create(**decision.candidate.store_fields())
        except Exception as exc:
            raise MemoryConsolidationApplyError("legacy W02 create failed closed") from exc
        return _applied(decision, memory_id=created.id)
    raise MemoryConsolidationApplyError("unknown persistence outcome")


def apply_protected_persistence(
    reader: ProtectedMemoryReader,
    writer: ProtectedMemoryWriter,
    decision: PersistenceDecision,
) -> AppliedPersistence:
    _validate_persistence_decision(decision)
    if decision.outcome in {"review", "skip"}:
        return _applied(decision, memory_id=None)
    if decision.outcome == "reuse":
        current = _revalidate_reuse(_protected_slot(reader, decision.candidate), decision)
        return _applied(decision, memory_id=current.id)
    if decision.outcome == "create":
        _revalidate_create(_protected_slot(reader, decision.candidate), decision)
        try:
            created = writer.create(
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                **decision.candidate.store_fields(),
            )
        except Exception as exc:
            raise MemoryConsolidationApplyError("protected W02 create failed closed") from exc
        return _applied(decision, memory_id=created.id)
    raise MemoryConsolidationApplyError("unknown persistence outcome")


def _actions(plan: ConsolidationPlan) -> tuple[ConsolidationAction, ...]:
    if not isinstance(plan, ConsolidationPlan):
        raise MemoryConsolidationApplyError("ConsolidationPlan is required")
    if plan.receipt.sent_to_store is not False:
        raise MemoryConsolidationApplyError("neutral plan must remain pre-store")
    return plan.actions


def _structured_conflict_slots(
    actions: tuple[ConsolidationAction, ...],
) -> set[tuple[str, str]]:
    """Find non-verbatim same-slot batch disagreements before any store write.

    W02-A plans against one immutable snapshot, so two different pending
    structured candidates can each independently look creatable. W02-B must not
    let apply order choose a winner. Exact duplicate candidates collapse to one
    representation, while distinct hardened confirmed verbatim statements remain
    independent append-only notes by design.
    """
    grouped: dict[tuple[str, str], set[MemoryCandidate]] = {}
    for action in actions:
        if not isinstance(action, ConsolidationAction):
            raise MemoryConsolidationApplyError("ConsolidationAction is required")
        candidate = action.candidate
        _revalidate_candidate(candidate)
        if _is_confirmed_verbatim(candidate):
            continue
        grouped.setdefault(_candidate_slot(candidate), set()).add(candidate)
    return {slot for slot, candidates in grouped.items() if len(candidates) > 1}


def _candidate_slot(candidate: MemoryCandidate) -> tuple[str, str]:
    return (candidate.subject.casefold(), candidate.predicate.casefold())


def _prepare_action(
    action: ConsolidationAction,
    read_slot,
    *,
    force_review: bool = False,
) -> PersistenceDecision:
    if not isinstance(action, ConsolidationAction):
        raise MemoryConsolidationApplyError("ConsolidationAction is required")
    _revalidate_candidate(action.candidate)

    # A neutral skip has no persistence authority and needs no durable-state read.
    # This matters most for secret candidates: skipping them must not trigger an
    # unnecessary LOCAL_MANAGEMENT read/decryption pass.
    if action.decision == "skip":
        return PersistenceDecision("skip", action.candidate, None, None, action.reason)

    if force_review:
        return PersistenceDecision(
            "review",
            action.candidate,
            None,
            None,
            "conflicting_structured_batch",
        )

    rows = read_slot(action.candidate)

    if action.decision == "supersede":
        current = _row_by_id(rows, action.existing_id)
        return PersistenceDecision(
            "review",
            action.candidate,
            current.id,
            current.updated_at,
            "explicit_local_correction_required",
        )

    if action.decision == "dedupe":
        current = _row_by_id(rows, action.existing_id)
        _validate_exact_reuse(current, action.candidate)
        return PersistenceDecision(
            "reuse",
            action.candidate,
            current.id,
            current.updated_at,
            action.reason,
        )

    if action.decision != "create":
        raise MemoryConsolidationApplyError("unknown neutral consolidation decision")

    candidate = action.candidate
    exact = [row for row in rows if row.value == candidate.value]
    if exact:
        if len(exact) != 1:
            return PersistenceDecision(
                "review",
                candidate,
                None,
                None,
                "ambiguous_exact_durable_state",
            )
        current = exact[0]
        try:
            _validate_exact_reuse(current, candidate)
        except MemoryConsolidationApplyError:
            return PersistenceDecision(
                "review",
                candidate,
                current.id,
                current.updated_at,
                "exact_value_requires_review",
            )
        return PersistenceDecision(
            "reuse",
            candidate,
            current.id,
            current.updated_at,
            "concurrent_exact_value",
        )

    if _is_confirmed_verbatim(candidate):
        return PersistenceDecision(
            "create",
            candidate,
            None,
            None,
            "distinct_verbatim_statement",
        )

    confirmed = [row for row in rows if row.review_status == "confirmed"]
    if confirmed:
        if len(confirmed) == 1:
            current = confirmed[0]
            return PersistenceDecision(
                "review",
                candidate,
                current.id,
                current.updated_at,
                "contradicts_reviewed_fact",
            )
        return PersistenceDecision(
            "review",
            candidate,
            None,
            None,
            "ambiguous_reviewed_state",
        )
    if rows:
        return PersistenceDecision(
            "review",
            candidate,
            None,
            None,
            "pending_slot_conflict",
        )
    return PersistenceDecision("create", candidate, None, None, action.reason)


def _legacy_slot(store: MemoryStore, candidate: MemoryCandidate) -> list[MemoryRecord]:
    rows = store.list(
        subject=candidate.subject,
        predicate=candidate.predicate,
        lifecycle_status="active",
        include_expired=True,
        include_secret=True,
        limit=MAX_CONSOLIDATION_EXISTING + 1,
    )
    return _bounded_slot(rows)


def _protected_slot(
    reader: ProtectedMemoryReader,
    candidate: MemoryCandidate,
) -> list[MemoryRecord]:
    rows = reader.list(
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
        subject=candidate.subject,
        predicate=candidate.predicate,
        lifecycle_status="active",
        include_expired=True,
        include_secret=True,
        limit=MAX_CONSOLIDATION_EXISTING + 1,
    )
    return _bounded_slot(rows)


def _bounded_slot(rows: list[MemoryRecord]) -> list[MemoryRecord]:
    if len(rows) > MAX_CONSOLIDATION_EXISTING:
        raise MemoryConsolidationApplyError("persistence slot exceeds W02 hard bound")
    return rows


def _row_by_id(rows: list[MemoryRecord], memory_id: str | None) -> MemoryRecord:
    if not memory_id:
        raise MemoryConsolidationApplyError("existing memory id is required")
    matches = [row for row in rows if row.id == memory_id]
    if len(matches) != 1:
        raise MemoryConsolidationApplyError("existing memory target is no longer unique")
    return matches[0]


def _validate_exact_reuse(current: MemoryRecord, candidate: MemoryCandidate) -> None:
    if current.lifecycle_status != "active" or current.value != candidate.value:
        raise MemoryConsolidationApplyError("durable exact value changed")
    if current.expires_at is not None and current.expires_at <= time.time():
        raise MemoryConsolidationApplyError("durable exact value is expired")
    if current.kind != candidate.kind:
        raise MemoryConsolidationApplyError("durable kind differs from candidate")
    if _sensitivity_rank(current.sensitivity) < _sensitivity_rank(candidate.sensitivity):
        raise MemoryConsolidationApplyError("durable sensitivity is less restrictive")
    if current.review_status not in {"pending", "confirmed"}:
        raise MemoryConsolidationApplyError("durable review state cannot be reused")
    if candidate.review_status == "confirmed" and current.review_status != "confirmed":
        raise MemoryConsolidationApplyError("pending durable row cannot satisfy confirmed authority")


def _revalidate_reuse(
    rows: list[MemoryRecord],
    decision: PersistenceDecision,
) -> MemoryRecord:
    current = _row_by_id(rows, decision.existing_id)
    if current.updated_at != decision.expected_updated_at:
        raise MemoryConsolidationApplyError("reuse plan is stale")
    _validate_exact_reuse(current, decision.candidate)
    return current


def _revalidate_create(rows: list[MemoryRecord], decision: PersistenceDecision) -> None:
    candidate = decision.candidate
    if _is_confirmed_verbatim(candidate):
        if any(row.value == candidate.value for row in rows):
            raise MemoryConsolidationApplyError(
                "verbatim create is stale because the exact statement now exists"
            )
        return
    if rows:
        raise MemoryConsolidationApplyError("structured create is stale")


def _validate_persistence_decision(decision: PersistenceDecision) -> None:
    if not isinstance(decision, PersistenceDecision):
        raise MemoryConsolidationApplyError("PersistenceDecision is required")
    if decision.outcome not in {"create", "reuse", "review", "skip"}:
        raise MemoryConsolidationApplyError("invalid persistence outcome")
    _revalidate_candidate(decision.candidate)
    if (
        decision.candidate.sensitivity == "secret"
        and decision.outcome in {"create", "reuse"}
    ):
        raise MemoryConsolidationApplyError(
            "secret candidates cannot gain automatic persistence authority"
        )
    if decision.outcome == "reuse":
        if not decision.existing_id or decision.expected_updated_at is None:
            raise MemoryConsolidationApplyError("reuse requires optimistic durable state")
    if decision.outcome == "create" and decision.existing_id is not None:
        raise MemoryConsolidationApplyError("create cannot carry a mutation target")


def _revalidate_candidate(candidate: MemoryCandidate) -> None:
    try:
        MemoryConsolidator().plan([candidate], [])
    except MemoryConsolidationError as exc:
        raise MemoryConsolidationApplyError("candidate violates W02 authority") from exc


def _is_confirmed_verbatim(candidate: MemoryCandidate) -> bool:
    return (
        candidate.review_status == "confirmed"
        and candidate.source_type == "user_explicit"
        and candidate.subject == VERBATIM_USER_SUBJECT
        and candidate.predicate == VERBATIM_USER_PREDICATE
        and candidate.kind == "note"
        and candidate.sensitivity == "private"
        and candidate.confidence == 1.0
        and bool(candidate.value)
        and candidate.value == candidate.evidence
    )


def _sensitivity_rank(value: str) -> int:
    ranks = {"public": 0, "operational": 1, "private": 2, "secret": 3}
    try:
        return ranks[value]
    except KeyError as exc:
        raise MemoryConsolidationApplyError("unknown sensitivity") from exc


def _applied(
    decision: PersistenceDecision,
    *,
    memory_id: str | None,
) -> AppliedPersistence:
    return AppliedPersistence(
        outcome=decision.outcome,
        memory_id=memory_id,
        existing_id=decision.existing_id,
        expected_updated_at=decision.expected_updated_at,
        reason=decision.reason,
    )
