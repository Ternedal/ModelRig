"""C30-Q privacy-safe episode review runtime status projection.

The projection exposes counts and lifecycle state only. It never returns request
ids/refs, claim ids, closure evidence, raw text, or model chain-of-thought.
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_review_claim import TrustedEpisodeReviewClaimService
from .episode_review_lifecycle import (
    EpisodeReviewRuntime,
    episode_review_runtime_enabled,
)
from .episode_review_mailbox import EpisodeExperienceReviewMailbox
from .episode_review_observability import (
    EpisodeReviewObservability,
    EpisodeReviewObservabilitySnapshot,
)
from .session_lifecycle import ProductionCognitiveSession


ReviewRuntimeState = Literal[
    "OFF",
    "TRANSPORT_ONLY",
    "RUNTIME_UNAVAILABLE",
    "ACTIVE_IDLE",
    "ACTIVE_PENDING",
    "ACTIVE_CLAIMED",
    "MAILBOX_FULL",
    "CLOSED",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewStatusSnapshot(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-status/v1"
    ]
    state: ReviewRuntimeState
    runtime_enabled: bool
    transport_enabled: bool
    runtime_present: bool
    service_present: bool
    mailbox_present: bool
    mailbox_capacity: int | None = Field(default=None, ge=1, le=32)
    pending_count: int = Field(ge=0, le=32, strict=True)
    claimed_count: int = Field(ge=0, le=32, strict=True)
    mailbox_full: bool
    runtime_closed: bool | None
    mailbox_closed: bool | None
    last_publication_status: str | None
    observability_present: bool
    observability: EpisodeReviewObservabilitySnapshot | None
    request_refs_included: Literal[False]
    claim_ids_included: Literal[False]
    closure_evidence_included: Literal[False]
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeReviewStatusSnapshot":
        if not self.mailbox_present:
            if self.mailbox_capacity is not None:
                raise ValueError("absent mailbox cannot expose capacity")
            if self.pending_count != 0 or self.mailbox_full:
                raise ValueError("absent mailbox cannot expose pending work")
            if self.mailbox_closed is not None:
                raise ValueError("absent mailbox cannot expose closed state")
        if not self.service_present and self.claimed_count != 0:
            raise ValueError("absent service cannot expose claimed work")
        if self.observability_present != (self.observability is not None):
            raise ValueError("review observability presence mismatch")
        if self.mailbox_present and self.mailbox_capacity is not None:
            if self.mailbox_full != (
                self.pending_count >= self.mailbox_capacity
            ):
                raise ValueError("mailbox full flag mismatch")
        return self


def build_episode_review_status(app) -> EpisodeReviewStatusSnapshot:
    runtime_enabled = episode_review_runtime_enabled()
    transport_enabled = (
        os.getenv(
            "KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED",
            "0",
        )
        == "1"
    )

    runtime = getattr(
        app.state,
        "consciousness_episode_review_runtime",
        None,
    )
    mailbox = getattr(
        app.state,
        "consciousness_episode_review_mailbox",
        None,
    )
    service = getattr(
        app.state,
        "consciousness_episode_review_service",
        None,
    )
    observability = getattr(
        app.state,
        "consciousness_episode_review_observability",
        None,
    )

    if runtime is not None and not isinstance(runtime, EpisodeReviewRuntime):
        runtime = None
    if mailbox is not None and not isinstance(
        mailbox,
        EpisodeExperienceReviewMailbox,
    ):
        mailbox = None
    if service is not None and not isinstance(
        service,
        TrustedEpisodeReviewClaimService,
    ):
        service = None
    if observability is not None and not isinstance(
        observability,
        EpisodeReviewObservability,
    ):
        observability = None

    mailbox_snapshot = mailbox.snapshot if mailbox is not None else None
    service_snapshot = service.snapshot if service is not None else None

    pending_count = (
        mailbox_snapshot.pending_count
        if mailbox_snapshot is not None
        else 0
    )
    claimed_count = (
        service_snapshot.claimed_count
        if service_snapshot is not None
        else 0
    )
    capacity = (
        mailbox_snapshot.capacity
        if mailbox_snapshot is not None
        else None
    )
    mailbox_full = (
        capacity is not None and pending_count >= capacity
    )

    session = getattr(app.state, "consciousness_session", None)
    last_publication_status = None
    if isinstance(session, ProductionCognitiveSession):
        publication = session.last_episode_review_publication
        if publication is not None:
            last_publication_status = publication.status

    runtime_binding_valid = (
        runtime is not None
        and mailbox is not None
        and service is not None
        and runtime.mailbox is mailbox
        and runtime.service is service
        and (
            runtime.observability is None
            or runtime.observability is observability
        )
    )

    if runtime is None:
        if transport_enabled and not runtime_enabled:
            state: ReviewRuntimeState = "TRANSPORT_ONLY"
        elif runtime_enabled:
            state = "RUNTIME_UNAVAILABLE"
        else:
            state = "OFF"
    elif not runtime_binding_valid:
        state = "RUNTIME_UNAVAILABLE"
    elif runtime.closed or (
        mailbox_snapshot is not None and mailbox_snapshot.closed
    ):
        state = "CLOSED"
    elif mailbox_full:
        state = "MAILBOX_FULL"
    elif claimed_count > 0:
        state = "ACTIVE_CLAIMED"
    elif pending_count > 0:
        state = "ACTIVE_PENDING"
    else:
        state = "ACTIVE_IDLE"

    return EpisodeReviewStatusSnapshot(
        schema="kaliv-consciousness-core/episode-review-status/v1",
        state=state,
        runtime_enabled=runtime_enabled,
        transport_enabled=transport_enabled,
        runtime_present=runtime is not None,
        service_present=service is not None,
        mailbox_present=mailbox is not None,
        mailbox_capacity=capacity,
        pending_count=pending_count,
        claimed_count=claimed_count,
        mailbox_full=mailbox_full,
        runtime_closed=(runtime.closed if runtime is not None else None),
        mailbox_closed=(
            mailbox_snapshot.closed
            if mailbox_snapshot is not None
            else None
        ),
        last_publication_status=last_publication_status,
        observability_present=observability is not None,
        observability=(
            observability.snapshot
            if observability is not None
            else None
        ),
        request_refs_included=False,
        claim_ids_included=False,
        closure_evidence_included=False,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        memory4_called=False,
        model_calls=0,
        production_activation=False,
    )
