"""C23-A one-shot outward response-guidance projection.

Only ThoughtProposal.response_intent is eligible. The projection deliberately
excludes interpretation, hypotheses, candidate intentions, predictions,
questions and every other inner-monologue field.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import ThoughtProposal
from .cycle import proposal_ref
from .supervisor import CognitionEvent


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
EventId = Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
GuidanceId = Annotated[str, Field(pattern=r"^rguid-[a-f0-9]{32}$")]
GuidanceText = Annotated[str, Field(min_length=1, max_length=4096)]


class ResponseGuidanceError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ResponseGuidanceEnvelope(StrictModel):
    schema: Literal["kaliv-consciousness-core/response-guidance/v1"]
    guidance_id: GuidanceId
    user_turn_event_id: EventId
    cycle_id: CycleId
    proposal_ref: NonEmptyRef
    cognitive_profile_ref: NonEmptyRef
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    self_revision: Annotated[int, Field(ge=1, strict=True)]
    text: GuidanceText
    source_field: Literal["thought-proposal.response_intent"]
    contains_only_response_intent: Literal[True]
    raw_chain_of_thought_included: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
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


def response_guidance_ref(guidance: ResponseGuidanceEnvelope) -> str:
    if not isinstance(guidance, ResponseGuidanceEnvelope):
        raise TypeError("guidance must be ResponseGuidanceEnvelope")
    return "response-guidance:" + hashlib.sha256(
        _canonical_json(guidance)
    ).hexdigest()


def _guidance_id(seed: dict[str, Any]) -> str:
    return "rguid-" + hashlib.sha256(_canonical_json(seed)).hexdigest()[:32]


def build_response_guidance(
    *,
    proposal: ThoughtProposal,
    selected_events: list[CognitionEvent],
    cycle_id: str,
    cognitive_profile_ref: str,
    person_revision: str,
    self_revision: int,
) -> ResponseGuidanceEnvelope | None:
    """Project outward guidance only when one selected user turn is unambiguous."""
    if not isinstance(proposal, ThoughtProposal):
        raise TypeError("proposal must be ThoughtProposal")
    if not all(isinstance(event, CognitionEvent) for event in selected_events):
        raise TypeError("selected_events must contain CognitionEvent values")
    if not isinstance(cognitive_profile_ref, str) or not cognitive_profile_ref:
        raise ResponseGuidanceError("missing cognitive profile ref")

    text = (proposal.response_intent or "").strip()
    if not text:
        return None

    user_turns = [event for event in selected_events if event.kind == "user_turn"]
    if len(user_turns) != 1:
        # Zero user turns means there is no outward user reply to guide. More
        # than one is ambiguous: Core refuses to guess which turn owns the text.
        return None

    user_turn = user_turns[0]
    current_proposal_ref = proposal_ref(proposal)
    seed = {
        "user_turn_event_id": user_turn.event_id,
        "cycle_id": cycle_id,
        "proposal_ref": current_proposal_ref,
        "cognitive_profile_ref": cognitive_profile_ref,
        "person_revision": person_revision,
        "self_revision": self_revision,
        "text": text,
        "projection": "response-guidance-v1",
    }
    return ResponseGuidanceEnvelope(
        schema="kaliv-consciousness-core/response-guidance/v1",
        guidance_id=_guidance_id(seed),
        user_turn_event_id=user_turn.event_id,
        cycle_id=cycle_id,
        proposal_ref=current_proposal_ref,
        cognitive_profile_ref=cognitive_profile_ref,
        person_revision=person_revision,
        self_revision=self_revision,
        text=text,
        source_field="thought-proposal.response_intent",
        contains_only_response_intent=True,
        raw_chain_of_thought_included=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
