from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..memory.consolidation import (
    ACTION_CREATE,
    ACTION_REUSE,
    ACTION_REVIEW,
    ACTION_SUPERSEDE,
    ConsolidationDecision,
    ConsolidationPlan,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from ..memory.extraction import MemoryCandidate
from .memory import MemoryConflict, MemoryRecord, MemoryStore
from .memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from .memory_protected_writer import (
    MemoryWriteAccess,
    ProtectedMemoryWriter,
)


class MemoryConsolidationApplyError(RuntimeError):
    """A W02 persistence decision could not be applied without weakening authority."""


@dataclass(frozen=True)
class AppliedConsolidation:
    action: str
    memory_id: str | None
    superseded_id: str | None
    reason: str


def plan_legacy_consolidation(
    store: MemoryStore,
    candidates: Iterable[MemoryCandidate],
    *,
    clock=None,
) -> ConsolidationPlan:
    """Plan W02 against a bounded local-management view of the legacy store."""
    existing = store.list(
        lifecycle_status="active",
        include_expired=True,
        include_secret=True,
        limit=201,
    )
    consolidator = MemoryConsolidator() if clock is None else MemoryConsolidator(clock=clock)
    return consolidator.plan(candidates, existing)


def plan_protected_consolidation(
    reader: ProtectedMemoryReader,
    candidates: Iterable[MemoryCandidate],
    *,
    clock=None,
) -> ConsolidationPlan:
    """Plan W02 against decrypted values available only at local-management authority."""
    existing = reader.list(
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
        lifecycle_status="active",
        include_expired=True,
        include_secret=True,
        limit=201,
    )
    consolidator = MemoryConsolidator() if clock is None else MemoryConsolidator(clock=clock)
    return consolidator.plan(candidates, existing)


def apply_legacy_consolidation_decision(
    store: MemoryStore,
    decision: ConsolidationDecision,
) -> AppliedConsolidation:
    """Apply exactly one previously planned legacy decision.

    W02 intentionally does not pretend a multi-decision batch is atomic. Each
    mutation is one existing MemoryStore transaction. Reuse/review never mutate.
    Supersede revalidates the exact id/update token immediately before invoking
    the existing versioning correction path, so a stale plan fails closed.
    """
    _validate_decision(decision)
    if decision.action == ACTION_REVIEW:
        return AppliedConsolidation(ACTION_REVIEW, None, None, decision.reason)
    if decision.action == ACTION_REUSE:
        current = _legacy_current(store, decision)
        return AppliedConsolidation(
            ACTION_REUSE,
            current.id,
            None,
            decision.reason,
        )
    if decision.action == ACTION_CREATE:
        _validate_create_precondition_legacy(store, decision)
        created = store.create(**decision.candidate.store_fields())
        return AppliedConsolidation(
            ACTION_CREATE,
            created.id,
            None,
            decision.reason,
        )
    if decision.action == ACTION_SUPERSEDE:
        current = _legacy_current(store, decision)
        candidate = decision.candidate
        try:
            replacement = store.correct(
                current.id,
                value=candidate.value,
                source_ref=candidate.source_ref,
                sensitivity=candidate.sensitivity,
                confidence=candidate.confidence,
            )
        except Exception as exc:
            raise MemoryConsolidationApplyError(
                "legacy supersede failed closed"
            ) from exc
        return AppliedConsolidation(
            ACTION_SUPERSEDE,
            replacement.id,
            current.id,
            decision.reason,
        )
    raise MemoryConsolidationApplyError("unknown consolidation action")


def apply_protected_consolidation_decision(
    reader: ProtectedMemoryReader,
    writer: ProtectedMemoryWriter,
    decision: ConsolidationDecision,
) -> AppliedConsolidation:
    """Apply one W02 decision through the existing protected reader/writer pair."""
    _validate_decision(decision)
    if decision.action == ACTION_REVIEW:
        return AppliedConsolidation(ACTION_REVIEW, None, None, decision.reason)
    if decision.action == ACTION_REUSE:
        current = _protected_current(reader, decision)
        return AppliedConsolidation(
            ACTION_REUSE,
            current.id,
            None,
            decision.reason,
        )
    if decision.action == ACTION_CREATE:
        _validate_create_precondition_protected(reader, decision)
        candidate = decision.candidate
        try:
            created = writer.create(
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                **candidate.store_fields(),
            )
        except Exception as exc:
            raise MemoryConsolidationApplyError(
                "protected create failed closed"
            ) from exc
        return AppliedConsolidation(
            ACTION_CREATE,
            created.id,
            None,
            decision.reason,
        )
    if decision.action == ACTION_SUPERSEDE:
        current = _protected_current(reader, decision)
        candidate = decision.candidate
        try:
            replacement = writer.correct(
                current.id,
                access=MemoryWriteAccess.LOCAL_MANAGEMENT,
                expected_updated_at=current.updated_at,
                value=candidate.value,
                source_ref=candidate.source_ref,
                sensitivity=candidate.sensitivity,
                confidence=candidate.confidence,
            )
        except Exception as exc:
            raise MemoryConsolidationApplyError(
                "protected supersede failed closed"
            ) from exc
        return AppliedConsolidation(
            ACTION_SUPERSEDE,
            replacement.id,
            current.id,
            decision.reason,
        )
    raise MemoryConsolidationApplyError("unknown consolidation action")


def _validate_decision(decision: ConsolidationDecision) -> None:
    if not isinstance(decision, ConsolidationDecision):
        raise MemoryConsolidationApplyError("ConsolidationDecision is required")
    if decision.action not in {
        ACTION_CREATE,
        ACTION_REUSE,
        ACTION_REVIEW,
        ACTION_SUPERSEDE,
    }:
        raise MemoryConsolidationApplyError("invalid consolidation action")
    if decision.action in {ACTION_REUSE, ACTION_SUPERSEDE}:
        if not decision.existing_id or decision.expected_updated_at is None:
            raise MemoryConsolidationApplyError(
                "existing decision is missing optimistic state"
            )
    if decision.action == ACTION_SUPERSEDE:
        candidate = decision.candidate
        if not (
            candidate.review_status == "confirmed"
            and candidate.source_type == "user_explicit"
            and candidate.sensitivity == "private"
        ):
            raise MemoryConsolidationApplyError(
                "supersede requires confirmed private user-explicit authority"
            )


def _legacy_current(
    store: MemoryStore,
    decision: ConsolidationDecision,
) -> MemoryRecord:
    try:
        current = store.get(decision.existing_id or "")
    except Exception as exc:
        raise MemoryConsolidationApplyError(
            "legacy consolidation target is no longer active"
        ) from exc
    _verify_current(current, decision)
    return current


def _protected_current(
    reader: ProtectedMemoryReader,
    decision: ConsolidationDecision,
) -> MemoryRecord:
    try:
        current = reader.get(
            decision.existing_id or "",
            access=MemoryReadAccess.LOCAL_MANAGEMENT,
        )
    except Exception as exc:
        raise MemoryConsolidationApplyError(
            "protected consolidation target is no longer active"
        ) from exc
    _verify_current(current, decision)
    return current


def _verify_current(current: MemoryRecord, decision: ConsolidationDecision) -> None:
    if current.lifecycle_status != "active":
        raise MemoryConsolidationApplyError("consolidation target is not active")
    if current.id != decision.existing_id:
        raise MemoryConsolidationApplyError("consolidation target id changed")
    if current.updated_at != decision.expected_updated_at:
        raise MemoryConsolidationApplyError("consolidation plan is stale")
    if (
        current.subject.casefold() != decision.candidate.subject.casefold()
        or current.predicate.casefold() != decision.candidate.predicate.casefold()
    ):
        raise MemoryConsolidationApplyError("consolidation target slot changed")


def _validate_create_precondition_legacy(
    store: MemoryStore,
    decision: ConsolidationDecision,
) -> None:
    if decision.existing_id is None:
        current = store.list(
            subject=decision.candidate.subject,
            predicate=decision.candidate.predicate,
            lifecycle_status="active",
            include_expired=True,
            include_secret=True,
            limit=2,
        )
        if current:
            raise MemoryConsolidationApplyError(
                "new-slot create plan is stale"
            )
        return
    _legacy_current(store, decision)


def _validate_create_precondition_protected(
    reader: ProtectedMemoryReader,
    decision: ConsolidationDecision,
) -> None:
    if decision.existing_id is None:
        current = reader.list(
            access=MemoryReadAccess.LOCAL_MANAGEMENT,
            subject=decision.candidate.subject,
            predicate=decision.candidate.predicate,
            lifecycle_status="active",
            include_expired=True,
            include_secret=True,
            limit=2,
        )
        if current:
            raise MemoryConsolidationApplyError(
                "new-slot create plan is stale"
            )
        return
    _protected_current(reader, decision)
