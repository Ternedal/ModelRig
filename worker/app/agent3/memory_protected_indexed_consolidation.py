from __future__ import annotations

from ..memory.consolidation import MAX_CONSOLIDATION_EXISTING, ConsolidationPlan
from ..memory.extraction import (
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    MemoryCandidate,
)
from .memory import MemoryRecord
from .memory_consolidation_writer import (
    ConsolidationWriteReceipt,
    MemoryConsolidationWriteError,
    _apply_protected_fresh_locked,
    _protected_replay_receipt_locked,
    _replan,
    _snapshot_query,
    _validate_plan,
)
from .memory_protected_exact_lookup import (
    MAX_EXACT_LOOKUP_MATCHES,
    ProtectedMemoryExactLookupError,
    protected_exact_lookup_ids,
    remove_protected_exact_lookup_row,
    sync_protected_exact_lookup_row,
)
from .memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from .memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter


def apply_indexed_protected_consolidation_plan(
    writer: ProtectedMemoryWriter,
    plan: ConsolidationPlan,
    *,
    access: MemoryWriteAccess,
) -> ConsolidationWriteReceipt:
    """Apply W02-B using the optional keyed exact-match sidecar when installed.

    The sidecar only narrows the candidate set for canonical verbatim values. Every
    selected durable row is still decrypted and the ordinary W02-A planner is
    rerun while the protected writer's BEGIN IMMEDIATE transaction is held. A
    digest match therefore never becomes fact/review/supersede authority.

    When the sidecar has never been installed this function preserves W02-B's
    existing bounded exact-key scan and fail-closed >128 behavior. If sidecar
    metadata exists but is stale/incomplete, the write fails closed before any
    memory mutation.
    """
    writer._access(access)
    candidates = _validate_plan(plan)
    with writer._transaction():
        writer._validate_migration()
        try:
            with ProtectedMemoryReader(
                writer.path,
                writer.codec,
                busy_timeout_ms=writer.busy_timeout_ms,
            ) as reader:
                snapshot = _indexed_snapshot_locked(reader, candidates, plan)
                fresh = _replan(candidates, snapshot)
                if fresh != plan:
                    replay = _protected_replay_receipt_locked(reader, plan, fresh)
                    if replay is not None:
                        return replay
                    raise MemoryConsolidationWriteError(
                        "protected indexed consolidation plan is stale or was not "
                        "produced by W02-A"
                    )
        except ProtectedMemoryExactLookupError as exc:
            raise MemoryConsolidationWriteError(
                "protected exact-match sidecar cannot prove a complete lookup"
            ) from exc

        receipt = _apply_protected_fresh_locked(
            writer,
            fresh,
            {record.id: record for record in snapshot},
        )
        try:
            _sync_sidecar_locked(writer, fresh, receipt)
        except ProtectedMemoryExactLookupError as exc:
            raise MemoryConsolidationWriteError(
                "protected exact-match sidecar could not commit atomically"
            ) from exc
        return receipt


def _indexed_snapshot_locked(
    reader: ProtectedMemoryReader,
    candidates: tuple[MemoryCandidate, ...],
    plan: ConsolidationPlan,
) -> list[MemoryRecord]:
    canonical = tuple(candidate for candidate in candidates if _is_verbatim(candidate))
    if not canonical:
        return _bounded_snapshot_query(reader, candidates, plan, lookup_ids=())

    matched_ids: set[str] = set()
    for value in sorted({candidate.value for candidate in canonical}):
        ids = protected_exact_lookup_ids(
            reader._execute,
            reader.codec,
            value=value,
            limit=MAX_EXACT_LOOKUP_MATCHES,
        )
        if ids is None:
            # Optional sidecar has never been installed. Preserve the landed W02-B
            # behavior rather than silently changing storage semantics.
            return _bounded_snapshot_query(reader, candidates, plan, lookup_ids=())
        matched_ids.update(ids)
        if len(matched_ids) > MAX_CONSOLIDATION_EXISTING:
            raise MemoryConsolidationWriteError(
                "protected exact lookup exceeds the W02-A existing-row bound"
            )

    structured = tuple(candidate for candidate in candidates if not _is_verbatim(candidate))
    return _bounded_snapshot_query(
        reader,
        structured,
        plan,
        lookup_ids=tuple(sorted(matched_ids)),
    )


def _bounded_snapshot_query(
    reader: ProtectedMemoryReader,
    candidates: tuple[MemoryCandidate, ...],
    plan: ConsolidationPlan,
    *,
    lookup_ids: tuple[str, ...],
) -> list[MemoryRecord]:
    selectors, params = _snapshot_query(
        candidates,
        plan,
        filter_verbatim_value=False,
    )
    selector_parts: list[str] = []
    all_params: list[object] = []
    if selectors is not None:
        selector_parts.append(f"({selectors})")
        all_params.extend(params)
    if lookup_ids:
        selector_parts.append("id IN (" + ",".join("?" for _ in lookup_ids) + ")")
        all_params.extend(lookup_ids)
    if not selector_parts:
        return []

    rows = reader._execute(
        "SELECT * FROM agent_memories WHERE lifecycle_status='active' "
        "AND review_status IN ('pending','confirmed') AND sensitivity!='secret' "
        "AND ("
        + " OR ".join(selector_parts)
        + ") ORDER BY id LIMIT ?",
        (*all_params, MAX_CONSOLIDATION_EXISTING + 1),
    ).fetchall()
    if len(rows) > MAX_CONSOLIDATION_EXISTING:
        raise MemoryConsolidationWriteError(
            "protected indexed snapshot exceeds the W02-A existing-row bound"
        )
    return [
        reader._record(row, access=MemoryReadAccess.LOCAL_MANAGEMENT)
        for row in rows
    ]


def _sync_sidecar_locked(
    writer: ProtectedMemoryWriter,
    plan: ConsolidationPlan,
    receipt: ConsolidationWriteReceipt,
) -> None:
    created_iter = iter(receipt.created_ids)
    for action in plan.actions:
        if action.decision not in {"create", "supersede"}:
            continue
        try:
            memory_id = next(created_iter)
        except StopIteration as exc:
            raise MemoryConsolidationWriteError(
                "protected write receipt lost a created memory id"
            ) from exc
        row = writer._row_locked(memory_id)
        if row is None or row["lifecycle_status"] != "active":
            raise MemoryConsolidationWriteError(
                "protected write lost the newly-created active row"
            )
        sync_protected_exact_lookup_row(
            writer._execute,
            writer.codec,
            memory_id=memory_id,
            subject=action.candidate.subject,
            predicate=action.candidate.predicate,
            value=action.candidate.value,
            sensitivity=action.candidate.sensitivity,
            review_status=action.candidate.review_status,
            lifecycle_status="active",
            now=float(row["updated_at"]),
        )
        if action.decision == "supersede":
            if not action.existing_id:
                raise MemoryConsolidationWriteError(
                    "protected supersede receipt lost its predecessor id"
                )
            remove_protected_exact_lookup_row(
                writer._execute,
                writer.codec,
                memory_id=action.existing_id,
                now=float(row["updated_at"]),
            )

    try:
        next(created_iter)
    except StopIteration:
        return
    raise MemoryConsolidationWriteError(
        "protected write receipt contains an unexpected created memory id"
    )


def _is_verbatim(candidate: MemoryCandidate) -> bool:
    return (
        candidate.subject == VERBATIM_USER_SUBJECT
        and candidate.predicate == VERBATIM_USER_PREDICATE
    )
