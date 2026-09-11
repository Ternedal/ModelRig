from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..memory.consolidation import (
    ACTION_CREATE,
    ACTION_REUSE,
    ACTION_REVIEW,
    ConsolidationDecision,
    ConsolidationPlan,
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
    """A W02 persistence decision could not be applied without weakening authority."""


@dataclass(frozen=True)
class AppliedConsolidation:
    action: str
    memory_id: str | None
    reason: str


def plan_legacy_consolidation(
    store: MemoryStore,
    candidates: Iterable[MemoryCandidate],
    *,
    clock=None,
) -> ConsolidationPlan:
    existing = store.list(
        lifecycle_status="active",
        include_expired=True,
        include_secret=True,
        limit=201,
    )
    planner = MemoryConsolidator() if clock is None else MemoryConsolidator(clock=clock)
    return planner.plan(candidates, existing)


def plan_protected_consolidation(
    reader: ProtectedMemoryReader,
    candidates: Iterable[MemoryCandidate],
    *,
    clock=None,
) -> ConsolidationPlan:
    existing = reader.list(
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
        lifecycle_status="active",
        include_expired=True,
        include_secret=True,
        limit=201,
    )
    planner = MemoryConsolidator() if clock is None else MemoryConsolidator(clock=clock)
    return planner.plan(candidates, existing)


def apply_legacy_consolidation_decision(
    store: MemoryStore,
    decision: ConsolidationDecision,
) -> AppliedConsolidation:
    """Apply one non-destructive W02 decision to the legacy store.

    Review decisions never mutate. Reuse is revalidated against the exact row and
    optimistic token. Create is revalidated against the candidate's actual W02
    identity: exact statement identity for confirmed verbatim notes, or semantic
    subject/predicate identity for pending structured candidates.
    """
    _validate_decision(decision)
    if decision.action == ACTION_REVIEW:
        return AppliedConsolidation(ACTION_REVIEW, None, decision.reason)
    if decision.action == ACTION_REUSE:
        current = _legacy_reuse_target(store, decision)
        return AppliedConsolidation(ACTION_REUSE, current.id, decision.reason)
    if decision.action == ACTION_CREATE:
        _validate_legacy_create(store, decision.candidate)
        try:
            created = store.create(**decision.candidate.store_fields())
        except Exception as exc:
            raise MemoryConsolidationApplyError("legacy create failed closed") from exc
        return AppliedConsolidation(ACTION_CREATE, created.id, decision.reason)
    raise MemoryConsolidationApplyError("unknown consolidation action")


def apply_protected_consolidation_decision(
    reader: ProtectedMemoryReader,
    writer: ProtectedMemoryWriter,
    decision: ConsolidationDecision,
) -> AppliedConsolidation:
    """Apply one W02 create/reuse through existing protected local-management APIs."""
    _validate_decision(decision)
    if decision.action == ACTION_REVIEW:
        return AppliedConsolidation(ACTION_REVIEW, None, decision.reason)
    if decision.action == ACTION_REUSE:
        current = _protected_reuse_target(reader, decision)
        return AppliedConsolidation(ACTION_REUSE, current.id, decision.reason)
    if decision.action == ACTION_CREATE:
        _validate_protected_create(reader, decision.candidate)
        try:
            created = writer.create(
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                **decision.candidate.store_fields(),
            )
        except Exception as exc:
            raise MemoryConsolidationApplyError("protected create failed closed") from exc
        return AppliedConsolidation(ACTION_CREATE, created.id, decision.reason)
    raise MemoryConsolidationApplyError("unknown consolidation action")


def _validate_decision(decision: ConsolidationDecision) -> None:
    if not isinstance(decision, ConsolidationDecision):
        raise MemoryConsolidationApplyError("ConsolidationDecision is required")
    if decision.action not in {ACTION_CREATE, ACTION_REUSE, ACTION_REVIEW}:
        raise MemoryConsolidationApplyError("invalid consolidation action")
    if decision.action == ACTION_REUSE:
        if not decision.existing_id or decision.expected_updated_at is None:
            raise MemoryConsolidationApplyError(
                "reuse decision is missing optimistic state"
            )
    if decision.action == ACTION_CREATE and decision.existing_id is not None:
        raise MemoryConsolidationApplyError(
            "create decision must not carry mutation authority over an existing row"
        )


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


def _legacy_slot(store: MemoryStore, candidate: MemoryCandidate) -> list[MemoryRecord]:
    rows = store.list(
        subject=candidate.subject,
        predicate=candidate.predicate,
        lifecycle_status="active",
        include_expired=True,
        include_secret=True,
        limit=201,
    )
    if _is_confirmed_verbatim(candidate):
        rows = [row for row in rows if row.value == candidate.value]
    return rows


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
        limit=201,
    )
    if _is_confirmed_verbatim(candidate):
        rows = [row for row in rows if row.value == candidate.value]
    return rows


def _verify_reuse_target(
    rows: list[MemoryRecord],
    decision: ConsolidationDecision,
) -> MemoryRecord:
    if len(rows) != 1:
        raise MemoryConsolidationApplyError(
            "consolidation reuse state is no longer unambiguous"
        )
    current = rows[0]
    if current.id != decision.existing_id:
        raise MemoryConsolidationApplyError("consolidation target id changed")
    if current.updated_at != decision.expected_updated_at:
        raise MemoryConsolidationApplyError("consolidation plan is stale")
    if current.lifecycle_status != "active":
        raise MemoryConsolidationApplyError("consolidation target is not active")
    if current.value != decision.candidate.value:
        raise MemoryConsolidationApplyError("consolidation target value changed")
    if current.kind != decision.candidate.kind:
        raise MemoryConsolidationApplyError("consolidation target kind changed")
    return current


def _legacy_reuse_target(
    store: MemoryStore,
    decision: ConsolidationDecision,
) -> MemoryRecord:
    return _verify_reuse_target(_legacy_slot(store, decision.candidate), decision)


def _protected_reuse_target(
    reader: ProtectedMemoryReader,
    decision: ConsolidationDecision,
) -> MemoryRecord:
    return _verify_reuse_target(_protected_slot(reader, decision.candidate), decision)


def _validate_legacy_create(store: MemoryStore, candidate: MemoryCandidate) -> None:
    if _legacy_slot(store, candidate):
        raise MemoryConsolidationApplyError("create plan is stale")


def _validate_protected_create(
    reader: ProtectedMemoryReader,
    candidate: MemoryCandidate,
) -> None:
    if _protected_slot(reader, candidate):
        raise MemoryConsolidationApplyError("create plan is stale")
