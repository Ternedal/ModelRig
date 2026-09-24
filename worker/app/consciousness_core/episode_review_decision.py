"""C30-M exact decision application for consumed episode review requests.

This process-local primitive binds one C30-L consume receipt to one explicit
C30-I trusted review and, for APPROVE, one real C7 ExperienceCandidate. It does
not persist the result or call Memory 4.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_experience_review import (
    EpisodeExperienceCandidateEvaluation,
    TrustedEpisodeExperienceReview,
    evaluate_reviewed_episode_candidate,
    trusted_episode_experience_review_ref,
)
from .episode_review_adapter import EpisodeReviewAdapterConsumeReceipt
from .episode_review_mailbox import (
    EpisodeExperienceReviewRequest,
    episode_experience_review_request_ref,
)
from .experience import ExperienceCandidate


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


class EpisodeReviewDecisionError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewDecisionReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-decision-receipt/v1"
    ]
    application_id: Annotated[
        str,
        Field(pattern=r"^edec-[a-f0-9]{32}$"),
    ]
    request_ref: NonEmptyRef
    closure_evidence_ref: NonEmptyRef
    review_ref: NonEmptyRef
    decision: Literal["APPROVE", "REJECT"]
    evaluation: EpisodeExperienceCandidateEvaluation
    exact_consume_binding: Literal[True]
    semantic_review_applied: Literal[True]
    durable: Literal[False]
    memory4_called: Literal[False]
    durable_memory_write_authority: Literal[False]
    model_calls: Literal[0]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewDecisionReceipt":
        if self.evaluation.closure_evidence_ref != self.closure_evidence_ref:
            raise ValueError("decision/evaluation closure binding mismatch")
        if self.evaluation.review_ref != self.review_ref:
            raise ValueError("decision/evaluation review binding mismatch")
        expected = self.decision == "APPROVE"
        if self.evaluation.accepted_for_c7_evaluation != expected:
            raise ValueError("decision/evaluation outcome mismatch")
        return self


class EpisodeReviewDecisionSnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-decision-snapshot/v1"
    ]
    applied_count: Annotated[int, Field(ge=0, le=4096, strict=True)]
    closed: bool
    durable: Literal[False]
    memory4_called: Literal[False]
    production_activation: Literal[False]


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


class TrustedEpisodeReviewDecisionApplier:
    """Bounded exact-once process-local semantic review application."""

    MAX_APPLIED_REQUESTS = 4096

    def __init__(self) -> None:
        self._applied_request_refs: set[str] = set()
        self._closed = False

    @property
    def snapshot(self) -> EpisodeReviewDecisionSnapshot:
        return EpisodeReviewDecisionSnapshot(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-decision-snapshot/v1"
            ),
            applied_count=len(self._applied_request_refs),
            closed=self._closed,
            durable=False,
            memory4_called=False,
            production_activation=False,
        )

    def apply(
        self,
        *,
        request: EpisodeExperienceReviewRequest,
        consume_receipt: EpisodeReviewAdapterConsumeReceipt,
        review: TrustedEpisodeExperienceReview,
        candidate: ExperienceCandidate | None = None,
    ) -> EpisodeReviewDecisionReceipt:
        self._require_open()
        if not isinstance(request, EpisodeExperienceReviewRequest):
            raise TypeError("request must be EpisodeExperienceReviewRequest")
        if not isinstance(
            consume_receipt,
            EpisodeReviewAdapterConsumeReceipt,
        ):
            raise TypeError(
                "consume_receipt must be EpisodeReviewAdapterConsumeReceipt"
            )
        if not isinstance(review, TrustedEpisodeExperienceReview):
            raise TypeError("review must be TrustedEpisodeExperienceReview")
        if candidate is not None and not isinstance(
            candidate,
            ExperienceCandidate,
        ):
            raise TypeError(
                "candidate must be ExperienceCandidate or None"
            )

        request_ref = episode_experience_review_request_ref(request)
        if consume_receipt.request_id != request.request_id:
            raise EpisodeReviewDecisionError(
                "consume receipt belongs to another review request"
            )
        if consume_receipt.request_ref != request_ref:
            raise EpisodeReviewDecisionError(
                "consume receipt request ref mismatch"
            )
        if (
            consume_receipt.closure_evidence_ref
            != request.review_plan.closure_evidence_ref
        ):
            raise EpisodeReviewDecisionError(
                "consume receipt closure evidence mismatch"
            )
        if review.closure_evidence_ref != request.review_plan.closure_evidence_ref:
            raise EpisodeReviewDecisionError(
                "trusted review belongs to another closure evidence object"
            )
        if request_ref in self._applied_request_refs:
            raise EpisodeReviewDecisionError(
                "episode review decision has already been applied"
            )
        if len(self._applied_request_refs) >= self.MAX_APPLIED_REQUESTS:
            raise EpisodeReviewDecisionError(
                "episode review decision replay ledger is full"
            )

        if review.decision == "REJECT" and candidate is not None:
            raise EpisodeReviewDecisionError(
                "REJECT decision cannot carry an ExperienceCandidate"
            )
        if review.decision == "APPROVE" and candidate is None:
            raise EpisodeReviewDecisionError(
                "APPROVE decision requires an ExperienceCandidate"
            )

        evaluation = evaluate_reviewed_episode_candidate(
            request.closure_evidence,
            review,
            candidate,
        )
        review_ref = trusted_episode_experience_review_ref(review)
        seed = {
            "request_ref": request_ref,
            "review_ref": review_ref,
        }

        receipt = EpisodeReviewDecisionReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-decision-receipt/v1"
            ),
            application_id="edec-" + _digest(seed)[:32],
            request_ref=request_ref,
            closure_evidence_ref=request.review_plan.closure_evidence_ref,
            review_ref=review_ref,
            decision=review.decision,
            evaluation=evaluation,
            exact_consume_binding=True,
            semantic_review_applied=True,
            durable=False,
            memory4_called=False,
            durable_memory_write_authority=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

        self._applied_request_refs.add(request_ref)
        return receipt

    def close(self) -> None:
        self._applied_request_refs.clear()
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise EpisodeReviewDecisionError(
                "episode review decision applier is closed"
            )
