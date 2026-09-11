from __future__ import annotations

import inspect
from collections import Counter
from dataclasses import dataclass
from itertools import islice
from typing import Any, Awaitable, Callable, Iterable, Mapping

from .consolidation import (
    ConsolidationAction,
    ConsolidationPlan,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from .extraction import (
    MAX_MEMORY_CANDIDATES,
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    CompletedMemoryTurn,
    MemoryCandidate,
    MemoryCandidateExtractor,
    MemoryExtractionError,
    _looks_like_credential,
)


COMPLETED_TURN_PERSISTENCE_RECEIPT_SCHEMA = (
    "kaliv-memory-completed-turn-persistence-receipt/v1"
)
CONSOLIDATION_WRITE_RECEIPT_SCHEMA = "kaliv-memory-consolidation-write-receipt/v1"
_MAX_RECEIPT_ID_CHARS = 100


class CompletedTurnPersistenceError(RuntimeError):
    """A completed turn could not cross the W03-A persistence boundary safely."""


@dataclass(frozen=True)
class CompletedTurnWriteReceipt:
    schema: str
    considered_count: int
    created_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    superseding_ids: tuple[str, ...]
    deduped_ids: tuple[str, ...]
    skipped_count: int
    replayed: bool
    sent_to_store: bool

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


@dataclass(frozen=True)
class CompletedTurnPersistenceReceipt:
    schema: str
    extracted_count: int
    eligible_count: int
    deferred_count: int
    write_receipt: CompletedTurnWriteReceipt | None
    sent_to_store: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "extracted_count": self.extracted_count,
            "eligible_count": self.eligible_count,
            "deferred_count": self.deferred_count,
            "write_receipt": (
                None if self.write_receipt is None else self.write_receipt.to_dict()
            ),
            "sent_to_store": self.sent_to_store,
        }


ExtractCandidatesCall = Callable[
    [CompletedMemoryTurn], Awaitable[Iterable[MemoryCandidate]]
]
PreparePlanCall = Callable[[tuple[MemoryCandidate, ...]], ConsolidationPlan]
ApplyPlanCall = Callable[[ConsolidationPlan], Any]


class CompletedTurnMemoryPersistence:
    """Compose W01 -> W02 for one completed turn without owning storage authority.

    W03-A is deliberately storage-neutral. The caller injects W01 extraction,
    W02-A plan preparation and W02-B application. This class never imports Agent 3
    storage, opens a database, mounts HTTP, calls a model by itself or broadens
    write authority.

    The completed turn is validated through the exact W01 pre-model boundary
    before the injected extractor can observe it. Candidate provenance and literal
    grounding are then rebound to that validated turn. Only the exact
    server-normalized W01 confirmed verbatim shape may cross into the persistence
    callbacks. Pending, secret and semantic proposals are counted as deferred and
    remain outside durable auto-write authority.
    """

    def __init__(
        self,
        *,
        extract_candidates: ExtractCandidatesCall,
        prepare_plan: PreparePlanCall,
        apply_plan: ApplyPlanCall,
    ):
        if not callable(extract_candidates):
            raise CompletedTurnPersistenceError("extract_candidates must be callable")
        if not callable(prepare_plan):
            raise CompletedTurnPersistenceError("prepare_plan must be callable")
        if not callable(apply_plan):
            raise CompletedTurnPersistenceError("apply_plan must be callable")
        self._extract_candidates = extract_candidates
        self._prepare_plan = prepare_plan
        self._apply_plan = apply_plan

    async def persist(
        self,
        turn: CompletedMemoryTurn,
    ) -> CompletedTurnPersistenceReceipt:
        try:
            bounded_turn = MemoryCandidateExtractor._validate_turn(turn)
        except MemoryExtractionError as exc:
            raise CompletedTurnPersistenceError(
                "W03-A completed turn violates the W01 pre-model boundary"
            ) from exc

        candidates = await self._extract(bounded_turn)
        self._validate_candidate_batch(candidates, bounded_turn)

        eligible = tuple(
            item
            for item in candidates
            if _auto_persistable(item, bounded_turn)
        )
        deferred_count = len(candidates) - len(eligible)
        if not eligible:
            return CompletedTurnPersistenceReceipt(
                schema=COMPLETED_TURN_PERSISTENCE_RECEIPT_SCHEMA,
                extracted_count=len(candidates),
                eligible_count=0,
                deferred_count=deferred_count,
                write_receipt=None,
                sent_to_store=False,
            )

        plan = self._prepare(eligible)
        write_receipt = self._apply(plan, expected_count=len(eligible))
        return CompletedTurnPersistenceReceipt(
            schema=COMPLETED_TURN_PERSISTENCE_RECEIPT_SCHEMA,
            extracted_count=len(candidates),
            eligible_count=len(eligible),
            deferred_count=deferred_count,
            write_receipt=write_receipt,
            sent_to_store=True,
        )

    async def _extract(
        self,
        turn: CompletedMemoryTurn,
    ) -> tuple[MemoryCandidate, ...]:
        try:
            result = self._extract_candidates(turn)
            if not inspect.isawaitable(result):
                raise CompletedTurnPersistenceError(
                    "W03-A extraction callback must be async"
                )
            raw = await result
        except CompletedTurnPersistenceError:
            raise
        except Exception as exc:
            raise CompletedTurnPersistenceError("W03-A candidate extraction failed") from exc

        if isinstance(raw, (str, bytes, bytearray)):
            raise CompletedTurnPersistenceError(
                "W03-A extraction callback must return MemoryCandidate items"
            )
        try:
            rows = tuple(islice(iter(raw), MAX_MEMORY_CANDIDATES + 1))
        except TypeError as exc:
            raise CompletedTurnPersistenceError(
                "W03-A extraction callback returned a non-iterable batch"
            ) from exc
        if len(rows) > MAX_MEMORY_CANDIDATES:
            raise CompletedTurnPersistenceError(
                "W03-A extraction callback exceeded the W01 candidate bound"
            )
        if any(not isinstance(item, MemoryCandidate) for item in rows):
            raise CompletedTurnPersistenceError(
                "W03-A accepts validated MemoryCandidate objects only"
            )
        return rows

    @staticmethod
    def _validate_candidate_batch(
        candidates: tuple[MemoryCandidate, ...],
        turn: CompletedMemoryTurn,
    ) -> None:
        try:
            # Validation only. W03-A does not use this empty-snapshot plan for a
            # write; the injected prepare callback owns the trusted current-state
            # snapshot and W02-B will revalidate it again under the write lock.
            MemoryConsolidator().plan(candidates, ())
        except MemoryConsolidationError as exc:
            raise CompletedTurnPersistenceError(
                "W03-A candidate batch violates the W01/W02 contract"
            ) from exc

        for candidate in candidates:
            if candidate.source_ref != turn.source_ref:
                raise CompletedTurnPersistenceError(
                    "W03-A candidate source_ref is not bound to the completed turn"
                )
            if candidate.source_type == "user_explicit":
                if not candidate.evidence or candidate.evidence not in turn.user_text:
                    raise CompletedTurnPersistenceError(
                        "W03-A user-explicit evidence is not grounded in the completed turn"
                    )
                if candidate.value not in candidate.evidence:
                    raise CompletedTurnPersistenceError(
                        "W03-A user-explicit value is not grounded in its evidence"
                    )
            if candidate.review_status == "confirmed" and not _auto_persistable(
                candidate, turn
            ):
                raise CompletedTurnPersistenceError(
                    "W03-A confirmed candidate violates the W01 turn-bound authority shape"
                )

    def _prepare(
        self,
        eligible: tuple[MemoryCandidate, ...],
    ) -> ConsolidationPlan:
        try:
            plan = self._prepare_plan(eligible)
        except Exception as exc:
            raise CompletedTurnPersistenceError(
                "W03-A W02-A plan preparation failed"
            ) from exc
        if inspect.isawaitable(plan):
            raise CompletedTurnPersistenceError(
                "W03-A plan preparation callback must be synchronous"
            )
        if not isinstance(plan, ConsolidationPlan):
            raise CompletedTurnPersistenceError(
                "W03-A plan preparation did not return a ConsolidationPlan"
            )
        _validate_plan_binding(plan, eligible)
        return plan

    def _apply(
        self,
        plan: ConsolidationPlan,
        *,
        expected_count: int,
    ) -> CompletedTurnWriteReceipt:
        try:
            raw = self._apply_plan(plan)
        except Exception as exc:
            raise CompletedTurnPersistenceError("W03-A durable write failed") from exc
        if inspect.isawaitable(raw):
            raise CompletedTurnPersistenceError(
                "W03-A plan application callback must be synchronous"
            )
        return _parse_write_receipt(raw, expected_count=expected_count)


def _auto_persistable(
    candidate: MemoryCandidate,
    turn: CompletedMemoryTurn,
) -> bool:
    if (
        candidate.subject != VERBATIM_USER_SUBJECT
        or candidate.predicate != VERBATIM_USER_PREDICATE
        or candidate.kind != "note"
        or candidate.sensitivity != "private"
        or candidate.source_type != "user_explicit"
        or candidate.source_ref != turn.source_ref
        or isinstance(candidate.confidence, bool)
        or float(candidate.confidence) != 1.0
        or candidate.review_status != "confirmed"
        or not candidate.evidence
        or candidate.value != candidate.evidence
        or candidate.evidence != turn.user_text
    ):
        return False
    return not _looks_like_credential(
        subject=candidate.subject,
        predicate=candidate.predicate,
        value=candidate.value,
        evidence=candidate.evidence,
    )


def _validate_plan_binding(
    plan: ConsolidationPlan,
    eligible: tuple[MemoryCandidate, ...],
) -> None:
    if plan.receipt.sent_to_store is not False:
        raise CompletedTurnPersistenceError(
            "W03-A requires a pre-store W02-A plan receipt"
        )
    if len(plan.actions) != len(eligible):
        raise CompletedTurnPersistenceError(
            "W03-A W02-A plan changed the eligible candidate count"
        )
    if any(not isinstance(action, ConsolidationAction) for action in plan.actions):
        raise CompletedTurnPersistenceError("W03-A W02-A plan contains invalid actions")
    if Counter(action.candidate for action in plan.actions) != Counter(eligible):
        raise CompletedTurnPersistenceError(
            "W03-A W02-A plan changed eligible candidate identity"
        )
    if plan.receipt.considered_count != len(eligible):
        raise CompletedTurnPersistenceError(
            "W03-A W02-A receipt does not bind the eligible candidate count"
        )


_WRITE_RECEIPT_KEYS = {
    "schema",
    "considered_count",
    "created_count",
    "superseded_count",
    "deduped_count",
    "skipped_count",
    "created_ids",
    "superseded_ids",
    "superseding_ids",
    "deduped_ids",
    "replayed",
    "sent_to_store",
}


def _parse_write_receipt(raw: Any, *, expected_count: int) -> CompletedTurnWriteReceipt:
    if not isinstance(raw, Mapping):
        projector = getattr(raw, "to_dict", None)
        if not callable(projector):
            raise CompletedTurnPersistenceError(
                "W03-A write callback returned an invalid receipt"
            )
        raw = projector()
    if not isinstance(raw, Mapping) or set(raw) != _WRITE_RECEIPT_KEYS:
        raise CompletedTurnPersistenceError(
            "W03-A write receipt fields do not match the W02-B contract"
        )
    if raw.get("schema") != CONSOLIDATION_WRITE_RECEIPT_SCHEMA:
        raise CompletedTurnPersistenceError("W03-A write receipt schema mismatch")

    considered = _count(raw.get("considered_count"), "considered_count")
    created_count = _count(raw.get("created_count"), "created_count")
    superseded_count = _count(raw.get("superseded_count"), "superseded_count")
    deduped_count = _count(raw.get("deduped_count"), "deduped_count")
    skipped_count = _count(raw.get("skipped_count"), "skipped_count")
    if considered != expected_count:
        raise CompletedTurnPersistenceError(
            "W03-A write receipt considered_count mismatch"
        )

    created_ids = _ids(raw.get("created_ids"), "created_ids")
    superseded_ids = _ids(raw.get("superseded_ids"), "superseded_ids")
    superseding_ids = _ids(raw.get("superseding_ids"), "superseding_ids")
    deduped_ids = _ids(raw.get("deduped_ids"), "deduped_ids")
    if created_count != len(created_ids):
        raise CompletedTurnPersistenceError("W03-A created_count mismatch")
    if superseded_count != len(superseded_ids) or superseded_count != len(
        superseding_ids
    ):
        raise CompletedTurnPersistenceError("W03-A supersede receipt mismatch")
    if deduped_count != len(deduped_ids):
        raise CompletedTurnPersistenceError("W03-A deduped_count mismatch")
    if created_count + deduped_count + skipped_count != considered:
        raise CompletedTurnPersistenceError(
            "W03-A write receipt action accounting mismatch"
        )
    if superseded_count > created_count or not set(superseding_ids).issubset(
        set(created_ids)
    ):
        raise CompletedTurnPersistenceError(
            "W03-A superseding ids are not bound to created ids"
        )
    if set(created_ids) & set(deduped_ids):
        raise CompletedTurnPersistenceError(
            "W03-A write receipt reuses created ids as dedupe ids"
        )
    if set(superseded_ids) & set(deduped_ids):
        raise CompletedTurnPersistenceError(
            "W03-A write receipt reuses superseded ids as dedupe ids"
        )

    replayed = raw.get("replayed")
    sent_to_store = raw.get("sent_to_store")
    if not isinstance(replayed, bool) or sent_to_store is not True:
        raise CompletedTurnPersistenceError(
            "W03-A write receipt has invalid replay/store authority flags"
        )
    if replayed and (created_count != 0 or superseded_count != 0):
        raise CompletedTurnPersistenceError(
            "W03-A replay receipt cannot claim fresh durable mutation"
        )

    return CompletedTurnWriteReceipt(
        schema=CONSOLIDATION_WRITE_RECEIPT_SCHEMA,
        considered_count=considered,
        created_ids=created_ids,
        superseded_ids=superseded_ids,
        superseding_ids=superseding_ids,
        deduped_ids=deduped_ids,
        skipped_count=skipped_count,
        replayed=replayed,
        sent_to_store=True,
    )


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CompletedTurnPersistenceError(f"W03-A write receipt {name} is invalid")
    return value


def _ids(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CompletedTurnPersistenceError(f"W03-A write receipt {name} is invalid")
    result: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or len(item) > _MAX_RECEIPT_ID_CHARS
            or "\x00" in item
        ):
            raise CompletedTurnPersistenceError(
                f"W03-A write receipt {name} contains an invalid id"
            )
        result.append(item)
    if len(result) != len(set(result)):
        raise CompletedTurnPersistenceError(
            f"W03-A write receipt {name} contains duplicate ids"
        )
    return tuple(result)
