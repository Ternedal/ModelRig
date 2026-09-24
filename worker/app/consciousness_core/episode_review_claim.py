"""C30-N claim/commit service for trusted episode review workflows.

Claims are process-local reservations only. They keep the C30-J request pending
until an explicit semantic decision has passed C30-I preflight. No durable queue,
timer, background worker, Memory 4 call, or public route is introduced.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_experience_review import (
    TrustedEpisodeExperienceReview,
    evaluate_reviewed_episode_candidate,
)
from .episode_review_adapter import (
    EpisodeReviewAdapterError,
    TrustedEpisodeReviewAdapter,
)
from .episode_review_decision import (
    EpisodeReviewDecisionReceipt,
    TrustedEpisodeReviewDecisionApplier,
)
from .episode_review_mailbox import (
    EpisodeExperienceReviewMailbox,
    EpisodeExperienceReviewRequest,
    episode_experience_review_request_ref,
)
from .experience import ExperienceCandidate


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


class EpisodeReviewClaimError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewClaim(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-claim/v1"
    ]
    claim_id: Annotated[
        str,
        Field(pattern=r"^eclaim-[a-f0-9]{32}$"),
    ]
    request_id: Annotated[str, Field(pattern=r"^ereq-[a-f0-9]{32}$")]
    request_ref: NonEmptyRef
    closure_evidence_ref: NonEmptyRef
    claimed: Literal[True]
    request_consumed: Literal[False]
    durable: Literal[False]
    automatic_expiry: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]


class EpisodeReviewClaimSnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-claim-snapshot/v1"
    ]
    claimed_count: Annotated[int, Field(ge=0, le=32, strict=True)]
    claim_ids: Annotated[list[NonEmptyRef], Field(max_length=32)]
    closed: bool
    durable: Literal[False]
    automatic_expiry: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewClaimSnapshot":
        if self.claimed_count != len(self.claim_ids):
            raise ValueError("review claim snapshot count mismatch")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("review claim ids must be unique")
        return self


class EpisodeReviewClaimAbandonReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-claim-abandon/v1"
    ]
    claim_id: NonEmptyRef
    request_ref: NonEmptyRef
    request_still_pending: Literal[True]
    claim_removed: Literal[True]
    durable_store_write_applied: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]


class EpisodeReviewClaimCommitReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-claim-commit/v1"
    ]
    claim_id: NonEmptyRef
    request_ref: NonEmptyRef
    semantic_preflight_passed: Literal[True]
    request_consumed_after_preflight: Literal[True]
    decision_receipt: EpisodeReviewDecisionReceipt
    claim_removed: Literal[True]
    durable_store_write_applied: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_binding(self) -> "EpisodeReviewClaimCommitReceipt":
        if self.decision_receipt.request_ref != self.request_ref:
            raise ValueError("claim commit/decision request ref mismatch")
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


class TrustedEpisodeReviewClaimService:
    """Process-local claim -> semantic preflight -> consume -> decision service."""

    MAX_ACTIVE_CLAIMS = 32

    def __init__(
        self,
        *,
        mailbox: EpisodeExperienceReviewMailbox,
    ) -> None:
        if not isinstance(mailbox, EpisodeExperienceReviewMailbox):
            raise TypeError("mailbox must be EpisodeExperienceReviewMailbox")
        self._mailbox = mailbox
        self._adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)
        self._decision_applier = TrustedEpisodeReviewDecisionApplier()
        self._claims: dict[str, EpisodeReviewClaim] = {}
        self._closed = False

    @property
    def snapshot(self) -> EpisodeReviewClaimSnapshot:
        claims = list(self._claims.values())
        return EpisodeReviewClaimSnapshot(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-claim-snapshot/v1"
            ),
            claimed_count=len(claims),
            claim_ids=[claim.claim_id for claim in claims],
            closed=self._closed,
            durable=False,
            automatic_expiry=False,
            production_activation=False,
        )

    def claim_exact(
        self,
        *,
        request_id: str,
        expected_request_ref: str,
    ) -> tuple[EpisodeExperienceReviewRequest, EpisodeReviewClaim]:
        self._require_open()
        request = self._find_pending(request_id)
        request_ref = episode_experience_review_request_ref(request)
        if request_ref != expected_request_ref:
            raise EpisodeReviewClaimError(
                "episode review request ref mismatch"
            )
        if request_ref in self._claims:
            raise EpisodeReviewClaimError(
                "episode review request is already claimed"
            )
        if len(self._claims) >= self.MAX_ACTIVE_CLAIMS:
            raise EpisodeReviewClaimError(
                "episode review claim capacity reached"
            )

        seed = {
            "request_ref": request_ref,
            "closure_evidence_ref": (
                request.review_plan.closure_evidence_ref
            ),
        }
        claim = EpisodeReviewClaim(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-claim/v1"
            ),
            claim_id="eclaim-" + _digest(seed)[:32],
            request_id=request.request_id,
            request_ref=request_ref,
            closure_evidence_ref=request.review_plan.closure_evidence_ref,
            claimed=True,
            request_consumed=False,
            durable=False,
            automatic_expiry=False,
            timer_authority=False,
            production_activation=False,
        )
        self._claims[request_ref] = claim
        return request, claim

    def abandon(
        self,
        *,
        claim_id: str,
        expected_request_ref: str,
    ) -> EpisodeReviewClaimAbandonReceipt:
        self._require_open()
        request_ref, claim = self._find_claim(claim_id)
        if request_ref != expected_request_ref:
            raise EpisodeReviewClaimError(
                "episode review claim request ref mismatch"
            )
        request = self._find_pending(claim.request_id)
        if episode_experience_review_request_ref(request) != request_ref:
            raise EpisodeReviewClaimError(
                "pending request changed while claimed"
            )

        del self._claims[request_ref]
        return EpisodeReviewClaimAbandonReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-claim-abandon/v1"
            ),
            claim_id=claim.claim_id,
            request_ref=request_ref,
            request_still_pending=True,
            claim_removed=True,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    def commit_decision(
        self,
        *,
        claim_id: str,
        expected_request_ref: str,
        review: TrustedEpisodeExperienceReview,
        candidate: ExperienceCandidate | None = None,
    ) -> EpisodeReviewClaimCommitReceipt:
        self._require_open()
        request_ref, claim = self._find_claim(claim_id)
        if request_ref != expected_request_ref:
            raise EpisodeReviewClaimError(
                "episode review claim request ref mismatch"
            )
        request = self._find_pending(claim.request_id)
        if episode_experience_review_request_ref(request) != request_ref:
            raise EpisodeReviewClaimError(
                "pending request changed while claimed"
            )
        if review.closure_evidence_ref != claim.closure_evidence_ref:
            raise EpisodeReviewClaimError(
                "trusted review belongs to another claimed closure"
            )

        # Pure semantic preflight happens while the request is still pending.
        # Invalid review/candidate input therefore cannot lose the mailbox item.
        evaluate_reviewed_episode_candidate(
            request.closure_evidence,
            review,
            candidate,
        )

        try:
            consumed, consume_receipt = self._adapter.consume_exact(
                request_id=claim.request_id,
                expected_request_ref=request_ref,
            )
        except EpisodeReviewAdapterError as exc:
            raise EpisodeReviewClaimError(str(exc)) from exc

        decision_receipt = self._decision_applier.apply(
            request=consumed,
            consume_receipt=consume_receipt,
            review=review,
            candidate=candidate,
        )

        del self._claims[request_ref]
        return EpisodeReviewClaimCommitReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-claim-commit/v1"
            ),
            claim_id=claim.claim_id,
            request_ref=request_ref,
            semantic_preflight_passed=True,
            request_consumed_after_preflight=True,
            decision_receipt=decision_receipt,
            claim_removed=True,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    def close(self) -> None:
        self._claims.clear()
        self._decision_applier.close()
        self._closed = True

    def _find_pending(
        self,
        request_id: str,
    ) -> EpisodeExperienceReviewRequest:
        if not isinstance(request_id, str):
            raise TypeError("request_id must be str")
        for request in self._mailbox.pending_requests():
            if request.request_id == request_id:
                return request
        raise EpisodeReviewClaimError(
            "episode review request is not pending"
        )

    def _find_claim(
        self,
        claim_id: str,
    ) -> tuple[str, EpisodeReviewClaim]:
        if not isinstance(claim_id, str):
            raise TypeError("claim_id must be str")
        for request_ref, claim in self._claims.items():
            if claim.claim_id == claim_id:
                return request_ref, claim
        raise EpisodeReviewClaimError(
            "episode review claim is not active"
        )

    def _require_open(self) -> None:
        if self._closed:
            raise EpisodeReviewClaimError(
                "episode review claim service is closed"
            )
