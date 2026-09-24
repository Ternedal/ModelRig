"""C30-T compact privacy-safe operator summary for episode review.

The summary composes C30-Q status and C30-S attention into one bounded,
read-only dashboard projection. It contains no individual review item data.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_review_attention import (
    DEFAULT_EPISODE_REVIEW_ATTENTION_POLICY,
    AttentionLevel,
    EpisodeReviewAttentionPolicy,
    SignalCode,
    evaluate_episode_review_attention,
)
from .episode_review_observability import MAX_OBSERVABILITY_COUNTER
from .episode_review_status import (
    ReviewRuntimeState,
    build_episode_review_status,
)


CounterInt = Annotated[
    int,
    Field(ge=0, le=MAX_OBSERVABILITY_COUNTER, strict=True),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewOperatorSummary(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-operator-summary/v1"
    ]
    state: ReviewRuntimeState
    attention_level: AttentionLevel
    attention_signal_count: Annotated[int, Field(ge=0, le=8, strict=True)]
    attention_signal_codes: Annotated[list[SignalCode], Field(max_length=8)]
    runtime_enabled: bool
    transport_enabled: bool
    runtime_present: bool
    mailbox_present: bool
    service_present: bool
    observability_present: bool
    mailbox_capacity: int | None = Field(default=None, ge=1, le=32)
    pending_count: Annotated[int, Field(ge=0, le=32, strict=True)]
    claimed_count: Annotated[int, Field(ge=0, le=32, strict=True)]
    mailbox_full: bool
    last_publication_status: str | None
    publication_enqueued: CounterInt
    publication_capacity_reached: CounterInt
    publication_duplicate: CounterInt
    publication_replay_ledger_full: CounterInt
    claims_succeeded: CounterInt
    abandons_succeeded: CounterInt
    approvals_succeeded: CounterInt
    rejections_succeeded: CounterInt
    individual_review_items_included: Literal[False]
    request_refs_included: Literal[False]
    claim_ids_included: Literal[False]
    closure_evidence_included: Literal[False]
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    notification_sent: Literal[False]
    automatic_action_taken: Literal[False]
    durable_store_write_applied: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewOperatorSummary":
        if self.attention_signal_count != len(
            self.attention_signal_codes
        ):
            raise ValueError("operator summary attention count mismatch")
        if len(self.attention_signal_codes) != len(
            set(self.attention_signal_codes)
        ):
            raise ValueError(
                "operator summary attention codes must be unique"
            )
        if not self.observability_present:
            for value in (
                self.publication_enqueued,
                self.publication_capacity_reached,
                self.publication_duplicate,
                self.publication_replay_ledger_full,
                self.claims_succeeded,
                self.abandons_succeeded,
                self.approvals_succeeded,
                self.rejections_succeeded,
            ):
                if value != 0:
                    raise ValueError(
                        "operator summary cannot expose counters "
                        "without observability"
                    )
        return self


def build_episode_review_operator_summary(
    app,
    *,
    policy: EpisodeReviewAttentionPolicy = (
        DEFAULT_EPISODE_REVIEW_ATTENTION_POLICY
    ),
) -> EpisodeReviewOperatorSummary:
    """Compose one bounded read-only operator dashboard snapshot."""
    status = build_episode_review_status(app)
    attention = evaluate_episode_review_attention(
        status,
        policy,
    )
    metrics = status.observability

    return EpisodeReviewOperatorSummary(
        schema=(
            "kaliv-consciousness-core/"
            "episode-review-operator-summary/v1"
        ),
        state=status.state,
        attention_level=attention.level,
        attention_signal_count=attention.signal_count,
        attention_signal_codes=[
            signal.code for signal in attention.signals
        ],
        runtime_enabled=status.runtime_enabled,
        transport_enabled=status.transport_enabled,
        runtime_present=status.runtime_present,
        mailbox_present=status.mailbox_present,
        service_present=status.service_present,
        observability_present=status.observability_present,
        mailbox_capacity=status.mailbox_capacity,
        pending_count=status.pending_count,
        claimed_count=status.claimed_count,
        mailbox_full=status.mailbox_full,
        last_publication_status=status.last_publication_status,
        publication_enqueued=(
            metrics.publication_enqueued if metrics is not None else 0
        ),
        publication_capacity_reached=(
            metrics.publication_capacity_reached
            if metrics is not None
            else 0
        ),
        publication_duplicate=(
            metrics.publication_duplicate if metrics is not None else 0
        ),
        publication_replay_ledger_full=(
            metrics.publication_replay_ledger_full
            if metrics is not None
            else 0
        ),
        claims_succeeded=(
            metrics.claims_succeeded if metrics is not None else 0
        ),
        abandons_succeeded=(
            metrics.abandons_succeeded if metrics is not None else 0
        ),
        approvals_succeeded=(
            metrics.approvals_succeeded if metrics is not None else 0
        ),
        rejections_succeeded=(
            metrics.rejections_succeeded if metrics is not None else 0
        ),
        individual_review_items_included=False,
        request_refs_included=False,
        claim_ids_included=False,
        closure_evidence_included=False,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        notification_sent=False,
        automatic_action_taken=False,
        durable_store_write_applied=False,
        memory4_called=False,
        model_calls=0,
        production_activation=False,
    )
