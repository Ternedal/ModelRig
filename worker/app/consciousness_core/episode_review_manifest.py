"""C30-U machine-readable capability manifest for episode review.

The manifest describes static gates, surfaces, bounds and denied authorities.
It contains no live runtime state and performs no activation or side effects.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .episode_review_lifecycle import (
    DEFAULT_EPISODE_REVIEW_MAILBOX_CAPACITY,
    EPISODE_REVIEW_RUNTIME_FLAG,
)
from .episode_review_observability import MAX_OBSERVABILITY_COUNTER


CONSCIOUSNESS_EPISODE_REVIEW_FLAG = (
    "KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED"
)
CONSCIOUSNESS_EPISODE_REVIEW_PREFIX = (
    "/experimental/consciousness/episode-review"
)

NonEmpty = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewCapabilityManifest(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-capability-manifest/v1"
    ]
    capability: Literal["C30_EXPERIENTIAL_EPISODE_REVIEW"]
    slice_start: Literal["C30-H"]
    slice_end: Literal["C30-T"]
    runtime_flag: Literal[
        "KALIV_CONSCIOUSNESS_EPISODE_REVIEW_RUNTIME_ENABLED"
    ]
    transport_flag: Literal[
        "KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED"
    ]
    runtime_default_enabled: Literal[False]
    transport_default_enabled: Literal[False]
    transport_loopback_only: Literal[True]
    operator_read_routes: Annotated[list[NonEmpty], Field(max_length=4)]
    review_workflow_routes: Annotated[list[NonEmpty], Field(max_length=4)]
    mailbox_default_capacity: Literal[8]
    mailbox_max_capacity: Literal[32]
    pending_list_max_items: Literal[32]
    active_claim_max_count: Literal[32]
    observability_counter_max: Literal[9223372036854775807]
    episode_boundary_review_publication_non_blocking: Literal[True]
    claim_keeps_request_pending: Literal[True]
    semantic_preflight_before_consume: Literal[True]
    exact_request_ref_binding: Literal[True]
    synthetic_cycle_allowed: Literal[False]
    synthetic_user_fact_reconstruction_allowed: Literal[False]
    episode_derived_completed_turn_authority: Literal[False]
    direct_memory4_write_authority: Literal[False]
    durable_review_store: Literal[False]
    durable_claim_recovery: Literal[False]
    automatic_semantic_review: Literal[False]
    raw_user_text_in_operator_status: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    notifications_automatic: Literal[False]
    timers_authority: Literal[False]
    scheduling_authority: Literal[False]
    background_worker_authority: Literal[False]
    execution_authority: Literal[False]
    model_calls_from_review_control_plane: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_contract(self) -> "EpisodeReviewCapabilityManifest":
        routes = self.operator_read_routes + self.review_workflow_routes
        if len(routes) != len(set(routes)):
            raise ValueError("episode review manifest routes must be unique")
        if any(
            not route.startswith(CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/")
            for route in routes
        ):
            raise ValueError("episode review manifest route prefix mismatch")
        return self


def build_episode_review_capability_manifest(
) -> EpisodeReviewCapabilityManifest:
    """Return the static C30-H..T capability contract."""
    return EpisodeReviewCapabilityManifest(
        schema=(
            "kaliv-consciousness-core/"
            "episode-review-capability-manifest/v1"
        ),
        capability="C30_EXPERIENTIAL_EPISODE_REVIEW",
        slice_start="C30-H",
        slice_end="C30-T",
        runtime_flag=EPISODE_REVIEW_RUNTIME_FLAG,
        transport_flag=CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
        runtime_default_enabled=False,
        transport_default_enabled=False,
        transport_loopback_only=True,
        operator_read_routes=[
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/manifest",
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/status",
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/attention",
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/summary",
        ],
        review_workflow_routes=[
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/pending",
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/abandon",
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/commit",
        ],
        mailbox_default_capacity=DEFAULT_EPISODE_REVIEW_MAILBOX_CAPACITY,
        mailbox_max_capacity=32,
        pending_list_max_items=32,
        active_claim_max_count=32,
        observability_counter_max=MAX_OBSERVABILITY_COUNTER,
        episode_boundary_review_publication_non_blocking=True,
        claim_keeps_request_pending=True,
        semantic_preflight_before_consume=True,
        exact_request_ref_binding=True,
        synthetic_cycle_allowed=False,
        synthetic_user_fact_reconstruction_allowed=False,
        episode_derived_completed_turn_authority=False,
        direct_memory4_write_authority=False,
        durable_review_store=False,
        durable_claim_recovery=False,
        automatic_semantic_review=False,
        raw_user_text_in_operator_status=False,
        raw_chain_of_thought_included=False,
        notifications_automatic=False,
        timers_authority=False,
        scheduling_authority=False,
        background_worker_authority=False,
        execution_authority=False,
        model_calls_from_review_control_plane=0,
        production_activation=False,
    )
