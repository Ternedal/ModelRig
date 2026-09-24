"""C30-L trusted in-process review adapter over the C30-J mailbox.

The adapter exposes bounded reference-level review metadata and exact one-shot
consume. It is not a route, authentication boundary, durable queue, reviewer,
Memory 4 bridge, or model surface.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_review_mailbox import (
    EpisodeExperienceReviewMailbox,
    EpisodeExperienceReviewRequest,
    EpisodeReviewMailboxError,
    EpisodeReviewMailboxReceipt,
    episode_experience_review_request_ref,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


class EpisodeReviewAdapterError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewAdapterItem(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-adapter-item/v1"
    ]
    request_id: Annotated[str, Field(pattern=r"^ereq-[a-f0-9]{32}$")]
    request_ref: NonEmptyRef
    closure_evidence_ref: NonEmptyRef
    closed_episode_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    open_reason: NonEmptyRef
    close_reason: NonEmptyRef
    opened_sequence: NonNegativeInt
    closed_sequence: NonNegativeInt
    objective_elapsed_ms: NonNegativeInt
    total_moment_count: Annotated[int, Field(ge=1, strict=True)]
    retained_moment_count: Annotated[int, Field(ge=1, le=128, strict=True)]
    evicted_moment_count: Annotated[int, Field(ge=0, strict=True)]
    salient_source_refs: Annotated[list[NonEmptyRef], Field(max_length=16)]
    participant_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    active_goal_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    max_retained_salience: Annotated[float, Field(ge=0.0, le=1.0)]
    semantic_review_required: Literal[True]
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    durable: Literal[False]
    memory4_called: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_counts(self) -> "EpisodeReviewAdapterItem":
        if (
            self.retained_moment_count + self.evicted_moment_count
            != self.total_moment_count
        ):
            raise ValueError("episode review adapter moment accounting is invalid")
        if self.closed_sequence < self.opened_sequence:
            raise ValueError("episode review adapter sequence range is invalid")
        return self


class EpisodeReviewAdapterSnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-adapter-snapshot/v1"
    ]
    pending_count: Annotated[int, Field(ge=0, le=32, strict=True)]
    returned_count: Annotated[int, Field(ge=0, le=32, strict=True)]
    items: Annotated[list[EpisodeReviewAdapterItem], Field(max_length=32)]
    truncated: bool
    durable: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewAdapterSnapshot":
        if self.returned_count != len(self.items):
            raise ValueError("review adapter returned-count mismatch")
        if self.returned_count > self.pending_count:
            raise ValueError("review adapter returned more than pending")
        if self.truncated != (self.returned_count < self.pending_count):
            raise ValueError("review adapter truncation flag mismatch")
        return self


class EpisodeReviewAdapterConsumeReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-adapter-consume-receipt/v1"
    ]
    request_id: Annotated[str, Field(pattern=r"^ereq-[a-f0-9]{32}$")]
    request_ref: NonEmptyRef
    closure_evidence_ref: NonEmptyRef
    mailbox_receipt: EpisodeReviewMailboxReceipt
    exact_ref_match: Literal[True]
    one_shot_consumed: Literal[True]
    reviewer_decision_applied: Literal[False]
    candidate_created: Literal[False]
    memory4_called: Literal[False]
    durable_store_write_applied: Literal[False]
    model_calls: Literal[0]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_receipt(self) -> "EpisodeReviewAdapterConsumeReceipt":
        if self.mailbox_receipt.operation != "CONSUME":
            raise ValueError("adapter consume receipt requires mailbox CONSUME")
        if self.mailbox_receipt.request_ref != self.request_ref:
            raise ValueError("adapter/mailbox request ref mismatch")
        return self


def _adapter_item(
    request: EpisodeExperienceReviewRequest,
) -> EpisodeReviewAdapterItem:
    evidence = request.closure_evidence
    return EpisodeReviewAdapterItem(
        schema="kaliv-consciousness-core/episode-review-adapter-item/v1",
        request_id=request.request_id,
        request_ref=episode_experience_review_request_ref(request),
        closure_evidence_ref=request.review_plan.closure_evidence_ref,
        closed_episode_ref=evidence.closed_episode_ref,
        self_id=evidence.self_id,
        person_revision=evidence.person_revision,
        open_reason=evidence.open_reason,
        close_reason=evidence.close_reason,
        opened_sequence=evidence.opened_sequence,
        closed_sequence=evidence.closed_sequence,
        objective_elapsed_ms=evidence.objective_elapsed_ms,
        total_moment_count=evidence.total_moment_count,
        retained_moment_count=evidence.retained_moment_count,
        evicted_moment_count=evidence.evicted_moment_count,
        salient_source_refs=list(evidence.salient_source_refs),
        participant_refs=list(evidence.participant_refs),
        active_goal_refs=list(evidence.active_goal_refs),
        max_retained_salience=evidence.max_retained_salience,
        semantic_review_required=True,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        durable=False,
        memory4_called=False,
        production_activation=False,
    )


class TrustedEpisodeReviewAdapter:
    """Bounded process-local UI/operator adapter over one mailbox."""

    def __init__(
        self,
        *,
        mailbox: EpisodeExperienceReviewMailbox,
    ) -> None:
        if not isinstance(mailbox, EpisodeExperienceReviewMailbox):
            raise TypeError("mailbox must be EpisodeExperienceReviewMailbox")
        self._mailbox = mailbox

    def list_pending(
        self,
        *,
        limit: int = 8,
    ) -> EpisodeReviewAdapterSnapshot:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be int")
        if limit < 1 or limit > 32:
            raise EpisodeReviewAdapterError(
                "limit must be between 1 and 32"
            )

        requests = self._mailbox.pending_requests()
        selected = requests[:limit]
        return EpisodeReviewAdapterSnapshot(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-adapter-snapshot/v1"
            ),
            pending_count=len(requests),
            returned_count=len(selected),
            items=[_adapter_item(request) for request in selected],
            truncated=len(selected) < len(requests),
            durable=False,
            memory4_called=False,
            model_calls=0,
            production_activation=False,
        )

    def consume_exact(
        self,
        *,
        request_id: str,
        expected_request_ref: str,
    ) -> tuple[
        EpisodeExperienceReviewRequest,
        EpisodeReviewAdapterConsumeReceipt,
    ]:
        if (
            not isinstance(request_id, str)
            or not request_id.startswith("ereq-")
            or len(request_id) != len("ereq-") + 32
        ):
            raise EpisodeReviewAdapterError("invalid episode review request id")
        if not isinstance(expected_request_ref, str) or not expected_request_ref:
            raise EpisodeReviewAdapterError("expected_request_ref is required")

        match = None
        for request in self._mailbox.pending_requests():
            if request.request_id == request_id:
                match = request
                break

        if match is None:
            raise EpisodeReviewAdapterError(
                "episode review request is not pending"
            )

        actual_ref = episode_experience_review_request_ref(match)
        if actual_ref != expected_request_ref:
            raise EpisodeReviewAdapterError(
                "episode review request ref mismatch"
            )

        try:
            consumed, mailbox_receipt = self._mailbox.consume(request_id)
        except EpisodeReviewMailboxError as exc:
            raise EpisodeReviewAdapterError(str(exc)) from exc

        consumed_ref = episode_experience_review_request_ref(consumed)
        if consumed_ref != actual_ref:
            raise EpisodeReviewAdapterError(
                "mailbox returned unexpected episode review request"
            )

        receipt = EpisodeReviewAdapterConsumeReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-adapter-consume-receipt/v1"
            ),
            request_id=consumed.request_id,
            request_ref=consumed_ref,
            closure_evidence_ref=(
                consumed.review_plan.closure_evidence_ref
            ),
            mailbox_receipt=mailbox_receipt,
            exact_ref_match=True,
            one_shot_consumed=True,
            reviewer_decision_applied=False,
            candidate_created=False,
            memory4_called=False,
            durable_store_write_applied=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )
        return consumed, receipt
