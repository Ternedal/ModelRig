from __future__ import annotations

import inspect
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .consolidation import (
    MAX_CONSOLIDATION_CANDIDATES,
    MAX_RECORD_ID_CHARS,
    ConsolidationAction,
    ConsolidationPlan,
    ConsolidationReceipt,
)
from .extraction import (
    KINDS,
    MAX_CANDIDATE_EVIDENCE_CHARS,
    MAX_CANDIDATE_PREDICATE_CHARS,
    MAX_CANDIDATE_SUBJECT_CHARS,
    MAX_CANDIDATE_VALUE_CHARS,
    MAX_MEMORY_CANDIDATES,
    MAX_SOURCE_REF_CHARS,
    SENSITIVITIES,
    SOURCE_TYPES,
    VERBATIM_USER_PREDICATE,
    VERBATIM_USER_SUBJECT,
    CompletedMemoryTurn,
    MemoryCandidate,
    MemoryCandidateExtractor,
)


COMPLETED_TURN_PERSISTENCE_SCHEMA = "kaliv-memory-completed-turn-persistence/v1"
W02_WRITE_RECEIPT_SCHEMA = "kaliv-memory-consolidation-write-receipt/v1"


class MemoryOrchestrationError(RuntimeError):
    """A completed turn cannot cross the W01 -> W02 persistence boundary safely."""


@dataclass(frozen=True)
class DurableWriteReceipt:
    """Value-free projection of the existing W02-B durable write receipt."""

    schema: str
    considered_count: int
    created_ids: tuple[str, ...]
    superseded_ids: tuple[str, ...]
    superseding_ids: tuple[str, ...]
    deduped_ids: tuple[str, ...]
    skipped_count: int
    replayed: bool
    sent_to_store: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "considered_count": self.considered_count,
            "created_count": len(self.created_ids),
            "superseded_count": len(self.superseded_ids),
            "deduped_count": len(self.deduped_ids),
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
    """Bounded W03-A receipt containing no candidate/evidence/source-ref values."""

    schema: str
    extracted_count: int
    eligible_count: int
    deferred_count: int
    write_receipt: DurableWriteReceipt | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "extracted_count": self.extracted_count,
            "eligible_count": self.eligible_count,
            "deferred_count": self.deferred_count,
            "write_receipt": (
                None if self.write_receipt is None else self.write_receipt.to_dict()
            ),
        }


ExtractionCallback = Callable[
    [CompletedMemoryTurn],
    Awaitable[tuple[MemoryCandidate, ...]],
]
PlanPreparationCallback = Callable[
    [tuple[MemoryCandidate, ...]],
    ConsolidationPlan | Awaitable[ConsolidationPlan],
]
PlanApplicationCallback = Callable[
    [ConsolidationPlan],
    object | Awaitable[object],
]


class CompletedTurnMemoryOrchestrator:
    """Compose validated W01 extraction with injected W02 plan/apply callbacks.

    This shared core owns no database, model adapter or Agent 3 storage dependency.
    It auto-forwards only the canonical confirmed verbatim shape that W01 itself
    server-normalizes. Every other valid W01 candidate is counted as deferred and
    is kept away from planning/storage callbacks.
    """

    def __init__(
        self,
        *,
        extract_candidates: ExtractionCallback,
        prepare_plan: PlanPreparationCallback,
        apply_plan: PlanApplicationCallback,
    ) -> None:
        if not callable(extract_candidates):
            raise MemoryOrchestrationError("W01 extraction callback must be callable")
        if not callable(prepare_plan):
            raise MemoryOrchestrationError("W02 plan callback must be callable")
        if not callable(apply_plan):
            raise MemoryOrchestrationError("W02 apply callback must be callable")
        self._extract_candidates = extract_candidates
        self._prepare_plan = prepare_plan
        self._apply_plan = apply_plan

    async def persist(
        self,
        turn: CompletedMemoryTurn,
    ) -> CompletedTurnPersistenceReceipt:
        # Reuse W01's bounded completed-turn normalization before any callback is
        # entered. This does not import or invoke the local Ollama adapter.
        try:
            bounded_turn = MemoryCandidateExtractor._validate_turn(turn)
        except Exception as exc:
            raise MemoryOrchestrationError(
                "completed turn violates the W01 boundary"
            ) from exc

        extraction_result = self._extract_candidates(bounded_turn)
        if not inspect.isawaitable(extraction_result):
            raise MemoryOrchestrationError("W01 extraction callback must be async")
        candidates = await extraction_result
        candidate_rows = self._validate_candidate_batch(candidates, bounded_turn)

        eligible = tuple(
            candidate
            for candidate in candidate_rows
            if self._is_auto_persistable(candidate, bounded_turn)
        )
        deferred_count = len(candidate_rows) - len(eligible)

        if not eligible:
            return CompletedTurnPersistenceReceipt(
                schema=COMPLETED_TURN_PERSISTENCE_SCHEMA,
                extracted_count=len(candidate_rows),
                eligible_count=0,
                deferred_count=deferred_count,
                write_receipt=None,
            )

        plan_result = self._prepare_plan(eligible)
        if inspect.isawaitable(plan_result):
            plan_result = await plan_result
        plan = self._validate_plan_binding(plan_result, eligible)

        write_result = self._apply_plan(plan)
        if inspect.isawaitable(write_result):
            write_result = await write_result
        write_receipt = self._project_write_receipt(write_result, plan)

        return CompletedTurnPersistenceReceipt(
            schema=COMPLETED_TURN_PERSISTENCE_SCHEMA,
            extracted_count=len(candidate_rows),
            eligible_count=len(eligible),
            deferred_count=deferred_count,
            write_receipt=write_receipt,
        )

    @classmethod
    def _validate_candidate_batch(
        cls,
        value: Any,
        turn: CompletedMemoryTurn,
    ) -> tuple[MemoryCandidate, ...]:
        if not isinstance(value, tuple):
            raise MemoryOrchestrationError(
                "W01 extraction callback must return a candidate tuple"
            )
        if (
            len(value) > MAX_MEMORY_CANDIDATES
            or len(value) > MAX_CONSOLIDATION_CANDIDATES
        ):
            raise MemoryOrchestrationError("W01 candidate batch exceeds its hard bound")
        if any(not isinstance(candidate, MemoryCandidate) for candidate in value):
            raise MemoryOrchestrationError(
                "W01 extraction callback returned a non-candidate value"
            )

        seen: set[MemoryCandidate] = set()
        for candidate in value:
            cls._validate_w01_candidate(candidate, turn)
            if candidate in seen:
                raise MemoryOrchestrationError(
                    "W01 extraction callback returned duplicate candidates"
                )
            seen.add(candidate)
        return value

    @classmethod
    def _validate_w01_candidate(
        cls,
        candidate: MemoryCandidate,
        turn: CompletedMemoryTurn,
    ) -> None:
        cls._canonical_text(
            "candidate subject",
            candidate.subject,
            MAX_CANDIDATE_SUBJECT_CHARS,
        )
        cls._canonical_text(
            "candidate predicate",
            candidate.predicate,
            MAX_CANDIDATE_PREDICATE_CHARS,
        )
        cls._canonical_text(
            "candidate value",
            candidate.value,
            MAX_CANDIDATE_VALUE_CHARS,
        )
        cls._canonical_text(
            "candidate source_ref",
            candidate.source_ref,
            MAX_SOURCE_REF_CHARS,
        )
        if candidate.source_ref != turn.source_ref:
            raise MemoryOrchestrationError(
                "W01 candidate source_ref is not bound to the completed turn"
            )

        if not isinstance(candidate.evidence, str):
            raise MemoryOrchestrationError("W01 candidate evidence must be text")
        if (
            candidate.evidence != candidate.evidence.strip()
            or "\x00" in candidate.evidence
            or len(candidate.evidence) > MAX_CANDIDATE_EVIDENCE_CHARS
        ):
            raise MemoryOrchestrationError(
                "W01 candidate evidence is outside its hard bound"
            )
        if candidate.kind not in KINDS:
            raise MemoryOrchestrationError("W01 candidate kind is invalid")
        if candidate.sensitivity not in SENSITIVITIES:
            raise MemoryOrchestrationError("W01 candidate sensitivity is invalid")
        if candidate.sensitivity not in {"private", "secret"}:
            raise MemoryOrchestrationError(
                "W01 candidate sensitivity violates the conservative boundary"
            )
        if candidate.source_type not in SOURCE_TYPES:
            raise MemoryOrchestrationError("W01 candidate source_type is invalid")
        if candidate.review_status not in {"pending", "confirmed"}:
            raise MemoryOrchestrationError("W01 candidate review_status is invalid")

        if isinstance(candidate.confidence, bool):
            raise MemoryOrchestrationError("W01 candidate confidence must be numeric")
        try:
            confidence = float(candidate.confidence)
        except (TypeError, ValueError) as exc:
            raise MemoryOrchestrationError(
                "W01 candidate confidence must be numeric"
            ) from exc
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise MemoryOrchestrationError(
                "W01 candidate confidence is outside its hard bound"
            )

        if candidate.sensitivity == "secret" and candidate.review_status != "pending":
            raise MemoryOrchestrationError(
                "secret W01 candidate cannot carry confirmed authority"
            )

        if candidate.source_type == "user_explicit":
            if (
                not candidate.evidence
                or candidate.evidence not in turn.user_text
                or candidate.value not in candidate.evidence
            ):
                raise MemoryOrchestrationError(
                    "W01 user-explicit evidence is not bound to the completed turn"
                )

        if candidate.review_status == "confirmed":
            canonical_confirmed = (
                candidate.subject == VERBATIM_USER_SUBJECT
                and candidate.predicate == VERBATIM_USER_PREDICATE
                and candidate.kind == "note"
                and candidate.sensitivity == "private"
                and candidate.source_type == "user_explicit"
                and confidence == 1.0
                and candidate.value == candidate.evidence
                and candidate.value == turn.user_text
            )
            if not canonical_confirmed:
                raise MemoryOrchestrationError(
                    "confirmed W01 candidate violates verbatim authority"
                )

    @staticmethod
    def _canonical_text(name: str, value: Any, maximum: int) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or "\x00" in value
            or len(value) > maximum
        ):
            raise MemoryOrchestrationError(f"{name} is outside its hard bound")
        return value

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
            and candidate.value == candidate.evidence
            and candidate.value == turn.user_text
            and candidate.source_ref == turn.source_ref
        )

    @staticmethod
    def _validate_plan_binding(
        value: Any,
        eligible: tuple[MemoryCandidate, ...],
    ) -> ConsolidationPlan:
        if not isinstance(value, ConsolidationPlan):
            raise MemoryOrchestrationError("W02 plan callback returned an invalid type")
        if len(value.actions) != len(eligible):
            raise MemoryOrchestrationError(
                "W02 plan does not cover the exact eligible candidate batch"
            )
        if any(not isinstance(action, ConsolidationAction) for action in value.actions):
            raise MemoryOrchestrationError("W02 plan contains an invalid action")

        if Counter(action.candidate for action in value.actions) != Counter(eligible):
            raise MemoryOrchestrationError(
                "W02 plan candidate binding does not match the eligible batch"
            )

        counts = {name: 0 for name in ("create", "dedupe", "supersede", "skip")}
        touched: set[str] = set()
        for action in value.actions:
            if action.decision not in counts:
                raise MemoryOrchestrationError("W02 plan contains an invalid decision")
            counts[action.decision] += 1
            if action.existing_id is not None:
                touched.add(action.existing_id)

        expected_receipt = ConsolidationReceipt(
            considered_count=len(value.actions),
            create_count=counts["create"],
            dedupe_count=counts["dedupe"],
            supersede_count=counts["supersede"],
            skip_count=counts["skip"],
            touched_existing_ids=tuple(sorted(touched)),
            sent_to_store=False,
        )
        if value.receipt != expected_receipt:
            raise MemoryOrchestrationError(
                "W02 plan receipt is not bound to its actions"
            )
        return value

    @classmethod
    def _project_write_receipt(
        cls,
        value: Any,
        plan: ConsolidationPlan,
    ) -> DurableWriteReceipt:
        try:
            schema = value.schema
            considered_count = value.considered_count
            created_ids = value.created_ids
            superseded_ids = value.superseded_ids
            superseding_ids = value.superseding_ids
            deduped_ids = value.deduped_ids
            skipped_count = value.skipped_count
            replayed = value.replayed
            sent_to_store = value.sent_to_store
        except AttributeError as exc:
            raise MemoryOrchestrationError(
                "W02 apply callback returned an invalid receipt"
            ) from exc

        if schema != W02_WRITE_RECEIPT_SCHEMA:
            raise MemoryOrchestrationError("W02 write receipt schema is invalid")
        if (
            isinstance(considered_count, bool)
            or not isinstance(considered_count, int)
            or considered_count != len(plan.actions)
        ):
            raise MemoryOrchestrationError(
                "W02 write receipt considered_count is not bound to the plan"
            )
        if (
            isinstance(skipped_count, bool)
            or not isinstance(skipped_count, int)
            or skipped_count < 0
        ):
            raise MemoryOrchestrationError("W02 write receipt skipped_count is invalid")
        if not isinstance(replayed, bool) or sent_to_store is not True:
            raise MemoryOrchestrationError("W02 write receipt store state is invalid")

        projected = DurableWriteReceipt(
            schema=schema,
            considered_count=considered_count,
            created_ids=cls._validated_ids("created_ids", created_ids),
            superseded_ids=cls._validated_ids("superseded_ids", superseded_ids),
            superseding_ids=cls._validated_ids("superseding_ids", superseding_ids),
            deduped_ids=cls._validated_ids("deduped_ids", deduped_ids),
            skipped_count=skipped_count,
            replayed=replayed,
            sent_to_store=True,
        )
        cls._validate_write_receipt_binding(projected, plan)
        return projected

    @staticmethod
    def _validated_ids(name: str, value: Any) -> tuple[str, ...]:
        if not isinstance(value, tuple):
            raise MemoryOrchestrationError(f"W02 write receipt {name} must be a tuple")
        result: list[str] = []
        for item in value:
            if (
                not isinstance(item, str)
                or not item
                or item != item.strip()
                or "\x00" in item
                or len(item) > MAX_RECORD_ID_CHARS
            ):
                raise MemoryOrchestrationError(
                    f"W02 write receipt {name} contains an invalid id"
                )
            result.append(item)
        return tuple(result)

    @staticmethod
    def _validate_write_receipt_binding(
        receipt: DurableWriteReceipt,
        plan: ConsolidationPlan,
    ) -> None:
        planned = {name: 0 for name in ("create", "dedupe", "supersede", "skip")}
        for action in plan.actions:
            planned[action.decision] += 1

        if receipt.skipped_count != planned["skip"]:
            raise MemoryOrchestrationError(
                "W02 write receipt skip count is not bound to the plan"
            )
        if len(receipt.superseded_ids) != len(receipt.superseding_ids):
            raise MemoryOrchestrationError(
                "W02 write receipt supersede ids are inconsistent"
            )

        if receipt.replayed:
            if receipt.created_ids or receipt.superseded_ids or receipt.superseding_ids:
                raise MemoryOrchestrationError(
                    "replayed W02 write receipt cannot claim new mutations"
                )
            if len(receipt.deduped_ids) != (
                planned["create"] + planned["dedupe"] + planned["supersede"]
            ):
                raise MemoryOrchestrationError(
                    "replayed W02 write receipt does not cover the plan"
                )
            if len(receipt.deduped_ids) + receipt.skipped_count != receipt.considered_count:
                raise MemoryOrchestrationError(
                    "replayed W02 write receipt outcome count is not bound to the plan"
                )
            return

        if len(receipt.created_ids) != planned["create"] + planned["supersede"]:
            raise MemoryOrchestrationError(
                "W02 write receipt created ids are not bound to create/supersede actions"
            )
        if len(receipt.superseded_ids) != planned["supersede"]:
            raise MemoryOrchestrationError(
                "W02 write receipt superseded ids are not bound to the plan"
            )
        if len(receipt.superseding_ids) != planned["supersede"]:
            raise MemoryOrchestrationError(
                "W02 write receipt superseding ids are not bound to the plan"
            )
        if len(receipt.deduped_ids) != planned["dedupe"]:
            raise MemoryOrchestrationError(
                "W02 write receipt dedupe count is not bound to the plan"
            )
        if not set(receipt.superseding_ids).issubset(set(receipt.created_ids)):
            raise MemoryOrchestrationError(
                "W02 write receipt superseding ids must be part of created ids"
            )
        if set(receipt.created_ids) & set(receipt.superseded_ids):
            raise MemoryOrchestrationError(
                "W02 write receipt created/superseded ids overlap"
            )
        if set(receipt.created_ids) & set(receipt.deduped_ids):
            raise MemoryOrchestrationError(
                "W02 write receipt created/deduped ids overlap"
            )
        if set(receipt.superseded_ids) & set(receipt.deduped_ids):
            raise MemoryOrchestrationError(
                "W02 write receipt superseded/deduped ids overlap"
            )
        if (
            len(receipt.created_ids)
            + len(receipt.deduped_ids)
            + receipt.skipped_count
            != receipt.considered_count
        ):
            raise MemoryOrchestrationError(
                "W02 write receipt outcome count is not bound to the plan"
            )
