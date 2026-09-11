from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..memory.consolidation import (
    MAX_CONSOLIDATION_CANDIDATES,
    MAX_CONSOLIDATION_EXISTING,
    ConsolidationPlan,
    ExistingMemory,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from ..memory.extraction import MemoryCandidate
from .memory import MemoryStore
from .memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter
from .memory_protection import MemoryProtectionError, MemoryProtectionScope


class MemoryConsolidationApplyError(RuntimeError):
    """A W02-B plan could not be applied without broadening authority."""


@dataclass(frozen=True)
class DurableConsolidationReceipt:
    considered_count: int
    created_count: int
    reused_count: int
    review_count: int
    skipped_count: int
    created_ids: tuple[str, ...]
    reused_ids: tuple[str, ...]
    review_existing_ids: tuple[str, ...]
    committed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "kaliv-memory-consolidation-write-receipt/v1",
            "considered_count": self.considered_count,
            "created_count": self.created_count,
            "reused_count": self.reused_count,
            "review_count": self.review_count,
            "skipped_count": self.skipped_count,
            "created_ids": list(self.created_ids),
            "reused_ids": list(self.reused_ids),
            "review_existing_ids": list(self.review_existing_ids),
            "committed": self.committed,
        }


def apply_legacy_consolidation_plan(
    store: MemoryStore,
    plan: ConsolidationPlan,
) -> DurableConsolidationReceipt:
    """Atomically apply the create/dedupe subset of one W02-A plan.

    The plan is never treated as write authority by itself. Candidate contracts
    are revalidated first, then the entire plan is recomputed against the current
    relevant durable state *inside* the same SQLite IMMEDIATE transaction. Any
    state drift, forged decision, insert failure or unsupported supersede leaves
    no partial batch behind.
    """

    candidates = _plan_candidates(plan)
    try:
        with store._transaction():
            existing = _legacy_snapshot_locked(store, candidates)
            current = _revalidate_plan(plan, candidates, existing)
            return _apply_legacy_locked(store, current)
    except MemoryConsolidationApplyError:
        raise
    except Exception as exc:
        raise MemoryConsolidationApplyError(
            "legacy W02-B consolidation failed closed"
        ) from exc


def apply_protected_consolidation_plan(
    writer: ProtectedMemoryWriter,
    plan: ConsolidationPlan,
    *,
    access: MemoryWriteAccess,
) -> DurableConsolidationReceipt:
    """Atomically apply W02-B through the existing protected writer boundary."""

    candidates = _plan_candidates(plan)
    try:
        writer._access(access)
        with writer._transaction():
            writer._validate_migration()
            existing = _protected_snapshot_locked(writer, candidates)
            current = _revalidate_plan(plan, candidates, existing)
            return _apply_protected_locked(writer, current)
    except MemoryConsolidationApplyError:
        raise
    except Exception as exc:
        raise MemoryConsolidationApplyError(
            "protected W02-B consolidation failed closed"
        ) from exc


def _plan_candidates(plan: ConsolidationPlan) -> tuple[MemoryCandidate, ...]:
    if not isinstance(plan, ConsolidationPlan):
        raise MemoryConsolidationApplyError("W02-B requires a ConsolidationPlan")
    if len(plan.actions) > MAX_CONSOLIDATION_CANDIDATES:
        raise MemoryConsolidationApplyError("W02-B plan exceeds the action bound")
    if plan.receipt.considered_count != len(plan.actions):
        raise MemoryConsolidationApplyError("W02-B plan receipt/action count mismatch")
    if plan.receipt.sent_to_store:
        raise MemoryConsolidationApplyError(
            "W02-B accepts pre-store plans only"
        )

    candidates = tuple(action.candidate for action in plan.actions)
    try:
        # Candidate-only planning re-runs the W01/W02 field, evidence, privacy,
        # confidence and batch-bound validators before any transaction starts.
        MemoryConsolidator().plan(candidates, [])
    except MemoryConsolidationError as exc:
        raise MemoryConsolidationApplyError(
            "W02-B candidate contract validation failed"
        ) from exc
    return candidates


def _revalidate_plan(
    expected: ConsolidationPlan,
    candidates: tuple[MemoryCandidate, ...],
    existing: tuple[ExistingMemory, ...],
) -> ConsolidationPlan:
    try:
        current = MemoryConsolidator().plan(candidates, existing)
    except MemoryConsolidationError as exc:
        raise MemoryConsolidationApplyError(
            "current durable state is not consolidation-safe"
        ) from exc
    if current != expected:
        raise MemoryConsolidationApplyError(
            "W02-B plan is stale or does not match current durable state"
        )
    return current


def _relevant_keys(
    candidates: tuple[MemoryCandidate, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted({(candidate.subject, candidate.predicate) for candidate in candidates})
    )


def _where_for_keys(
    candidates: tuple[MemoryCandidate, ...],
) -> tuple[str, tuple[Any, ...]]:
    keys = _relevant_keys(candidates)
    if not keys:
        return "0", ()
    clauses = ["(subject=? AND predicate=?)" for _ in keys]
    parameters: list[Any] = []
    for subject, predicate in keys:
        parameters.extend((subject, predicate))
    return "(" + " OR ".join(clauses) + ")", tuple(parameters)


def _legacy_snapshot_locked(
    store: MemoryStore,
    candidates: tuple[MemoryCandidate, ...],
) -> tuple[ExistingMemory, ...]:
    where, parameters = _where_for_keys(candidates)
    rows = store._conn.execute(
        "SELECT * FROM agent_memories WHERE lifecycle_status='active' "
        "AND sensitivity!='secret' AND "
        + where
        + " ORDER BY id LIMIT ?",
        parameters + (MAX_CONSOLIDATION_EXISTING + 1,),
    ).fetchall()
    if len(rows) > MAX_CONSOLIDATION_EXISTING:
        raise MemoryConsolidationApplyError(
            "relevant legacy snapshot exceeds the W02 hard bound"
        )
    return tuple(
        ExistingMemory(
            id=str(row["id"]),
            subject=str(row["subject"]),
            predicate=str(row["predicate"]),
            value=str(row["value"]),
            kind=str(row["kind"]),
            sensitivity=str(row["sensitivity"]),
            source_type=str(row["source_type"]),
            review_status=str(row["review_status"]),
            lifecycle_status=str(row["lifecycle_status"]),
        )
        for row in rows
    )


def _protected_snapshot_locked(
    writer: ProtectedMemoryWriter,
    candidates: tuple[MemoryCandidate, ...],
) -> tuple[ExistingMemory, ...]:
    where, parameters = _where_for_keys(candidates)
    rows = writer._execute(
        "SELECT * FROM agent_memories WHERE lifecycle_status='active' "
        "AND sensitivity!='secret' AND "
        + where
        + " ORDER BY id LIMIT ?",
        parameters + (MAX_CONSOLIDATION_EXISTING + 1,),
    ).fetchall()
    if len(rows) > MAX_CONSOLIDATION_EXISTING:
        raise MemoryConsolidationApplyError(
            "relevant protected snapshot exceeds the W02 hard bound"
        )
    return tuple(_protected_existing(writer, row) for row in rows)


def _protected_existing(
    writer: ProtectedMemoryWriter,
    row: Any,
) -> ExistingMemory:
    sensitivity = str(row["sensitivity"])
    if sensitivity == "private":
        writer._validate_protected_row(row)
        if str(row["protection_state"]) != "protected":
            raise MemoryConsolidationApplyError(
                "active private W02 memory must retain a protected payload"
            )
        envelope = row["value_protected"]
        if not isinstance(envelope, str) or not envelope:
            raise MemoryConsolidationApplyError(
                "protected W02 memory value envelope is missing"
            )
        try:
            value = writer.codec.unprotect_text(
                envelope,
                scope=MemoryProtectionScope(
                    memory_id=str(row["id"]),
                    subject=str(row["subject"]),
                    predicate=str(row["predicate"]),
                    sensitivity=sensitivity,
                    field="value",
                    row_schema_version=int(row["schema_version"]),
                ),
            )
        except MemoryProtectionError as exc:
            raise MemoryConsolidationApplyError(
                "protected W02 memory value could not be opened"
            ) from exc
    else:
        if (
            row["protection_state"] != "plaintext"
            or row["value_protected"] is not None
            or row["source_ref_protected"] is not None
        ):
            raise MemoryConsolidationApplyError(
                "non-private W02 memory has unexpected protection metadata"
            )
        value = str(row["value"])

    return ExistingMemory(
        id=str(row["id"]),
        subject=str(row["subject"]),
        predicate=str(row["predicate"]),
        value=value,
        kind=str(row["kind"]),
        sensitivity=sensitivity,
        source_type=str(row["source_type"]),
        review_status=str(row["review_status"]),
        lifecycle_status=str(row["lifecycle_status"]),
    )


def _apply_legacy_locked(
    store: MemoryStore,
    plan: ConsolidationPlan,
) -> DurableConsolidationReceipt:
    created: list[str] = []
    reused: list[str] = []
    review: list[str] = []
    skipped = 0

    for action in plan.actions:
        if action.candidate.sensitivity == "secret":
            if action.decision != "skip":
                raise MemoryConsolidationApplyError(
                    "secret W01 candidate reached a W02-B write decision"
                )
            skipped += 1
            continue

        if action.decision == "create":
            fields = action.candidate.store_fields()
            record = store._insert_locked(**fields, expires_at=None)
            created.append(record.id)
        elif action.decision == "dedupe":
            if action.existing_id is None:
                raise MemoryConsolidationApplyError(
                    "dedupe decision lost its durable id"
                )
            reused.append(action.existing_id)
        elif action.decision == "supersede":
            # W02-B deliberately does not inherit correction/supersede authority
            # from a model-derived candidate. It is a local-management review
            # handoff only; no durable row is changed here.
            if action.existing_id is None:
                raise MemoryConsolidationApplyError(
                    "supersede review handoff lost its durable id"
                )
            review.append(action.existing_id)
        elif action.decision == "skip":
            skipped += 1
        else:
            raise MemoryConsolidationApplyError(
                "unknown W02-B consolidation decision"
            )

    return _receipt(plan, created, reused, review, skipped)


def _apply_protected_locked(
    writer: ProtectedMemoryWriter,
    plan: ConsolidationPlan,
) -> DurableConsolidationReceipt:
    created: list[str] = []
    reused: list[str] = []
    review: list[str] = []
    skipped = 0

    for action in plan.actions:
        candidate = action.candidate
        if candidate.sensitivity == "secret":
            if action.decision != "skip":
                raise MemoryConsolidationApplyError(
                    "secret W01 candidate reached a protected W02-B write decision"
                )
            skipped += 1
            continue

        if action.decision == "create":
            created.append(_protected_create_locked(writer, candidate))
        elif action.decision == "dedupe":
            if action.existing_id is None:
                raise MemoryConsolidationApplyError(
                    "dedupe decision lost its protected durable id"
                )
            reused.append(action.existing_id)
        elif action.decision == "supersede":
            if action.existing_id is None:
                raise MemoryConsolidationApplyError(
                    "supersede review handoff lost its protected durable id"
                )
            review.append(action.existing_id)
        elif action.decision == "skip":
            skipped += 1
        else:
            raise MemoryConsolidationApplyError(
                "unknown protected W02-B consolidation decision"
            )

    return _receipt(plan, created, reused, review, skipped)


def _protected_create_locked(
    writer: ProtectedMemoryWriter,
    candidate: MemoryCandidate,
) -> str:
    fields = writer._validate_fields(
        **candidate.store_fields(),
        expires_at=None,
    )
    memory_id = writer._new_id()
    now = writer.clock()
    value_envelope, source_envelope, protected_fields = writer._protect_fields(
        memory_id=memory_id,
        subject=fields["subject"],
        predicate=fields["predicate"],
        sensitivity=fields["sensitivity"],
        value=fields["value"],
        source_ref=fields["source_ref"],
        schema_version=1,
    )
    writer._insert_locked(
        memory_id=memory_id,
        fields=fields,
        value_envelope=value_envelope,
        source_envelope=source_envelope,
        protected_fields=protected_fields,
        now=now,
        supersedes_id=None,
    )
    return memory_id


def _receipt(
    plan: ConsolidationPlan,
    created: list[str],
    reused: list[str],
    review: list[str],
    skipped: int,
) -> DurableConsolidationReceipt:
    return DurableConsolidationReceipt(
        considered_count=len(plan.actions),
        created_count=len(created),
        reused_count=len(reused),
        review_count=len(review),
        skipped_count=skipped,
        created_ids=tuple(created),
        reused_ids=tuple(reused),
        review_existing_ids=tuple(review),
        committed=True,
    )
