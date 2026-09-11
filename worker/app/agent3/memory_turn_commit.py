from __future__ import annotations

from ..memory.consolidation import (
    ConsolidationPlan,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from ..memory.extraction import MemoryCandidate
from ..memory.write_service import DurableCandidateWrite
from .memory import MemoryStore
from .memory_consolidation_indexed import (
    _indexed_snapshot_locked,
    _sync_created_actions_locked,
)
from .memory_consolidation_writer import (
    WRITE_RECEIPT_SCHEMA,
    ConsolidationWriteReceipt,
    MemoryConsolidationWriteError,
    _apply_legacy_fresh_locked,
    _apply_protected_fresh_locked,
    _legacy_snapshot_locked,
    _protected_snapshot_locked,
    _replan,
)
from .memory_protected_lookup import (
    ProtectedMemoryLookupError,
    ProtectedMemoryVerbatimLookup,
)
from .memory_protected_reader import ProtectedMemoryReader
from .memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter


def _seed_plan(candidates: tuple[MemoryCandidate, ...]) -> ConsolidationPlan:
    """Validate one W01 candidate batch and derive selectors without storage authority."""
    try:
        return MemoryConsolidator().plan(candidates, ())
    except MemoryConsolidationError as exc:
        raise MemoryConsolidationWriteError(
            "W03 candidate batch is outside the W02-A boundary"
        ) from exc


def _project(receipt: ConsolidationWriteReceipt) -> DurableCandidateWrite:
    if not isinstance(receipt, ConsolidationWriteReceipt):
        raise MemoryConsolidationWriteError("W02-B returned an invalid write receipt")
    if receipt.schema != WRITE_RECEIPT_SCHEMA or receipt.sent_to_store is not True:
        raise MemoryConsolidationWriteError("W02-B write receipt boundary mismatch")
    return DurableCandidateWrite(
        considered_count=receipt.considered_count,
        created_ids=receipt.created_ids,
        superseded_ids=receipt.superseded_ids,
        superseding_ids=receipt.superseding_ids,
        deduped_ids=receipt.deduped_ids,
        skipped_count=receipt.skipped_count,
        replayed=receipt.replayed,
        sent_to_store=receipt.sent_to_store,
    )


def commit_legacy_candidates(
    store: MemoryStore,
    candidates: tuple[MemoryCandidate, ...],
) -> DurableCandidateWrite:
    """Plan and atomically persist one W01 batch through legacy W02 storage.

    The validation-only seed plan is used only to derive bounded storage selectors.
    The authoritative W02-A plan is produced from the fresh durable snapshot while
    the existing MemoryStore write transaction is held, then applied before that
    transaction can release.
    """
    if not isinstance(store, MemoryStore):
        raise MemoryConsolidationWriteError("legacy W03 requires MemoryStore")
    if not isinstance(candidates, tuple):
        raise MemoryConsolidationWriteError("W03 candidates must be a tuple")
    seed = _seed_plan(candidates)
    with store._transaction():
        snapshot = _legacy_snapshot_locked(store, candidates, seed)
        fresh = _replan(candidates, snapshot)
        receipt = _apply_legacy_fresh_locked(
            store,
            fresh,
            {record.id: record for record in snapshot},
        )
    return _project(receipt)


def commit_protected_candidates(
    writer: ProtectedMemoryWriter,
    candidates: tuple[MemoryCandidate, ...],
    *,
    access: MemoryWriteAccess,
) -> DurableCandidateWrite:
    """Plan and atomically persist one W01 batch through protected W02 storage."""
    if not isinstance(writer, ProtectedMemoryWriter):
        raise MemoryConsolidationWriteError(
            "protected W03 requires ProtectedMemoryWriter"
        )
    if not isinstance(candidates, tuple):
        raise MemoryConsolidationWriteError("W03 candidates must be a tuple")
    writer._access(access)
    seed = _seed_plan(candidates)
    with writer._transaction():
        writer._validate_migration()
        with ProtectedMemoryReader(
            writer.path,
            writer.codec,
            busy_timeout_ms=writer.busy_timeout_ms,
        ) as reader:
            snapshot = _protected_snapshot_locked(reader, candidates, seed)
            fresh = _replan(candidates, snapshot)
        receipt = _apply_protected_fresh_locked(
            writer,
            fresh,
            {record.id: record for record in snapshot},
        )
    return _project(receipt)


def commit_indexed_protected_candidates(
    writer: ProtectedMemoryWriter,
    candidates: tuple[MemoryCandidate, ...],
    *,
    access: MemoryWriteAccess,
) -> DurableCandidateWrite:
    """Use #1218's explicit blind index for a protected W03 candidate batch.

    This never creates or repairs the sidecar. Stores that opt into indexed W03
    must have completed the explicit protected verbatim lookup migration already.
    Missing/stale sidecar state therefore fails closed exactly as the landed
    indexed W02-B entry point does.
    """
    if not isinstance(writer, ProtectedMemoryWriter):
        raise MemoryConsolidationWriteError(
            "indexed protected W03 requires ProtectedMemoryWriter"
        )
    if not isinstance(candidates, tuple):
        raise MemoryConsolidationWriteError("W03 candidates must be a tuple")
    writer._access(access)
    seed = _seed_plan(candidates)
    try:
        with writer._transaction():
            writer._validate_migration()
            lookup = ProtectedMemoryVerbatimLookup.load_locked(
                writer._conn,
                writer.codec,
            )
            try:
                lookup.assert_complete_for_active_locked(writer._conn)
                with ProtectedMemoryReader(
                    writer.path,
                    writer.codec,
                    busy_timeout_ms=writer.busy_timeout_ms,
                ) as reader:
                    snapshot = _indexed_snapshot_locked(
                        reader,
                        lookup,
                        candidates,
                        seed,
                    )
                    fresh = _replan(candidates, snapshot)
                receipt = _apply_protected_fresh_locked(
                    writer,
                    fresh,
                    {record.id: record for record in snapshot},
                )
                _sync_created_actions_locked(writer, lookup, fresh, receipt)
                lookup.assert_complete_for_active_locked(writer._conn)
            finally:
                lookup.close()
    except ProtectedMemoryLookupError as exc:
        raise MemoryConsolidationWriteError(
            "indexed protected W03 lookup failed closed"
        ) from exc
    return _project(receipt)
