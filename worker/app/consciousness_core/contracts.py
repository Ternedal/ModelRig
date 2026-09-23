"""Strict runtime models for the C0-C3 Consciousness Core contracts.

These models intentionally duplicate only the runtime-relevant shape of the
versioned JSON contracts. They add no authority: provider/model identity is
transient CognitiveProfile data, while ThoughtProposal has empty action and
state-mutation surfaces and all authority bits are pinned false.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
ShortText = Annotated[str, Field(min_length=1, max_length=2048)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CognitiveProfile(StrictModel):
    schema: Literal["kaliv-consciousness-core/cognitive-profile/v1"]
    profile_id: Annotated[str, Field(pattern=r"^cog-[a-f0-9]{32}$")]
    engine_instance_id: NonEmptyRef
    provider: Annotated[str, Field(min_length=1, max_length=128)]
    model: NonEmptyRef
    reasoning_depth: UnitInterval
    planning_capacity: UnitInterval
    context_capacity_tokens: Annotated[int, Field(ge=1, strict=True)]
    multimodal_capacity: UnitInterval
    tool_reasoning: UnitInterval
    uncertainty_calibration: UnitInterval
    ephemeral: Literal[True]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    action_authority: Literal[False]
    production_activation: Literal[False]


class PersonalitySnapshot(StrictModel):
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    personality_revision: Annotated[str, Field(pattern=r"^personality-r[0-9]{4,}$")]
    personality_state_ref: NonEmptyRef
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]


class ThoughtRequest(StrictModel):
    schema: Literal["kaliv-consciousness-core/thought-request/v1"]
    request_id: Annotated[str, Field(pattern=r"^thinkreq-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    self_state_ref: NonEmptyRef
    world_state_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    personality_snapshot: PersonalitySnapshot
    relevant_memory_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    embodiment_state_ref: NonEmptyRef | None
    cognitive_profile_ref: NonEmptyRef
    requested_reasoning_mode: Literal["fast", "normal", "deep", "verify"]
    production_activation: Literal[False]


class Hypothesis(StrictModel):
    summary: ShortText
    confidence: UnitInterval


class CandidateIntention(StrictModel):
    summary: ShortText
    confidence: UnitInterval
    required_authority: Literal[
        "none",
        "agent3",
        "bodyrig",
        "voicerig",
        "memory4",
        "human_review",
    ]


class PredictedOutcome(StrictModel):
    summary: ShortText
    confidence: UnitInterval


class ProposalAuthority(StrictModel):
    identity: Literal[False]
    persistent_state: Literal[False]
    durable_memory: Literal[False]
    action: Literal[False]


class ThoughtProposal(StrictModel):
    schema: Literal["kaliv-consciousness-core/thought-proposal/v1"]
    proposal_id: Annotated[str, Field(pattern=r"^thinkprop-[a-f0-9]{32}$")]
    request_id: Annotated[str, Field(pattern=r"^thinkreq-[a-f0-9]{32}$")]
    interpretation: Annotated[str, Field(max_length=8192)]
    hypotheses: Annotated[list[Hypothesis], Field(max_length=32)]
    candidate_intentions: Annotated[list[CandidateIntention], Field(max_length=32)]
    predicted_outcomes: Annotated[list[PredictedOutcome], Field(max_length=32)]
    questions: Annotated[list[ShortText], Field(max_length=32)]
    memory_queries: Annotated[list[ShortText], Field(max_length=32)]
    attention_suggestions: Annotated[list[NonEmptyRef], Field(max_length=32)]
    response_intent: Annotated[str, Field(max_length=4096)] | None
    body_intent: Annotated[str, Field(max_length=4096)] | None
    uncertainty: UnitInterval
    state_mutations: Annotated[list[Any], Field(max_length=0)]
    actions: Annotated[list[Any], Field(max_length=0)]
    authority: ProposalAuthority
    production_activation: Literal[False]
