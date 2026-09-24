"""C30-J bounded process-local episode experience review mailbox.

The mailbox carries only C30-H bounded closure evidence and C30-I review plans.
It owns no durable storage, background work, Memory 4 calls, or automatic review.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_closure_evidence import (
    EpisodeClosureEvidence,
    episode_closure_evidence_ref,
)
from .episode_experience_review import (
    EpisodeExperienceReviewPlan,
    plan_episode_experience_review,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


MailboxErrorCode = Literal[
    "INVALID_CAPACITY",
    "DUPLICATE",
    "REPLAY_LEDGER_FULL",
    "CAPACITY_REACHED",
    "NOT_PENDING",
    "CLOSED",
]


class EpisodeReviewMailboxError(RuntimeError):
    def __init__(self, code: MailboxErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeExperienceReviewRequest(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-experience-review-request/v1"
    ]
    request_id: Annotated[
        str,
        Field(pattern=r"^ereq-[a-f0-9]{32}$"),
    ]
    closure_evidence: EpisodeClosureEvidence
    review_plan: EpisodeExperienceReviewPlan
    enqueued_sequence: NonNegativeInt
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    durable: Literal[False]
    memory4_called: Literal[False]
    background_work_started: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_bindings(self) -> "EpisodeExperienceReviewRequest":
        evidence_ref = episode_closure_evidence_ref(self.closure_evidence)
        if self.review_plan.closure_evidence_ref != evidence_ref:
            raise ValueError(
                "review request evidence/plan binding mismatch"
            )
        if self.review_plan.disposition != "TRUSTED_REVIEW_REQUIRED":
            raise ValueError(
                "review request requires non-empty trusted-review plan"
            )
        if self.enqueued_sequence != self.closure_evidence.closed_sequence:
            raise ValueError(
                "review request sequence must match episode closure"
            )
        return self


class EpisodeReviewMailboxReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-mailbox-receipt/v1"
    ]
    operation: Literal["ENQUEUE", "CONSUME", "CLOSE"]
    request_ref: NonEmptyRef | None
    pending_before: NonNegativeInt
    pending_after: NonNegativeInt
    seen_request_count: NonNegativeInt
    mutation_applied: bool
    durable_store_write_applied: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    background_work_started: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_counts(self) -> "EpisodeReviewMailboxReceipt":
        if self.operation == "ENQUEUE":
            if (
                self.request_ref is None
                or not self.mutation_applied
                or self.pending_after != self.pending_before + 1
            ):
                raise ValueError("invalid ENQUEUE mailbox receipt")
        elif self.operation == "CONSUME":
            if (
                self.request_ref is None
                or not self.mutation_applied
                or self.pending_after + 1 != self.pending_before
            ):
                raise ValueError("invalid CONSUME mailbox receipt")
        else:
            if self.request_ref is not None:
                raise ValueError("CLOSE mailbox receipt cannot bind a request")
            if self.pending_after != 0:
                raise ValueError("CLOSE mailbox receipt must clear pending state")
        return self


class EpisodeReviewMailboxSnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-mailbox-snapshot/v1"
    ]
    capacity: Annotated[int, Field(ge=1, le=32, strict=True)]
    pending_count: Annotated[int, Field(ge=0, le=32, strict=True)]
    pending_request_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=32),
    ]
    seen_request_count: Annotated[int, Field(ge=0, le=4096, strict=True)]
    closed: bool
    durable: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewMailboxSnapshot":
        if self.pending_count != len(self.pending_request_refs):
            raise ValueError(
                "mailbox snapshot pending accounting is inconsistent"
            )
        if self.pending_count > self.capacity:
            raise ValueError(
                "mailbox snapshot exceeds configured capacity"
            )
        return self


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def episode_experience_review_request_ref(
    request: EpisodeExperienceReviewRequest,
) -> str:
    if not isinstance(request, EpisodeExperienceReviewRequest):
        raise TypeError("request must be EpisodeExperienceReviewRequest")
    return "episode-experience-review-request:" + _digest(request)


def build_episode_experience_review_request(
    evidence: EpisodeClosureEvidence,
) -> EpisodeExperienceReviewRequest | None:
    """Create one bounded request for a non-empty closure evidence object."""
    if not isinstance(evidence, EpisodeClosureEvidence):
        raise TypeError("evidence must be EpisodeClosureEvidence")
    plan = plan_episode_experience_review(evidence)
    if plan.disposition == "NO_REVIEW":
        return None

    seed = {
        "closure_evidence_ref": plan.closure_evidence_ref,
        "closed_sequence": evidence.closed_sequence,
    }
    return EpisodeExperienceReviewRequest(
        schema=(
            "kaliv-consciousness-core/"
            "episode-experience-review-request/v1"
        ),
        request_id="ereq-" + _digest(seed)[:32],
        closure_evidence=evidence,
        review_plan=plan,
        enqueued_sequence=evidence.closed_sequence,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        durable=False,
        memory4_called=False,
        background_work_started=False,
        production_activation=False,
    )


class EpisodeExperienceReviewMailbox:
    """Small in-memory mailbox with bounded replay tombstones."""

    MAX_SEEN_REQUESTS = 4096

    def __init__(self, *, capacity: int = 8) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError("capacity must be int")
        if capacity < 1 or capacity > 32:
            raise EpisodeReviewMailboxError(
                "INVALID_CAPACITY",
                "capacity must be between 1 and 32",
            )
        self._capacity = capacity
        self._pending: dict[str, EpisodeExperienceReviewRequest] = {}
        self._seen_request_ids: set[str] = set()
        self._closed = False

    @property
    def snapshot(self) -> EpisodeReviewMailboxSnapshot:
        refs = [
            episode_experience_review_request_ref(request)
            for request in self._pending.values()
        ]
        return EpisodeReviewMailboxSnapshot(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-mailbox-snapshot/v1"
            ),
            capacity=self._capacity,
            pending_count=len(self._pending),
            pending_request_refs=refs,
            seen_request_count=len(self._seen_request_ids),
            closed=self._closed,
            durable=False,
            production_activation=False,
        )

    def pending_requests(
        self,
    ) -> tuple[EpisodeExperienceReviewRequest, ...]:
        return tuple(self._pending.values())

    def enqueue(
        self,
        request: EpisodeExperienceReviewRequest,
    ) -> EpisodeReviewMailboxReceipt:
        self._require_open()
        if not isinstance(request, EpisodeExperienceReviewRequest):
            raise TypeError(
                "request must be EpisodeExperienceReviewRequest"
            )
        if request.request_id in self._seen_request_ids:
            raise EpisodeReviewMailboxError(
                "DUPLICATE",
                "episode review request has already been admitted",
            )
        if len(self._seen_request_ids) >= self.MAX_SEEN_REQUESTS:
            raise EpisodeReviewMailboxError(
                "REPLAY_LEDGER_FULL",
                "episode review mailbox replay ledger is full",
            )
        if len(self._pending) >= self._capacity:
            raise EpisodeReviewMailboxError(
                "CAPACITY_REACHED",
                "episode review mailbox capacity reached",
            )

        before = len(self._pending)
        self._pending[request.request_id] = request
        self._seen_request_ids.add(request.request_id)
        return EpisodeReviewMailboxReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-mailbox-receipt/v1"
            ),
            operation="ENQUEUE",
            request_ref=episode_experience_review_request_ref(request),
            pending_before=before,
            pending_after=len(self._pending),
            seen_request_count=len(self._seen_request_ids),
            mutation_applied=True,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            background_work_started=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    def consume(
        self,
        request_id: str,
    ) -> tuple[
        EpisodeExperienceReviewRequest,
        EpisodeReviewMailboxReceipt,
    ]:
        self._require_open()
        if request_id not in self._pending:
            raise EpisodeReviewMailboxError(
                "NOT_PENDING",
                "episode review request is not pending",
            )

        before = len(self._pending)
        request = self._pending.pop(request_id)
        receipt = EpisodeReviewMailboxReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-mailbox-receipt/v1"
            ),
            operation="CONSUME",
            request_ref=episode_experience_review_request_ref(request),
            pending_before=before,
            pending_after=len(self._pending),
            seen_request_count=len(self._seen_request_ids),
            mutation_applied=True,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            background_work_started=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )
        return request, receipt

    def close(self) -> EpisodeReviewMailboxReceipt:
        before = len(self._pending)
        self._pending.clear()
        self._seen_request_ids.clear()
        self._closed = True
        return EpisodeReviewMailboxReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-mailbox-receipt/v1"
            ),
            operation="CLOSE",
            request_ref=None,
            pending_before=before,
            pending_after=0,
            seen_request_count=0,
            mutation_applied=before > 0,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            background_work_started=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise EpisodeReviewMailboxError(
                "CLOSED",
                "episode review mailbox is closed",
            )
