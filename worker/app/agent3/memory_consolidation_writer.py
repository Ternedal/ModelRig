from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..memory.consolidation import (
    MAX_CONSOLIDATION_CANDIDATES,
    MAX_CONSOLIDATION_EXISTING,
    ConsolidationAction,
    ConsolidationPlan,
    ConsolidationReceipt,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from ..memory.extraction import (
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    MemoryCandidate,
)
from .memory import MemoryConflict, MemoryRecord, MemoryStore
from .memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from .memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter


WRITE_RECEIPT_SCHEMA = "kaliv-memory-consolidation-write-receipt/v1"


class MemoryConsolidationWriteError(RuntimeError):
    """A W02-A plan cannot be applied without broadening storage authority."""


@dataclass(frozen=True)
class ConsolidationWriteReceipt:
    schema: str
    considered_count: int
    created_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    superseding_ids: tuple[str, ...]
    deduped_ids: tuple[str, ...]
    skipped_count: int
    replayed: bool
    sent_to_store: bool = True

    @property
    def created_count(self) -> int:
        return len(self.created_ids)

    @property
    def superseded_count(self) -> int:
        return len(self.superseded_ids)

    @property
    def deduped_count(self) -> int:
        return len(self.deduped_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "considered_count": self.considered_count,
            "created_count": self.created_count,
            "superseded_count": self.superseded_count,
            "deduped_count": self.deduped_count,
            "skipped_count": self.skipped_count,
            "created_ids": list(self.created_ids),
            "superseded_ids": list(self.superseded_ids),
            "superseding_ids": list(self.superseding_ids),
            "deduped_ids": list(self.deduped_ids),
            "replayed": self.replayed,
            "sent_to_store": self.sent_to_store,
        }


def apply_legacy_consolidation_plan(
    store: MemoryStore,
    plan: ConsolidationPlan,
) -> ConsolidationWriteReceipt:
    """Atomically execute one still-current W02-A plan against legacy storage."""
    candidates = _validate_plan(plan)
    with store._transaction():
        snapshot = _legacy_snapshot_locked(store, candidates, plan)
        fresh = _replan(candidates, snapshot)
        if fresh != plan:
            replay = _legacy_replay_receipt_locked(store, plan, fresh)
            if replay is not None:
                return replay
            raise MemoryConsolidationWriteError(
                "legacy consolidation plan is stale or was not produced by W02-A"
            )
        return _apply_legacy_fresh_locked(
            store,
            fresh,
            {record.id: record for record in snapshot},
        )


def apply_protected_consolidation_plan(
    writer: ProtectedMemoryWriter,
    plan: ConsolidationPlan,
    *,
    access: MemoryWriteAccess,
) -> ConsolidationWriteReceipt:
    """Atomically execute one W02-A plan through the protected local writer."""
    writer._access(access)
    candidates = _validate_plan(plan)
    with writer._transaction():
        writer._validate_migration()
        with ProtectedMemoryReader(
            writer.path,
            writer.codec,
            busy_timeout_ms=writer.busy_timeout_ms,
        ) as reader:
            snapshot = _protected_snapshot_locked(reader, candidates, plan)
            fresh = _replan(candidates, snapshot)
            if fresh != plan:
                replay = _protected_replay_receipt_locked(reader, plan, fresh)
                if replay is not None:
                    return replay
                raise MemoryConsolidationWriteError(
                    "protected consolidation plan is stale or was not produced by W02-A"
                )
        return _apply_protected_fresh_locked(
            writer,
            fresh,
            {record.id: record for record in snapshot},
        )


def _validate_plan(plan: ConsolidationPlan) -> tuple[MemoryCandidate, ...]:
    if not isinstance(plan, ConsolidationPlan):
        raise MemoryConsolidationWriteError("W02-B requires a ConsolidationPlan")
    if len(plan.actions) > MAX_CONSOLIDATION_CANDIDATES:
        raise MemoryConsolidationWriteError("consolidation plan exceeds its hard bound")
    if plan.receipt.sent_to_store is not False:
        raise MemoryConsolidationWriteError("W02-A input receipt must be pre-store")

    counts = {name: 0 for name in ("create", "dedupe", "supersede", "skip")}
    touched: set[str] = set()
    candidates: list[MemoryCandidate] = []
    for action in plan.actions:
        if not isinstance(action, ConsolidationAction):
            raise MemoryConsolidationWriteError("invalid consolidation action")
        if action.decision not in counts:
            raise MemoryConsolidationWriteError("invalid consolidation decision")
        counts[action.decision] += 1
        candidates.append(action.candidate)
        if action.existing_id is not None:
            touched.add(action.existing_id)

    expected = ConsolidationReceipt(
        considered_count=len(plan.actions),
        create_count=counts["create"],
        dedupe_count=counts["dedupe"],
        supersede_count=counts["supersede"],
        skip_count=counts["skip"],
        touched_existing_ids=tuple(sorted(touched)),
        sent_to_store=False,
    )
    if plan.receipt != expected:
        raise MemoryConsolidationWriteError("consolidation receipt does not match actions")

    candidate_rows = tuple(candidates)
    # Validate the candidate authority/bounds before using subject/predicate as
    # storage selectors. The empty snapshot is validation-only; the authoritative
    # plan is rerun under the write lock against current durable state below.
    try:
        MemoryConsolidator().plan(candidate_rows, ())
    except MemoryConsolidationError as exc:
        raise MemoryConsolidationWriteError(
            "consolidation plan contains an invalid W02-A candidate"
        ) from exc
    return candidate_rows


def _replan(
    candidates: tuple[MemoryCandidate, ...],
    snapshot: list[MemoryRecord],
) -> ConsolidationPlan:
    try:
        return MemoryConsolidator().plan(candidates, snapshot)
    except MemoryConsolidationError as exc:
        raise MemoryConsolidationWriteError(
            "current durable state is outside the W02-A consolidation boundary"
        ) from exc


def _snapshot_query(
    candidates: tuple[MemoryCandidate, ...],
    plan: ConsolidationPlan,
    *,
    filter_verbatim_value: bool,
) -> tuple[str | None, tuple[object, ...]]:
    """Build a bounded exact-key lookup instead of scanning the whole memory DB.

    Structured W02-A decisions can depend on every row in the candidate's exact
    subject/predicate slot, so those slots are read in full (within the planner's
    hard bound). In legacy/plaintext storage the canonical verbatim slot can be
    narrowed by exact value because W02-A treats different statement values as
    independent log entries. Protected rows intentionally have an empty plaintext
    ``value`` column, so protected mode must keep the full exact-key selector and
    let ProtectedMemoryReader decrypt values before W02-A replans.

    Trusted ids named by dedupe/supersede actions are also selected explicitly.
    """
    selectors_by_key = sorted(
        {
            (
                item.subject,
                item.predicate,
                item.value
                if (
                    filter_verbatim_value
                    and item.subject == VERBATIM_USER_SUBJECT
                    and item.predicate == VERBATIM_USER_PREDICATE
                )
                else None,
            )
            for item in candidates
        }
    )
    touched = sorted(
        {
            action.existing_id
            for action in plan.actions
            if action.existing_id is not None
        }
    )
    selectors: list[str] = []
    params: list[object] = []
    for subject, predicate, exact_value in selectors_by_key:
        if exact_value is None:
            selectors.append("(subject=? AND predicate=?)")
            params.extend((subject, predicate))
        else:
            selectors.append("(subject=? AND predicate=? AND value=?)")
            params.extend((subject, predicate, exact_value))
    if touched:
        selectors.append("id IN (" + ",".join("?" for _ in touched) + ")")
        params.extend(touched)
    if not selectors:
        return None, ()
    return " OR ".join(selectors), tuple(params)


def _legacy_snapshot_locked(
    store: MemoryStore,
    candidates: tuple[MemoryCandidate, ...],
    plan: ConsolidationPlan,
) -> list[MemoryRecord]:
    selectors, params = _snapshot_query(
        candidates,
        plan,
        filter_verbatim_value=True,
    )
    if selectors is None:
        return []
    rows = store._conn.execute(
        "SELECT * FROM agent_memories WHERE lifecycle_status='active' "
        "AND review_status IN ('pending','confirmed') AND sensitivity!='secret' "
        f"AND ({selectors}) ORDER BY id LIMIT ?",
        (*params, MAX_CONSOLIDATION_EXISTING + 1),
    ).fetchall()
    return [store._record(row) for row in rows]


def _protected_snapshot_locked(
    reader: ProtectedMemoryReader,
    candidates: tuple[MemoryCandidate, ...],
    plan: ConsolidationPlan,
) -> list[MemoryRecord]:
    selectors, params = _snapshot_query(
        candidates,
        plan,
        filter_verbatim_value=False,
    )
    if selectors is None:
        return []
    rows = reader._execute(
        "SELECT * FROM agent_memories WHERE lifecycle_status='active' "
        "AND review_status IN ('pending','confirmed') AND sensitivity!='secret' "
        f"AND ({selectors}) ORDER BY id LIMIT ?",
        (*params, MAX_CONSOLIDATION_EXISTING + 1),
    ).fetchall()
    return [
        reader._record(row, access=MemoryReadAccess.LOCAL_MANAGEMENT)
        for row in rows
    ]


def _candidate_fields(candidate: MemoryCandidate) -> dict[str, object]:
    return {
        **candidate.store_fields(),
        "expires_at": None,
    }


def _full_match(record: MemoryRecord, candidate: MemoryCandidate) -> bool:
    return (
        record.lifecycle_status == "active"
        and record.subject == candidate.subject
        and record.predicate == candidate.predicate
        and record.value == candidate.value
        and record.kind == candidate.kind
        and record.sensitivity == candidate.sensitivity
        and record.source_type == candidate.source_type
        and record.source_ref == candidate.source_ref
        and record.confidence == candidate.confidence
        and record.review_status == candidate.review_status
        and record.expires_at is None
    )


def _replay_receipt(
    plan: ConsolidationPlan,
    fresh: ConsolidationPlan,
    *,
    active_get: Callable[[str], MemoryRecord | None],
    any_get: Callable[[str], MemoryRecord | None],
) -> ConsolidationWriteReceipt | None:
    if len(plan.actions) != len(fresh.actions):
        return None

    deduped: list[str] = []
    skipped = 0
    for original, current in zip(plan.actions, fresh.actions):
        if original.decision in {"dedupe", "skip"}:
            if original != current:
                return None
            if original.decision == "dedupe":
                if original.existing_id is None:
                    return None
                deduped.append(original.existing_id)
            else:
                skipped += 1
            continue

        if original.decision not in {"create", "supersede"}:
            return None
        if current.decision != "dedupe" or current.existing_id is None:
            return None
        durable = active_get(current.existing_id)
        if durable is None or not _full_match(durable, original.candidate):
            return None
        if original.decision == "create":
            if durable.supersedes_id is not None:
                return None
        else:
            if original.reason != "exact_verbatim_authority_promotion":
                return None
            if durable.supersedes_id != original.existing_id:
                return None
            previous = any_get(original.existing_id or "")
            if previous is None or previous.lifecycle_status != "superseded":
                return None
        deduped.append(durable.id)

    return ConsolidationWriteReceipt(
        schema=WRITE_RECEIPT_SCHEMA,
        considered_count=len(plan.actions),
        created_ids=(),
        superseded_ids=(),
        superseding_ids=(),
        deduped_ids=tuple(deduped),
        skipped_count=skipped,
        replayed=True,
    )


def _legacy_replay_receipt_locked(
    store: MemoryStore,
    plan: ConsolidationPlan,
    fresh: ConsolidationPlan,
) -> ConsolidationWriteReceipt | None:
    def get_active(memory_id: str) -> MemoryRecord | None:
        row = store._conn.execute(
            "SELECT * FROM agent_memories WHERE id=? AND lifecycle_status='active'",
            (memory_id,),
        ).fetchone()
        return None if row is None else store._record(row)

    def get_any(memory_id: str) -> MemoryRecord | None:
        row = store._conn.execute(
            "SELECT * FROM agent_memories WHERE id=?",
            (memory_id,),
        ).fetchone()
        return None if row is None else store._record(row)

    return _replay_receipt(
        plan,
        fresh,
        active_get=get_active,
        any_get=get_any,
    )


def _protected_replay_receipt_locked(
    reader: ProtectedMemoryReader,
    plan: ConsolidationPlan,
    fresh: ConsolidationPlan,
) -> ConsolidationWriteReceipt | None:
    def get_record(memory_id: str) -> MemoryRecord | None:
        try:
            return reader.get(
                memory_id,
                access=MemoryReadAccess.LOCAL_MANAGEMENT,
                include_deleted=True,
            )
        except Exception:
            return None

    def get_active(memory_id: str) -> MemoryRecord | None:
        record = get_record(memory_id)
        if record is None or record.lifecycle_status != "active":
            return None
        return record

    return _replay_receipt(
        plan,
        fresh,
        active_get=get_active,
        any_get=get_record,
    )


def _apply_legacy_fresh_locked(
    store: MemoryStore,
    plan: ConsolidationPlan,
    snapshot_by_id: dict[str, MemoryRecord],
) -> ConsolidationWriteReceipt:
    created: list[str] = []
    superseded: list[str] = []
    superseding: list[str] = []
    deduped: list[str] = []
    skipped = 0

    for action in plan.actions:
        if action.decision == "skip":
            skipped += 1
            continue
        if action.decision == "dedupe":
            if action.existing_id is None:
                raise MemoryConsolidationWriteError("dedupe target is missing")
            deduped.append(action.existing_id)
            continue

        fields = store._validate_fields(**_candidate_fields(action.candidate))
        if action.decision == "create":
            created_record = store._insert_locked(**fields)
            created.append(created_record.id)
            continue
        if action.decision != "supersede":
            raise MemoryConsolidationWriteError("unknown consolidation action")
        if action.reason != "exact_verbatim_authority_promotion" or not action.existing_id:
            raise MemoryConsolidationWriteError("supersede authority is invalid")

        previous = snapshot_by_id.get(action.existing_id)
        if previous is None:
            raise MemoryConsolidationWriteError("supersede target is outside fresh snapshot")
        _verify_promotion_target(previous, action.candidate)
        old = store._conn.execute(
            "SELECT * FROM agent_memories WHERE id=? AND lifecycle_status='active' "
            "AND review_status='pending'",
            (action.existing_id,),
        ).fetchone()
        if old is None:
            raise MemoryConsolidationWriteError("supersede target is no longer pending/active")
        replacement = store._insert_locked(
            **fields,
            supersedes_id=action.existing_id,
        )
        changed = store._conn.execute(
            "UPDATE agent_memories SET lifecycle_status='superseded',updated_at=? "
            "WHERE id=? AND lifecycle_status='active' AND review_status='pending'",
            (replacement.updated_at, action.existing_id),
        ).rowcount
        if changed != 1:
            raise MemoryConflict("memory changed during consolidation supersede")
        created.append(replacement.id)
        superseded.append(action.existing_id)
        superseding.append(replacement.id)

    return ConsolidationWriteReceipt(
        schema=WRITE_RECEIPT_SCHEMA,
        considered_count=len(plan.actions),
        created_ids=tuple(created),
        superseded_ids=tuple(superseded),
        superseding_ids=tuple(superseding),
        deduped_ids=tuple(deduped),
        skipped_count=skipped,
        replayed=False,
    )


def _apply_protected_fresh_locked(
    writer: ProtectedMemoryWriter,
    plan: ConsolidationPlan,
    snapshot_by_id: dict[str, MemoryRecord],
) -> ConsolidationWriteReceipt:
    created: list[str] = []
    superseded: list[str] = []
    superseding: list[str] = []
    deduped: list[str] = []
    skipped = 0

    for action in plan.actions:
        if action.decision == "skip":
            skipped += 1
            continue
        if action.decision == "dedupe":
            if action.existing_id is None:
                raise MemoryConsolidationWriteError("dedupe target is missing")
            deduped.append(action.existing_id)
            continue

        fields = writer._validate_fields(**_candidate_fields(action.candidate))
        memory_id = writer._new_id()
        now = writer.clock()
        value_envelope, source_envelope, protected_fields = writer._protect_fields(
            memory_id=memory_id,
            subject=str(fields["subject"]),
            predicate=str(fields["predicate"]),
            sensitivity=str(fields["sensitivity"]),
            value=str(fields["value"]),
            source_ref=(
                None if fields["source_ref"] is None else str(fields["source_ref"])
            ),
            schema_version=1,
        )

        if action.decision == "create":
            writer._insert_locked(
                memory_id=memory_id,
                fields=fields,
                value_envelope=value_envelope,
                source_envelope=source_envelope,
                protected_fields=protected_fields,
                now=now,
                supersedes_id=None,
            )
            created.append(memory_id)
            continue
        if action.decision != "supersede":
            raise MemoryConsolidationWriteError("unknown consolidation action")
        if action.reason != "exact_verbatim_authority_promotion" or not action.existing_id:
            raise MemoryConsolidationWriteError("supersede authority is invalid")

        previous = snapshot_by_id.get(action.existing_id)
        if previous is None:
            raise MemoryConsolidationWriteError("supersede target is outside fresh snapshot")
        _verify_promotion_target(previous, action.candidate)
        old = writer._row_locked(action.existing_id)
        if (
            old is None
            or old["lifecycle_status"] != "active"
            or old["review_status"] != "pending"
        ):
            raise MemoryConsolidationWriteError("supersede target is no longer pending/active")
        writer._validate_protected_row(old)
        writer._insert_locked(
            memory_id=memory_id,
            fields=fields,
            value_envelope=value_envelope,
            source_envelope=source_envelope,
            protected_fields=protected_fields,
            now=now,
            supersedes_id=action.existing_id,
        )
        changed = writer._execute(
            "UPDATE agent_memories SET lifecycle_status='superseded',updated_at=? "
            "WHERE id=? AND lifecycle_status='active' AND review_status='pending'",
            (now, action.existing_id),
        ).rowcount
        if changed != 1:
            raise MemoryConflict("memory changed during protected consolidation supersede")
        created.append(memory_id)
        superseded.append(action.existing_id)
        superseding.append(memory_id)

    return ConsolidationWriteReceipt(
        schema=WRITE_RECEIPT_SCHEMA,
        considered_count=len(plan.actions),
        created_ids=tuple(created),
        superseded_ids=tuple(superseded),
        superseding_ids=tuple(superseding),
        deduped_ids=tuple(deduped),
        skipped_count=skipped,
        replayed=False,
    )


def _verify_promotion_target(
    old: MemoryRecord,
    candidate: MemoryCandidate,
) -> None:
    if (
        old.lifecycle_status != "active"
        or old.review_status != "pending"
        or old.subject != candidate.subject
        or old.predicate != candidate.predicate
        or old.value != candidate.value
        or old.sensitivity != "private"
        or candidate.review_status != "confirmed"
        or candidate.sensitivity != "private"
    ):
        raise MemoryConsolidationWriteError(
            "supersede target no longer matches exact verbatim authority promotion"
        )
