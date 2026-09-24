"""C30-S read-only operator-attention evaluation for episode review.

This module derives bounded attention signals from C30-Q status and C30-R
aggregate counters. It performs no notification, scheduling, timer, retry,
background work, persistence, or automatic remediation.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_review_status import EpisodeReviewStatusSnapshot


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
PositiveInt = Annotated[int, Field(ge=1, le=1_000_000, strict=True)]
SignalCode = Literal[
    "RUNTIME_UNAVAILABLE",
    "MAILBOX_PRESSURE",
    "MAILBOX_FULL",
    "CLAIM_PRESSURE",
    "REPEATED_CAPACITY_REJECTION",
    "REPLAY_LEDGER_EXHAUSTION",
    "PUBLICATION_TO_CLOSED_MAILBOX",
    "REPEATED_DUPLICATE_PUBLICATION",
]
AttentionLevel = Literal["OK", "ATTENTION", "DEGRADED"]
SignalSeverity = Literal["ATTENTION", "DEGRADED"]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewAttentionPolicy(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-attention-policy/v1"
    ]
    mailbox_pressure_ratio: UnitInterval
    claim_pressure_count: Annotated[int, Field(ge=1, le=32, strict=True)]
    capacity_rejection_threshold: PositiveInt
    replay_ledger_full_threshold: PositiveInt
    mailbox_closed_publication_threshold: PositiveInt
    duplicate_publication_threshold: PositiveInt


DEFAULT_EPISODE_REVIEW_ATTENTION_POLICY = EpisodeReviewAttentionPolicy(
    schema=(
        "kaliv-consciousness-core/"
        "episode-review-attention-policy/v1"
    ),
    mailbox_pressure_ratio=0.75,
    claim_pressure_count=24,
    capacity_rejection_threshold=3,
    replay_ledger_full_threshold=1,
    mailbox_closed_publication_threshold=1,
    duplicate_publication_threshold=10,
)


class EpisodeReviewAttentionSignal(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-attention-signal/v1"
    ]
    code: SignalCode
    severity: SignalSeverity
    observed_value: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    threshold_value: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    request_refs_included: Literal[False]
    claim_ids_included: Literal[False]
    automatic_action: Literal[False]
    notification_sent: Literal[False]
    production_activation: Literal[False]


class EpisodeReviewAttentionSnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-attention/v1"
    ]
    level: AttentionLevel
    signals: Annotated[
        list[EpisodeReviewAttentionSignal],
        Field(max_length=8),
    ]
    signal_count: Annotated[int, Field(ge=0, le=8, strict=True)]
    request_refs_included: Literal[False]
    claim_ids_included: Literal[False]
    closure_evidence_included: Literal[False]
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    notifications_sent: Literal[0]
    timers_started: Literal[0]
    scheduler_jobs_created: Literal[0]
    background_tasks_started: Literal[0]
    automatic_actions_taken: Literal[0]
    durable_store_write_applied: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewAttentionSnapshot":
        if self.signal_count != len(self.signals):
            raise ValueError("review attention signal count mismatch")
        expected = "OK"
        if any(signal.severity == "DEGRADED" for signal in self.signals):
            expected = "DEGRADED"
        elif self.signals:
            expected = "ATTENTION"
        if self.level != expected:
            raise ValueError("review attention level mismatch")
        if len({signal.code for signal in self.signals}) != len(
            self.signals
        ):
            raise ValueError("review attention signal codes must be unique")
        return self


def _signal(
    *,
    code: SignalCode,
    severity: SignalSeverity,
    observed_value: float,
    threshold_value: float,
) -> EpisodeReviewAttentionSignal:
    return EpisodeReviewAttentionSignal(
        schema=(
            "kaliv-consciousness-core/"
            "episode-review-attention-signal/v1"
        ),
        code=code,
        severity=severity,
        observed_value=observed_value,
        threshold_value=threshold_value,
        request_refs_included=False,
        claim_ids_included=False,
        automatic_action=False,
        notification_sent=False,
        production_activation=False,
    )


def evaluate_episode_review_attention(
    status: EpisodeReviewStatusSnapshot,
    policy: EpisodeReviewAttentionPolicy = (
        DEFAULT_EPISODE_REVIEW_ATTENTION_POLICY
    ),
) -> EpisodeReviewAttentionSnapshot:
    """Pure snapshot evaluation with no side effects or historical state."""
    if not isinstance(status, EpisodeReviewStatusSnapshot):
        raise TypeError("status must be EpisodeReviewStatusSnapshot")
    if not isinstance(policy, EpisodeReviewAttentionPolicy):
        raise TypeError("policy must be EpisodeReviewAttentionPolicy")

    signals: list[EpisodeReviewAttentionSignal] = []

    if status.state == "RUNTIME_UNAVAILABLE":
        signals.append(
            _signal(
                code="RUNTIME_UNAVAILABLE",
                severity="DEGRADED",
                observed_value=1.0,
                threshold_value=1.0,
            )
        )

    if status.mailbox_present and status.mailbox_capacity is not None:
        occupancy = (
            status.pending_count / status.mailbox_capacity
            if status.mailbox_capacity > 0
            else 0.0
        )
        if status.mailbox_full:
            signals.append(
                _signal(
                    code="MAILBOX_FULL",
                    severity="DEGRADED",
                    observed_value=float(status.pending_count),
                    threshold_value=float(status.mailbox_capacity),
                )
            )
        elif occupancy >= policy.mailbox_pressure_ratio:
            signals.append(
                _signal(
                    code="MAILBOX_PRESSURE",
                    severity="ATTENTION",
                    observed_value=occupancy,
                    threshold_value=policy.mailbox_pressure_ratio,
                )
            )

    if status.claimed_count >= policy.claim_pressure_count:
        signals.append(
            _signal(
                code="CLAIM_PRESSURE",
                severity="ATTENTION",
                observed_value=float(status.claimed_count),
                threshold_value=float(policy.claim_pressure_count),
            )
        )

    metrics = status.observability
    if metrics is not None:
        if (
            metrics.publication_capacity_reached
            >= policy.capacity_rejection_threshold
        ):
            signals.append(
                _signal(
                    code="REPEATED_CAPACITY_REJECTION",
                    severity="DEGRADED",
                    observed_value=float(
                        metrics.publication_capacity_reached
                    ),
                    threshold_value=float(
                        policy.capacity_rejection_threshold
                    ),
                )
            )
        if (
            metrics.publication_replay_ledger_full
            >= policy.replay_ledger_full_threshold
        ):
            signals.append(
                _signal(
                    code="REPLAY_LEDGER_EXHAUSTION",
                    severity="DEGRADED",
                    observed_value=float(
                        metrics.publication_replay_ledger_full
                    ),
                    threshold_value=float(
                        policy.replay_ledger_full_threshold
                    ),
                )
            )
        if (
            metrics.publication_mailbox_closed
            >= policy.mailbox_closed_publication_threshold
        ):
            signals.append(
                _signal(
                    code="PUBLICATION_TO_CLOSED_MAILBOX",
                    severity="ATTENTION",
                    observed_value=float(
                        metrics.publication_mailbox_closed
                    ),
                    threshold_value=float(
                        policy.mailbox_closed_publication_threshold
                    ),
                )
            )
        if (
            metrics.publication_duplicate
            >= policy.duplicate_publication_threshold
        ):
            signals.append(
                _signal(
                    code="REPEATED_DUPLICATE_PUBLICATION",
                    severity="ATTENTION",
                    observed_value=float(
                        metrics.publication_duplicate
                    ),
                    threshold_value=float(
                        policy.duplicate_publication_threshold
                    ),
                )
            )

    level: AttentionLevel = "OK"
    if any(signal.severity == "DEGRADED" for signal in signals):
        level = "DEGRADED"
    elif signals:
        level = "ATTENTION"

    return EpisodeReviewAttentionSnapshot(
        schema="kaliv-consciousness-core/episode-review-attention/v1",
        level=level,
        signals=signals,
        signal_count=len(signals),
        request_refs_included=False,
        claim_ids_included=False,
        closure_evidence_included=False,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        notifications_sent=0,
        timers_started=0,
        scheduler_jobs_created=0,
        background_tasks_started=0,
        automatic_actions_taken=0,
        durable_store_write_applied=False,
        memory4_called=False,
        model_calls=0,
        production_activation=False,
    )
