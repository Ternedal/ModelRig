from __future__ import annotations

from collections import defaultdict
from typing import Iterable

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
    _validate_plan,
)
from .memory_protected_lookup import (
    LOOKUP_SCHEMA,
    ProtectedMemoryLookupError,
    ProtectedMemoryVerbatimLookup,
)
from .memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from .memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter


class IndexedMemoryConsolidationWriteError(MemoryConsolidationWriteError):
    """The scalable protected lookup path cannot prove a current W02-B plan."""


def apply_protected_consolidation_plan_indexed(
    writer: ProtectedMemoryWriter,
    plan: ConsolidationPlan,
    *,
    access: MemoryWriteAccess,
) -> ConsolidationWriteReceipt:
    """Apply W02-B using the migrated keyed blind index for verbatim exact match.

    This is an explicit opt-in composition primitive for stores that completed the
    #1216 lookup migration. Structured candidates retain the bounded exact-slot
    lookup from W02-B. Canonical verbatim candidates use a server-derived HMAC
    selector, then decrypt and verify every selected row before W02-A replans.
    The blind index never grants authority: stale/forged plans still fail closed.
    """
    writer._access(access)
    candidates = _validate_plan(plan)
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
                        writer,
                        reader,
                        lookup,
                        candidates,
                        plan,
                    )
                    fresh = _replan(candidates, snapshot)
                    if fresh != plan:
                        replay = _protected_replay_receipt_locked(reader, plan, fresh)
                        if replay is not None:
                            return replay
                        raise IndexedMemoryConsolidationWriteError(
                            "indexed protected consolidation plan is stale or forged"
                        )

                receipt = _apply_protected_fresh_locked(
                    writer,
                    fresh,
                    {record.id: record for record in snapshot},
                )
                _index_created_actions_locked(writer, lookup, fresh, receipt)
                lookup.assert_complete_for_active_locked(writer._conn)
                return receipt
            finally:
                lookup.close()
    except ProtectedMemoryLookupError as exc:
        raise IndexedMemoryConsolidationWriteError(str(exc)) from exc


def _indexed_snapshot_locked(
    writer: ProtectedMemoryWriter,
    reader: ProtectedMemoryReader,
    lookup: ProtectedMemoryVerbatimLookup,
    candidates: tuple[MemoryCandidate, ...],
    plan: ConsolidationPlan,
) -> list[MemoryRecord]:
    records: dict[str, MemoryRecord] = {}
    _add_structured_rows(reader, candidates, records)
    _add_verbatim_rows(reader, lookup, candidates, records)
    _add_touched_rows(reader, plan, records)
    if len(records) > MAX_CONSOLIDATION_EXISTING:
        raise IndexedMemoryConsolidationWriteError(
            "indexed protected consolidation snapshot exceeds its hard bound"
        )
    return [records[memory_id] for memory_id in sorted(records)]


def _add_structured_rows(
    reader: ProtectedMemoryReader,
    candidates: Iterable[MemoryCandidate],
    records: dict[str, MemoryRecord],
) -> None:
    keys = sorted(
        {
            (candidate.subject, candidate.predicate)
            for candidate in candidates
            if not _is_verbatim(candidate)
            and candidate.sensitivity != "secret"
        }
    )
    if not keys:
        return
    selectors = " OR ".join("(subject=? AND predicate=?)" for _ in keys)
    params: list[object] = []
    for subject, predicate in keys:
        params.extend((subject, predicate))
    rows = reader._execute(
        "SELECT * FROM agent_memories WHERE lifecycle_status='active' "
        "AND review_status IN ('pending','confirmed') AND sensitivity!='secret' "
        f"AND ({selectors}) ORDER BY id LIMIT ?",
        (*params, MAX_CONSOLIDATION_EXISTING + 1),
    ).fetchall()
    if len(rows) > MAX_CONSOLIDATION_EXISTING:
        raise IndexedMemoryConsolidationWriteError(
            "structured protected snapshot exceeds its hard bound"
        )
    for row in rows:
        record = reader._record(row, access=MemoryReadAccess.LOCAL_MANAGEMENT)
        records[record.id] = record


def _add_verbatim_rows(
    reader: ProtectedMemoryReader,
    lookup: ProtectedMemoryVerbatimLookup,
    candidates: Iterable[MemoryCandidate],
    records: dict[str, MemoryRecord],
) -> None:
    values = sorted(
        {
            candidate.value
            for candidate in candidates
            if _is_verbatim(candidate) and candidate.sensitivity != "secret"
        }
    )
    if not values:
        return

    values_by_digest: dict[str, set[str]] = defaultdict(set)
    for value in values:
        values_by_digest[lookup.fingerprint(value)].add(value)
    digests = sorted(values_by_digest)
    placeholders = ",".join("?" for _ in digests)
    rows = reader._execute(
        "SELECT m.*,i.value_hmac AS lookup_value_hmac "
        "FROM agent_memories m "
        "JOIN agent_memory_protected_verbatim_lookup i ON i.memory_id=m.id "
        "WHERE m.subject=? AND m.predicate=? AND m.sensitivity='private' "
        "AND m.protection_state='protected' AND m.lifecycle_status='active' "
        "AND m.review_status IN ('pending','confirmed') AND i.schema=? "
        f"AND i.value_hmac IN ({placeholders}) ORDER BY m.id LIMIT ?",
        (
            VERBATIM_USER_SUBJECT,
            VERBATIM_USER_PREDICATE,
            LOOKUP_SCHEMA,
            *digests,
            MAX_CONSOLIDATION_EXISTING + 1,
        ),
    ).fetchall()
    if len(rows) > MAX_CONSOLIDATION_EXISTING:
        raise IndexedMemoryConsolidationWriteError(
            "verbatim exact-match snapshot exceeds its hard bound"
        )
    for row in rows:
        digest = str(row["lookup_value_hmac"])
        record = reader._record(row, access=MemoryReadAccess.LOCAL_MANAGEMENT)
        if record.value not in values_by_digest.get(digest, set()):
            raise IndexedMemoryConsolidationWriteError(
                "protected blind-index collision or tampering was detected"
            )
        if lookup.fingerprint(record.value) != digest:
            raise IndexedMemoryConsolidationWriteError(
                "protected blind-index fingerprint does not match decrypted value"
            )
        records[record.id] = record


def _add_touched_rows(
    reader: ProtectedMemoryReader,
    plan: ConsolidationPlan,
    records: dict[str, MemoryRecord],
) -> None:
    # Structured plans may name a trusted existing id, but canonical verbatim
    # dedupe/supersede targets must be rediscovered through the blind index.
    # Allowing a verbatim existing_id fallback would let a stale/forged plan
    # bypass the selector that #1216 is specifically designed to revalidate.
    touched = sorted(
        {
            action.existing_id
            for action in plan.actions
            if action.existing_id is not None and not _is_verbatim(action.candidate)
        }
    )
    if not touched:
        return
    placeholders = ",".join("?" for _ in touched)
    rows = reader._execute(
        "SELECT * FROM agent_memories WHERE lifecycle_status='active' "
        "AND review_status IN ('pending','confirmed') AND sensitivity!='secret' "
        f"AND id IN ({placeholders}) ORDER BY id LIMIT ?",
        (*touched, MAX_CONSOLIDATION_EXISTING + 1),
    ).fetchall()
    for row in rows:
        record = reader._record(row, access=MemoryReadAccess.LOCAL_MANAGEMENT)
        records[record.id] = record


def _index_created_actions_locked(
    writer: ProtectedMemoryWriter,
    lookup: ProtectedMemoryVerbatimLookup,
    plan: ConsolidationPlan,
    receipt: ConsolidationWriteReceipt,
) -> None:
    created = iter(receipt.created_ids)
    consumed = 0
    for action in plan.actions:
        if action.decision not in {"create", "supersede"}:
            continue
        try:
            memory_id = next(created)
        except StopIteration as exc:
            raise IndexedMemoryConsolidationWriteError(
                "W02-B receipt omitted a created memory id"
            ) from exc
        consumed += 1
        lookup.index_created_locked(
            writer._conn,
            memory_id=memory_id,
            subject=action.candidate.subject,
            predicate=action.candidate.predicate,
            value=action.candidate.value,
            sensitivity=action.candidate.sensitivity,
            indexed_at=writer.clock(),
        )
    if consumed != len(receipt.created_ids):
        raise IndexedMemoryConsolidationWriteError(
            "W02-B receipt contains unexpected created memory ids"
        )


def _is_verbatim(candidate: MemoryCandidate) -> bool:
    return (
        candidate.subject == VERBATIM_USER_SUBJECT
        and candidate.predicate == VERBATIM_USER_PREDICATE
    )
