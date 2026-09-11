from __future__ import annotations

import inspect
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .consolidation import (
    MAX_RECORD_ID_CHARS,
    ConsolidationPlan,
    ConsolidationReceipt,
    MemoryConsolidationError,
    MemoryConsolidator,
)
from .extraction import (
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    CompletedMemoryTurn,
    MemoryCandidate,
    MemoryCandidateExtractor,
)


TURN_PERSISTENCE_RECEIPT_SCHEMA = "kaliv-memory-turn-persistence/v1"
W02_WRITE_RECEIPT_SCHEMA = "kaliv-memory-consolidation-write-receipt/v1"


class MemoryTurnPersistenceError(RuntimeError):
    """A completed turn could not cross the W03-A persistence boundary safely."""


ExtractCandidates = Callable[[CompletedMemoryTurn], Awaitable[tuple[MemoryCandidate, ...]]]
PreparePlan = Callable[[tuple[MemoryCandidate, ...]], ConsolidationPlan]
ApplyPlan = Callable[[ConsolidationPlan], Any]


@dataclass(frozen=True)
class MemoryTurnWriteReceipt:
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
class MemoryTurnPersistenceReceipt:
    schema: str
    extracted_count: int
    eligible_count: int
    deferred_count: int
    write_receipt: MemoryTurnWriteReceipt | None

    @property
    def sent_to_store(self) -> bool:
        return self.write_receipt is not None and self.write_receipt.sent_to_store

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "extracted_count": self.extracted_count,
            "eligible_count": self.eligible_count,
            "deferred_count": self.deferred_count,
            "sent_to_store": self.sent_to_store,
            "write_receipt": (
                None if self.write_receipt is None else self.write_receipt.to_dict()
            ),
        }


class MemoryTurnPersistenceOrchestrator:
    """Compose W01 extraction with injected W02 planning/apply callbacks.

    This shared boundary deliberately owns no database and imports no Agent 3
    storage implementation. Only the server-normalized, whole-turn canonical
    confirmed verbatim W01 shape is eligible for automatic persistence. Every
    semantic/pending/secret/non-canonical proposal is deferred before W02 is
    called.
    """

    def __init__(
        self,
        *,
        extract_candidates: ExtractCandidates,
        prepare_plan: PreparePlan,
        apply_plan: ApplyPlan,
    ) -> None:
        if not callable(extract_candidates):
            raise MemoryTurnPersistenceError("W03-A extractor must be callable")
        if not callable(prepare_plan):
            raise MemoryTurnPersistenceError("W03-A plan callback must be callable")
        if not callable(apply_plan):
            raise MemoryTurnPersistenceError("W03-A apply callback must be callable")
        self._extract_candidates = extract_candidates
        self._prepare_plan = prepare_plan
        self._apply_plan = apply_plan

    async def persist(self, turn: CompletedMemoryTurn) -> MemoryTurnPersistenceReceipt:
        try:
            bounded_turn = MemoryCandidateExtractor._validate_turn(turn)
        except Exception as exc:
            raise MemoryTurnPersistenceError("completed turn failed W01 validation") from exc

        extracted = await self._extract(bounded_turn)
        self._validate_extracted(extracted, bounded_turn)
        eligible = tuple(
            candidate
            for candidate in extracted
            if self._is_auto_persistable(candidate, bounded_turn)
        )
        deferred_count = len(extracted) - len(eligible)

        if not eligible:
            return MemoryTurnPersistenceReceipt(
                schema=TURN_PERSISTENCE_RECEIPT_SCHEMA,
                extracted_count=len(extracted),
                eligible_count=0,
                deferred_count=deferred_count,
                write_receipt=None,
            )

        try:
            plan = self._prepare_plan(eligible)
        except Exception as exc:
            raise MemoryTurnPersistenceError("W02 plan preparation failed") from exc
        self._validate_plan(plan, eligible)

        try:
            raw_receipt = self._apply_plan(plan)
        except Exception as exc:
            raise MemoryTurnPersistenceError("W02 durable apply failed") from exc
        write_receipt = self._normalize_write_receipt(raw_receipt, len(eligible))

        return MemoryTurnPersistenceReceipt(
            schema=TURN_PERSISTENCE_RECEIPT_SCHEMA,
            extracted_count=len(extracted),
            eligible_count=len(eligible),
            deferred_count=deferred_count,
            write_receipt=write_receipt,
        )

    async def _extract(
        self,
        turn: CompletedMemoryTurn,
    ) -> tuple[MemoryCandidate, ...]:
        try:
            pending = self._extract_candidates(turn)
        except Exception as exc:
            raise MemoryTurnPersistenceError("W01 candidate extraction failed") from exc
        if not inspect.isawaitable(pending):
            raise MemoryTurnPersistenceError("W03-A extractor must be async")
        try:
            result = await pending
        except Exception as exc:
            raise MemoryTurnPersistenceError("W01 candidate extraction failed") from exc
        if not isinstance(result, tuple):
            raise MemoryTurnPersistenceError(
                "W01 extraction callback must return a candidate tuple"
            )
        return result

    @staticmethod
    def _validate_extracted(
        candidates: tuple[MemoryCandidate, ...],
        turn: CompletedMemoryTurn,
    ) -> None:
        try:
            # Validation-only: W02-A owns the current candidate hard bounds and
            # authority checks. No plan returned here is ever sent to storage.
            MemoryConsolidator().plan(candidates, ())
        except MemoryConsolidationError as exc:
            raise MemoryTurnPersistenceError(
                "W01 extraction callback returned candidates outside W02 bounds"
            ) from exc
        for candidate in candidates:
            if candidate.source_ref != turn.source_ref:
                raise MemoryTurnPersistenceError(
                    "candidate source_ref is not bound to the completed turn"
                )

    @staticmethod
    def _is_auto_persistable(
        candidate: MemoryCandidate,
        turn: CompletedMemoryTurn,
    ) -> bool:
        return (
            candidate.subject == VERBATIM_USER_SUBJECT
            and candidate.predicate == VERBATIM_USER_PREDICATE
            and candidate.kind == "note"
            and candidate.sensitivity == "private"
            and candidate.source_type == "user_explicit"
            and candidate.confidence == 1.0
            and candidate.review_status == "confirmed"
            and candidate.source_ref == turn.source_ref
            and candidate.value == candidate.evidence == turn.user_text
        )

    @staticmethod
    def _validate_plan(
        plan: Any,
        eligible: tuple[MemoryCandidate, ...],
    ) -> None:
        if not isinstance(plan, ConsolidationPlan):
            raise MemoryTurnPersistenceError("W02 plan callback returned invalid type")
        if len(plan.actions) != len(eligible):
            raise MemoryTurnPersistenceError("W02 plan does not bind every eligible candidate")
        if Counter(action.candidate for action in plan.actions) != Counter(eligible):
            raise MemoryTurnPersistenceError("W02 plan changed the eligible candidate batch")

        counts = {"create": 0, "dedupe": 0, "supersede": 0, "skip": 0}
        touched: set[str] = set()
        for action in plan.actions:
            if action.decision not in counts:
                raise MemoryTurnPersistenceError("W02 plan has invalid decision")
            counts[action.decision] += 1
            if action.existing_id is not None:
                touched.add(action.existing_id)
        expected = ConsolidationReceipt(
            considered_count=len(eligible),
            create_count=counts["create"],
            dedupe_count=counts["dedupe"],
            supersede_count=counts["supersede"],
            skip_count=counts["skip"],
            touched_existing_ids=tuple(sorted(touched)),
            sent_to_store=False,
        )
        if plan.receipt != expected:
            raise MemoryTurnPersistenceError("W02 plan receipt is not bound to its actions")

    @classmethod
    def _normalize_write_receipt(
        cls,
        receipt: Any,
        eligible_count: int,
    ) -> MemoryTurnWriteReceipt:
        try:
            schema = receipt.schema
            considered_count = receipt.considered_count
            created_ids = cls._ids("created_ids", receipt.created_ids)
            superseded_ids = cls._ids("superseded_ids", receipt.superseded_ids)
            superseding_ids = cls._ids("superseding_ids", receipt.superseding_ids)
            deduped_ids = cls._ids("deduped_ids", receipt.deduped_ids)
            skipped_count = receipt.skipped_count
            replayed = receipt.replayed
            sent_to_store = receipt.sent_to_store
        except AttributeError as exc:
            raise MemoryTurnPersistenceError("W02 write receipt is incomplete") from exc

        if schema != W02_WRITE_RECEIPT_SCHEMA:
            raise MemoryTurnPersistenceError("W02 write receipt schema is invalid")
        if isinstance(considered_count, bool) or considered_count != eligible_count:
            raise MemoryTurnPersistenceError("W02 write receipt candidate count is invalid")
        if isinstance(skipped_count, bool) or not isinstance(skipped_count, int):
            raise MemoryTurnPersistenceError("W02 write receipt skipped_count is invalid")
        if skipped_count < 0:
            raise MemoryTurnPersistenceError("W02 write receipt skipped_count is invalid")
        if not isinstance(replayed, bool) or sent_to_store is not True:
            raise MemoryTurnPersistenceError("W02 write receipt state is invalid")
        if len(superseded_ids) != len(superseding_ids):
            raise MemoryTurnPersistenceError("W02 write receipt supersede ids are unbalanced")
        if not set(superseding_ids).issubset(set(created_ids)):
            raise MemoryTurnPersistenceError("W02 write receipt superseding ids are not created")
        if len(created_ids) + len(deduped_ids) + skipped_count != eligible_count:
            raise MemoryTurnPersistenceError("W02 write receipt counts do not balance")

        return MemoryTurnWriteReceipt(
            schema=schema,
            considered_count=considered_count,
            created_ids=created_ids,
            superseded_ids=superseded_ids,
            superseding_ids=superseding_ids,
            deduped_ids=deduped_ids,
            skipped_count=skipped_count,
            replayed=replayed,
            sent_to_store=True,
        )

    @staticmethod
    def _ids(name: str, value: Any) -> tuple[str, ...]:
        if not isinstance(value, tuple):
            raise MemoryTurnPersistenceError(f"W02 write receipt {name} must be a tuple")
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise MemoryTurnPersistenceError(f"W02 write receipt {name} has invalid id")
            cleaned = item.strip()
            if (
                not cleaned
                or cleaned != item
                or "\x00" in cleaned
                or len(cleaned) > MAX_RECORD_ID_CHARS
                or cleaned in seen
            ):
                raise MemoryTurnPersistenceError(f"W02 write receipt {name} has invalid id")
            seen.add(cleaned)
            result.append(cleaned)
        return tuple(result)
