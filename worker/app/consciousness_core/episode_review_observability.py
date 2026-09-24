"""C30-R privacy-safe aggregate observability for episode review.

This module records counters only. It stores no request ids/refs, claim ids,
closure evidence, timestamps, user text, model chain-of-thought, or audit log.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


MAX_OBSERVABILITY_COUNTER = 9_223_372_036_854_775_807
CounterInt = Annotated[
    int,
    Field(ge=0, le=MAX_OBSERVABILITY_COUNTER, strict=True),
]
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


class EpisodeReviewObservabilitySnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-observability/v1"
    ]
    publication_not_applicable: CounterInt
    publication_mailbox_unavailable: CounterInt
    publication_no_review: CounterInt
    publication_enqueued: CounterInt
    publication_duplicate: CounterInt
    publication_capacity_reached: CounterInt
    publication_mailbox_closed: CounterInt
    publication_replay_ledger_full: CounterInt
    claims_succeeded: CounterInt
    abandons_succeeded: CounterInt
    approvals_succeeded: CounterInt
    rejections_succeeded: CounterInt
    request_ids_stored: Literal[False]
    request_refs_stored: Literal[False]
    claim_ids_stored: Literal[False]
    closure_evidence_stored: Literal[False]
    timestamps_stored: Literal[False]
    event_history_stored: Literal[False]
    raw_text_stored: Literal[False]
    raw_chain_of_thought_stored: Literal[False]
    durable: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    production_activation: Literal[False]


class EpisodeReviewObservability:
    """Process-local monotonic aggregate counters only."""

    @staticmethod
    def _increment(value: int) -> int:
        return min(value + 1, MAX_OBSERVABILITY_COUNTER)

    def __init__(self) -> None:
        self._publication = {
            "NOT_APPLICABLE": 0,
            "MAILBOX_UNAVAILABLE": 0,
            "NO_REVIEW": 0,
            "ENQUEUED": 0,
            "DUPLICATE": 0,
            "CAPACITY_REACHED": 0,
            "MAILBOX_CLOSED": 0,
            "REPLAY_LEDGER_FULL": 0,
        }
        self._claims_succeeded = 0
        self._abandons_succeeded = 0
        self._approvals_succeeded = 0
        self._rejections_succeeded = 0

    @property
    def snapshot(self) -> EpisodeReviewObservabilitySnapshot:
        return EpisodeReviewObservabilitySnapshot(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-observability/v1"
            ),
            publication_not_applicable=self._publication[
                "NOT_APPLICABLE"
            ],
            publication_mailbox_unavailable=self._publication[
                "MAILBOX_UNAVAILABLE"
            ],
            publication_no_review=self._publication["NO_REVIEW"],
            publication_enqueued=self._publication["ENQUEUED"],
            publication_duplicate=self._publication["DUPLICATE"],
            publication_capacity_reached=self._publication[
                "CAPACITY_REACHED"
            ],
            publication_mailbox_closed=self._publication[
                "MAILBOX_CLOSED"
            ],
            publication_replay_ledger_full=self._publication[
                "REPLAY_LEDGER_FULL"
            ],
            claims_succeeded=self._claims_succeeded,
            abandons_succeeded=self._abandons_succeeded,
            approvals_succeeded=self._approvals_succeeded,
            rejections_succeeded=self._rejections_succeeded,
            request_ids_stored=False,
            request_refs_stored=False,
            claim_ids_stored=False,
            closure_evidence_stored=False,
            timestamps_stored=False,
            event_history_stored=False,
            raw_text_stored=False,
            raw_chain_of_thought_stored=False,
            durable=False,
            memory4_called=False,
            model_calls=0,
            production_activation=False,
        )

    def record_publication(self, status: PublicationStatus) -> None:
        if status not in self._publication:
            raise ValueError("unknown episode review publication status")
        self._publication[status] = self._increment(
            self._publication[status]
        )

    def record_claim(self) -> None:
        self._claims_succeeded = self._increment(
            self._claims_succeeded
        )

    def record_abandon(self) -> None:
        self._abandons_succeeded = self._increment(
            self._abandons_succeeded
        )

    def record_decision(
        self,
        decision: Literal["APPROVE", "REJECT"],
    ) -> None:
        if decision == "APPROVE":
            self._approvals_succeeded = self._increment(
                self._approvals_succeeded
            )
        elif decision == "REJECT":
            self._rejections_succeeded = self._increment(
                self._rejections_succeeded
            )
        else:
            raise ValueError("unknown episode review decision")
