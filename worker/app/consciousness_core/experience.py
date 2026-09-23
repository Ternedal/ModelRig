"""C7 ExperienceCandidate and Memory 4 authority bridge.

Consciousness Core owns non-durable experience candidates. Memory 4 remains the
only durable autobiographical-memory authority. Structured Core/model inference
is never rewritten into fake user text for persistence.
"""
from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..memory.context_service import (
    MAX_TURN_CONTEXT_CHARS,
    ContextForTurnRequest,
    ContextForTurnResult,
)
from ..memory.extraction import CompletedMemoryTurn
from ..memory.write_service import CompletedTurnWriteReceipt


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]

ExperienceKind = Literal[
    "USER_STATED_FACT",
    "SHARED_EVENT",
    "SELF_ACTION_OUTCOME",
    "PREDICTION_ERROR",
    "RELATIONSHIP_EVENT",
    "PROJECT_PROGRESS",
    "PREFERENCE_EVIDENCE",
    "PERSONALITY_EVIDENCE",
    "UNRESOLVED_QUESTION",
    "EXPERIENTIAL_EPISODE",
]
ExperienceProvenance = Literal[
    "user_explicit",
    "tool_observation",
    "embodiment_observation",
    "shared_event",
    "inferred",
    "core_episode",
]
Sensitivity = Literal["public", "operational", "private", "secret"]


class ExperienceMemoryError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ExperienceCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/experience-candidate/v1"]
    experience_id: Annotated[str, Field(pattern=r"^exp-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    kind: ExperienceKind
    event_ref: NonEmptyRef
    participant_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    self_state_before_ref: NonEmptyRef
    self_state_after_ref: NonEmptyRef
    active_goal_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    intention_ref: NonEmptyRef | None
    prediction_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    outcome_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    prediction_error_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    personality_state_ref: NonEmptyRef | None
    world_state_delta_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    significance: UnitInterval
    provenance_kind: ExperienceProvenance
    sensitivity: Sensitivity
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=64)]
    completed_turn_source_ref: Annotated[
        str | None,
        Field(min_length=1, max_length=1000),
    ] = None
    production_activation: Literal[False]


class MemoryContextSnapshot(StrictModel):
    schema: Literal["kaliv-consciousness-core/memory-context-snapshot/v1"]
    target: Literal["local", "cloud"]
    context: Annotated[str, Field(max_length=MAX_TURN_CONTEXT_CHARS)]
    included_ids: Annotated[list[NonEmptyRef], Field(max_length=50)]
    context_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    character_count: Annotated[int, Field(ge=0, strict=True)]
    byte_count: Annotated[int, Field(ge=0, strict=True)]
    authority: Literal["reference_data"]
    sent_to_model: Literal[False]
    source_ref: NonEmptyRef
    production_activation: Literal[False]


class MemoryHandoffDecision(StrictModel):
    schema: Literal["kaliv-consciousness-core/memory-handoff-decision/v1"]
    experience_ref: NonEmptyRef
    status: Literal[
        "completed_turn_authority",
        "trusted_review_required",
        "blocked_secret",
    ]
    reason: BoundedText
    production_activation: Literal[False]


class MemoryDurableReceiptRef(StrictModel):
    schema: Literal["kaliv-consciousness-core/memory-durable-receipt-ref/v1"]
    experience_ref: NonEmptyRef
    memory_receipt_schema: NonEmptyRef
    candidate_count: Annotated[int, Field(ge=0, strict=True)]
    considered_count: Annotated[int, Field(ge=0, strict=True)]
    created_ids: Annotated[list[NonEmptyRef], Field(max_length=16)]
    superseded_ids: Annotated[list[NonEmptyRef], Field(max_length=16)]
    deduped_ids: Annotated[list[NonEmptyRef], Field(max_length=16)]
    skipped_count: Annotated[int, Field(ge=0, strict=True)]
    replayed: bool
    sent_to_store: bool
    production_activation: Literal[False]


def _validate_experience(
    candidate: ExperienceCandidate | Mapping[str, Any],
) -> ExperienceCandidate:
    try:
        return (
            candidate
            if isinstance(candidate, ExperienceCandidate)
            else ExperienceCandidate.model_validate(candidate)
        )
    except ValidationError as exc:
        raise ExperienceMemoryError("invalid ExperienceCandidate") from exc


def plan_memory_handoff(
    candidate: ExperienceCandidate | Mapping[str, Any],
) -> MemoryHandoffDecision:
    item = _validate_experience(candidate)
    ref = f"experience:{item.experience_id}"

    if item.sensitivity == "secret":
        return MemoryHandoffDecision(
            schema="kaliv-consciousness-core/memory-handoff-decision/v1",
            experience_ref=ref,
            status="blocked_secret",
            reason="secret experience cannot auto-persist through Consciousness Core",
            production_activation=False,
        )

    if (
        item.kind == "USER_STATED_FACT"
        and item.provenance_kind == "user_explicit"
        and item.completed_turn_source_ref is not None
    ):
        return MemoryHandoffDecision(
            schema="kaliv-consciousness-core/memory-handoff-decision/v1",
            experience_ref=ref,
            status="completed_turn_authority",
            reason=(
                "submit the original bounded completed turn to existing Memory 4 "
                "W01/W02 authority; do not persist ExperienceCandidate semantics"
            ),
            production_activation=False,
        )

    return MemoryHandoffDecision(
        schema="kaliv-consciousness-core/memory-handoff-decision/v1",
        experience_ref=ref,
        status="trusted_review_required",
        reason=(
            "structured Core/model meaning has no automatic durable-memory "
            "authority and requires a separate trusted review boundary"
        ),
        production_activation=False,
    )


class Memory4ExperienceBridge:
    """Injected adapter over existing Memory 4 services; owns no storage."""

    def __init__(self, *, context_service: Any = None, write_service: Any = None) -> None:
        if context_service is not None and not callable(
            getattr(context_service, "context_for_turn", None)
        ):
            raise ExperienceMemoryError("Memory 4 context service is invalid")
        if write_service is not None and not callable(
            getattr(write_service, "commit_completed_turn", None)
        ):
            raise ExperienceMemoryError("Memory 4 write service is invalid")
        self._context_service = context_service
        self._write_service = write_service

    async def recall(
        self,
        *,
        query: str,
        target: Literal["local", "cloud"] = "local",
        subjects: tuple[str, ...] = (),
        max_results: int = 12,
        max_context_chars: int = MAX_TURN_CONTEXT_CHARS,
    ) -> MemoryContextSnapshot:
        if self._context_service is None:
            raise ExperienceMemoryError("Memory 4 context service is unavailable")

        result = await self._context_service.context_for_turn(
            ContextForTurnRequest(
                query=query,
                target=target,
                subjects=subjects,
                max_results=max_results,
                max_context_chars=max_context_chars,
            )
        )
        if not isinstance(result, ContextForTurnResult):
            raise ExperienceMemoryError("Memory 4 returned invalid context result")

        context_bytes = result.context.encode("utf-8")
        receipt = result.receipt
        digest = hashlib.sha256(context_bytes).hexdigest()
        if receipt.context_sha256 != digest:
            raise ExperienceMemoryError("Memory 4 context receipt hash mismatch")
        if receipt.character_count != len(result.context):
            raise ExperienceMemoryError("Memory 4 context character count mismatch")
        if receipt.byte_count != len(context_bytes):
            raise ExperienceMemoryError("Memory 4 context byte count mismatch")
        if receipt.sent_to_model is not False:
            raise ExperienceMemoryError(
                "Memory 4 recall must arrive as unsent reference data"
            )

        return MemoryContextSnapshot(
            schema="kaliv-consciousness-core/memory-context-snapshot/v1",
            target=receipt.target,
            context=result.context,
            included_ids=list(receipt.included_ids),
            context_sha256=receipt.context_sha256,
            character_count=receipt.character_count,
            byte_count=receipt.byte_count,
            authority="reference_data",
            sent_to_model=False,
            source_ref=f"memory4-context:{receipt.context_sha256}",
            production_activation=False,
        )

    async def submit_completed_turn(
        self,
        candidate: ExperienceCandidate | Mapping[str, Any],
        turn: CompletedMemoryTurn,
    ) -> MemoryDurableReceiptRef:
        """Use existing Memory 4 W01/W02 authority; never write candidate semantics."""
        item = _validate_experience(candidate)
        decision = plan_memory_handoff(item)
        if decision.status != "completed_turn_authority":
            raise ExperienceMemoryError(
                "ExperienceCandidate has no automatic completed-turn write authority"
            )
        if self._write_service is None:
            raise ExperienceMemoryError("Memory 4 write service is unavailable")
        if not isinstance(turn, CompletedMemoryTurn):
            raise ExperienceMemoryError("CompletedMemoryTurn is required")
        if turn.source_ref != item.completed_turn_source_ref:
            raise ExperienceMemoryError(
                "completed turn source_ref does not match ExperienceCandidate binding"
            )

        receipt = await self._write_service.commit_completed_turn(turn)
        if not isinstance(receipt, CompletedTurnWriteReceipt):
            raise ExperienceMemoryError("Memory 4 returned invalid durable receipt")

        return MemoryDurableReceiptRef(
            schema="kaliv-consciousness-core/memory-durable-receipt-ref/v1",
            experience_ref=f"experience:{item.experience_id}",
            memory_receipt_schema=receipt.schema,
            candidate_count=receipt.candidate_count,
            considered_count=receipt.considered_count,
            created_ids=list(receipt.created_ids),
            superseded_ids=list(receipt.superseded_ids),
            deduped_ids=list(receipt.deduped_ids),
            skipped_count=receipt.skipped_count,
            replayed=receipt.replayed,
            sent_to_store=receipt.sent_to_store,
            production_activation=False,
        )
