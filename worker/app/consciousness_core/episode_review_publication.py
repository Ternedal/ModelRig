"""C30-K non-blocking publication of closure review requests into C30-J.

Publication is advisory and process-local. Episode boundary application remains
authoritative and must not fail because the optional review mailbox is absent,
closed, full, or has already seen the request.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_closure_evidence import (
    EpisodeClosureEvidence,
    episode_closure_evidence_ref,
)
from .episode_review_mailbox import (
    EpisodeExperienceReviewMailbox,
    EpisodeReviewMailboxError,
    EpisodeReviewMailboxReceipt,
    build_episode_experience_review_request,
    episode_experience_review_request_ref,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
PublicationStatus = Literal[
    "NOT_APPLICABLE",
    "MAILBOX_UNAVAILABLE",
    "NO_REVIEW",
    "ENQUEUED",
    "DUPLICATE",
    "CAPACITY_REACHED",
    "MAILBOX_CLOSED",
    "REPLAY_LEDGER_FULL",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewPublicationReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-publication-receipt/v1"
    ]
    status: PublicationStatus
    closure_evidence_ref: NonEmptyRef | None
    request_ref: NonEmptyRef | None
    mailbox_receipt: EpisodeReviewMailboxReceipt | None
    boundary_result_preserved: Literal[True]
    retry_scheduled: Literal[False]
    durable_store_write_applied: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewPublicationReceipt":
        if self.status == "NOT_APPLICABLE":
            if (
                self.closure_evidence_ref is not None
                or self.request_ref is not None
                or self.mailbox_receipt is not None
            ):
                raise ValueError("NOT_APPLICABLE publication shape is invalid")
        elif self.status == "MAILBOX_UNAVAILABLE":
            if (
                self.closure_evidence_ref is None
                or self.request_ref is not None
                or self.mailbox_receipt is not None
            ):
                raise ValueError("MAILBOX_UNAVAILABLE publication shape is invalid")
        elif self.status == "NO_REVIEW":
            if (
                self.closure_evidence_ref is None
                or self.request_ref is not None
                or self.mailbox_receipt is not None
            ):
                raise ValueError("NO_REVIEW publication shape is invalid")
        elif self.status == "ENQUEUED":
            if (
                self.closure_evidence_ref is None
                or self.request_ref is None
                or self.mailbox_receipt is None
                or self.mailbox_receipt.operation != "ENQUEUE"
            ):
                raise ValueError("ENQUEUED publication shape is invalid")
        else:
            if (
                self.closure_evidence_ref is None
                or self.request_ref is None
                or self.mailbox_receipt is not None
            ):
                raise ValueError("failed publication shape is invalid")
        return self


def publish_episode_closure_review(
    evidence: EpisodeClosureEvidence | None,
    mailbox: EpisodeExperienceReviewMailbox | None,
) -> EpisodeReviewPublicationReceipt:
    """Best-effort publication that never mutates durable state or schedules retry."""
    if evidence is None:
        return EpisodeReviewPublicationReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-publication-receipt/v1"
            ),
            status="NOT_APPLICABLE",
            closure_evidence_ref=None,
            request_ref=None,
            mailbox_receipt=None,
            boundary_result_preserved=True,
            retry_scheduled=False,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    evidence_ref = episode_closure_evidence_ref(evidence)
    if mailbox is None:
        return EpisodeReviewPublicationReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-publication-receipt/v1"
            ),
            status="MAILBOX_UNAVAILABLE",
            closure_evidence_ref=evidence_ref,
            request_ref=None,
            mailbox_receipt=None,
            boundary_result_preserved=True,
            retry_scheduled=False,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    if not isinstance(mailbox, EpisodeExperienceReviewMailbox):
        raise TypeError("mailbox must be EpisodeExperienceReviewMailbox or None")

    request = build_episode_experience_review_request(evidence)
    if request is None:
        return EpisodeReviewPublicationReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-publication-receipt/v1"
            ),
            status="NO_REVIEW",
            closure_evidence_ref=evidence_ref,
            request_ref=None,
            mailbox_receipt=None,
            boundary_result_preserved=True,
            retry_scheduled=False,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    request_ref = episode_experience_review_request_ref(request)
    try:
        receipt = mailbox.enqueue(request)
    except EpisodeReviewMailboxError as exc:
        status_by_code = {
            "DUPLICATE": "DUPLICATE",
            "CAPACITY_REACHED": "CAPACITY_REACHED",
            "CLOSED": "MAILBOX_CLOSED",
            "REPLAY_LEDGER_FULL": "REPLAY_LEDGER_FULL",
        }
        status = status_by_code.get(exc.code)
        if status is None:
            raise
        return EpisodeReviewPublicationReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-publication-receipt/v1"
            ),
            status=status,
            closure_evidence_ref=evidence_ref,
            request_ref=request_ref,
            mailbox_receipt=None,
            boundary_result_preserved=True,
            retry_scheduled=False,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    return EpisodeReviewPublicationReceipt(
        schema=(
            "kaliv-consciousness-core/"
            "episode-review-publication-receipt/v1"
        ),
        status="ENQUEUED",
        closure_evidence_ref=evidence_ref,
        request_ref=request_ref,
        mailbox_receipt=receipt,
        boundary_result_preserved=True,
        retry_scheduled=False,
        durable_store_write_applied=False,
        memory4_called=False,
        model_calls=0,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )
