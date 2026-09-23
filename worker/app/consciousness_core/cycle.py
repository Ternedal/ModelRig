"""C15 authoritative cognitive-cycle assembly for Consciousness Core.

The external model is a replaceable inner-monologue engine. This module owns the
bounded context assembly and exact binding checks around one cognitive cycle, but
it grants no persistence, memory-write, scheduler, tool, body, voice, or execution
authority to the model.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import (
    CognitiveProfile,
    PersonalitySnapshot,
    ThoughtProposal,
    ThoughtRequest,
)
from .continuity import (
    ContinuityContextProjection,
    PostWakeContinuityState,
    project_continuity_context,
)
from .runtime import ConsciousnessCoreRuntime
from .self_state import PersistentSelfState


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
CandidateId = Annotated[str, Field(pattern=r"^wc-[a-f0-9]{32}$")]
ObservationId = Annotated[str, Field(pattern=r"^obs-[a-f0-9]{32}$")]

WorkspaceKind = Literal[
    "perception",
    "memory",
    "goal",
    "body",
    "voice",
    "tool_result",
    "prediction_error",
    "thought_result",
]
EpistemicStatus = Literal["observed", "reported", "inferred", "predicted"]
ReasoningMode = Literal["fast", "normal", "deep", "verify"]


class CognitiveCycleError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class WorldObservation(StrictModel):
    observation_id: ObservationId
    subject_ref: NonEmptyRef
    proposition: BoundedText
    confidence: UnitInterval
    epistemic_status: EpistemicStatus
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_sources(self) -> "WorldObservation":
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("WorldObservation source_refs must be unique")
        return self


class RuntimeWorldState(StrictModel):
    schema: Literal["kaliv-consciousness-core/world-state/v1"]
    world_id: Annotated[str, Field(pattern=r"^world-[a-f0-9]{32}$")]
    revision: Annotated[int, Field(ge=1, strict=True)]
    observations: Annotated[list[WorldObservation], Field(max_length=512)]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def unique_observations(self) -> "RuntimeWorldState":
        ids = [item.observation_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("WorldState observation ids must be unique")
        return self


class WorkspaceCandidate(StrictModel):
    candidate_id: CandidateId
    kind: WorkspaceKind
    salience: UnitInterval
    summary: BoundedText
    source_ref: NonEmptyRef


class CognitiveWorkspace(StrictModel):
    schema: Literal["kaliv-consciousness-core/workspace/v1"]
    cycle_id: CycleId
    candidates: Annotated[list[WorkspaceCandidate], Field(max_length=256)]
    selected_candidate_ids: Annotated[list[CandidateId], Field(max_length=16)]
    max_active: Annotated[int, Field(ge=1, le=16, strict=True)]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def validate_selection(self) -> "CognitiveWorkspace":
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("workspace candidate ids must be unique")
        if len(self.selected_candidate_ids) != len(set(self.selected_candidate_ids)):
            raise ValueError("selected candidate ids must be unique")
        if len(self.selected_candidate_ids) > self.max_active:
            raise ValueError("selected candidates exceed max_active")
        if not set(self.selected_candidate_ids).issubset(set(candidate_ids)):
            raise ValueError("selected candidate is not present in workspace")
        return self


class CognitiveContextPacket(StrictModel):
    """Bounded materialized context shown to the replaceable ThoughtEngine.

    The packet is ephemeral. Durable memory contents are deliberately not copied
    here in C15; Memory 4 remains authoritative and only selected refs cross this
    slice.
    """

    schema: Literal["kaliv-consciousness-core/context-packet/v1"]
    cycle_id: CycleId
    self_state: PersistentSelfState
    world_state: RuntimeWorldState
    workspace: CognitiveWorkspace
    personality_snapshot: PersonalitySnapshot
    relevant_memory_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    embodiment_state_ref: NonEmptyRef | None
    continuity: ContinuityContextProjection | None = None
    production_activation: Literal[False]

    @model_validator(mode="after")
    def validate_cycle_and_refs(self) -> "CognitiveContextPacket":
        if self.workspace.cycle_id != self.cycle_id:
            raise ValueError("workspace belongs to another cognitive cycle")
        if len(self.relevant_memory_refs) != len(set(self.relevant_memory_refs)):
            raise ValueError("relevant memory refs must be unique")
        return self


class CognitiveCycleReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/cycle-receipt/v1"]
    cycle_id: CycleId
    request_id: Annotated[str, Field(pattern=r"^thinkreq-[a-f0-9]{32}$")]
    self_state_ref: NonEmptyRef
    world_state_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    personality_state_ref: NonEmptyRef
    cognitive_profile_ref: NonEmptyRef
    proposal_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    self_revision_before: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after: Annotated[int, Field(ge=1, strict=True)]
    self_state_unchanged: Literal[True]
    model_state_mutation_applied: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]


class CognitiveCycleResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/cycle-result/v1"]
    request: ThoughtRequest
    proposal: ThoughtProposal
    receipt: CognitiveCycleReceipt
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


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:{_digest(value)}"


def self_state_ref(state: PersistentSelfState | Mapping[str, Any]) -> str:
    parsed = (
        state
        if isinstance(state, PersistentSelfState)
        else PersistentSelfState.model_validate(state)
    )
    return _ref("self-state", parsed)


def world_state_ref(state: RuntimeWorldState | Mapping[str, Any]) -> str:
    parsed = (
        state
        if isinstance(state, RuntimeWorldState)
        else RuntimeWorldState.model_validate(state)
    )
    return _ref("world-state", parsed)


def workspace_ref(workspace: CognitiveWorkspace | Mapping[str, Any]) -> str:
    parsed = (
        workspace
        if isinstance(workspace, CognitiveWorkspace)
        else CognitiveWorkspace.model_validate(workspace)
    )
    return _ref("workspace", parsed)


def cognitive_profile_ref(profile: CognitiveProfile | Mapping[str, Any]) -> str:
    parsed = (
        profile
        if isinstance(profile, CognitiveProfile)
        else CognitiveProfile.model_validate(profile)
    )
    return _ref("cognitive-profile", parsed)


def proposal_ref(proposal: ThoughtProposal | Mapping[str, Any]) -> str:
    parsed = (
        proposal
        if isinstance(proposal, ThoughtProposal)
        else ThoughtProposal.model_validate(proposal)
    )
    return _ref("thought-proposal", parsed)


def build_workspace(
    *,
    cycle_id: str,
    candidates: list[WorkspaceCandidate | Mapping[str, Any]],
    max_active: int = 8,
) -> CognitiveWorkspace:
    """Select attention deterministically: highest salience, stable id tie-break."""
    try:
        parsed = [
            item
            if isinstance(item, WorkspaceCandidate)
            else WorkspaceCandidate.model_validate(item)
            for item in candidates
        ]
        if not 1 <= max_active <= 16:
            raise CognitiveCycleError("max_active must be between 1 and 16")
        if len(parsed) > 256:
            raise CognitiveCycleError("workspace candidate bound exceeded")
        ids = [item.candidate_id for item in parsed]
        if len(ids) != len(set(ids)):
            raise CognitiveCycleError("workspace candidate ids must be unique")
        selected = sorted(
            parsed,
            key=lambda item: (-item.salience, item.candidate_id),
        )[:max_active]
        return CognitiveWorkspace(
            schema="kaliv-consciousness-core/workspace/v1",
            cycle_id=cycle_id,
            candidates=parsed,
            selected_candidate_ids=[item.candidate_id for item in selected],
            max_active=max_active,
            production_activation=False,
        )
    except ValidationError as exc:
        raise CognitiveCycleError("invalid cognitive workspace input") from exc


def assemble_thought_request(
    *,
    state: PersistentSelfState | Mapping[str, Any],
    world: RuntimeWorldState | Mapping[str, Any],
    workspace: CognitiveWorkspace | Mapping[str, Any],
    personality_snapshot: PersonalitySnapshot | Mapping[str, Any],
    profile: CognitiveProfile | Mapping[str, Any],
    relevant_memory_refs: list[str] | None = None,
    embodiment_state_ref: str | None = None,
    continuity_state: PostWakeContinuityState | Mapping[str, Any] | None = None,
    requested_reasoning_mode: ReasoningMode = "normal",
) -> tuple[ThoughtRequest, CognitiveContextPacket]:
    """Materialize one exact context packet and its reference-only C3 request."""
    try:
        current = (
            state
            if isinstance(state, PersistentSelfState)
            else PersistentSelfState.model_validate(state)
        )
        world_value = (
            world
            if isinstance(world, RuntimeWorldState)
            else RuntimeWorldState.model_validate(world)
        )
        workspace_value = (
            workspace
            if isinstance(workspace, CognitiveWorkspace)
            else CognitiveWorkspace.model_validate(workspace)
        )
        personality = (
            personality_snapshot
            if isinstance(personality_snapshot, PersonalitySnapshot)
            else PersonalitySnapshot.model_validate(personality_snapshot)
        )
        profile_value = (
            profile
            if isinstance(profile, CognitiveProfile)
            else CognitiveProfile.model_validate(profile)
        )
        continuity_value = (
            None
            if continuity_state is None
            else continuity_state
            if isinstance(continuity_state, PostWakeContinuityState)
            else PostWakeContinuityState.model_validate(continuity_state)
        )
    except ValidationError as exc:
        raise CognitiveCycleError("invalid cognitive-cycle input") from exc

    world_ref = world_state_ref(world_value)
    active_workspace_ref = workspace_ref(workspace_value)
    current_self_ref = self_state_ref(current)
    profile_ref = cognitive_profile_ref(profile_value)

    if current.world_state_ref != world_ref:
        raise CognitiveCycleError("SelfState is not bound to this exact WorldState")
    if current.workspace_ref != active_workspace_ref:
        raise CognitiveCycleError("SelfState is not bound to this exact CognitiveWorkspace")
    if current.personality_state_ref != personality.personality_state_ref:
        raise CognitiveCycleError("SelfState is not bound to this PersonalityState")
    if current.person_revision != personality.person_revision:
        raise CognitiveCycleError("personality snapshot belongs to another Person Revision")

    continuity_projection = None
    if continuity_value is not None:
        if continuity_value.self_id != current.self_id:
            raise CognitiveCycleError(
                "continuity state belongs to another self"
            )
        if continuity_value.person_revision != current.person_revision:
            raise CognitiveCycleError(
                "continuity state belongs to another Person Revision"
            )
        continuity_projection = project_continuity_context(
            continuity_value
        )

    memories = list(dict.fromkeys(relevant_memory_refs or []))
    if len(memories) > 64:
        raise CognitiveCycleError("relevant memory ref bound exceeded")

    packet = CognitiveContextPacket(
        schema="kaliv-consciousness-core/context-packet/v1",
        cycle_id=workspace_value.cycle_id,
        self_state=current,
        world_state=world_value,
        workspace=workspace_value,
        personality_snapshot=personality,
        relevant_memory_refs=memories,
        embodiment_state_ref=embodiment_state_ref,
        continuity=continuity_projection,
        production_activation=False,
    )

    request_seed = {
        "cycle_id": workspace_value.cycle_id,
        "self_state_ref": current_self_ref,
        "world_state_ref": world_ref,
        "workspace_ref": active_workspace_ref,
        "personality_snapshot": personality.model_dump(mode="json"),
        "relevant_memory_refs": memories,
        "embodiment_state_ref": embodiment_state_ref,
        "cognitive_profile_ref": profile_ref,
        "requested_reasoning_mode": requested_reasoning_mode,
    }
    request = ThoughtRequest(
        schema="kaliv-consciousness-core/thought-request/v1",
        request_id="thinkreq-" + _digest(request_seed)[:32],
        cycle_id=workspace_value.cycle_id,
        self_state_ref=current_self_ref,
        world_state_ref=world_ref,
        workspace_ref=active_workspace_ref,
        personality_snapshot=personality,
        relevant_memory_refs=memories,
        embodiment_state_ref=embodiment_state_ref,
        cognitive_profile_ref=profile_ref,
        requested_reasoning_mode=requested_reasoning_mode,
        production_activation=False,
    )
    return request, packet


class CognitiveCycleCoordinator:
    """Run one bounded inner-monologue cycle and apply zero model mutations."""

    def __init__(self, runtime: ConsciousnessCoreRuntime) -> None:
        if not isinstance(runtime, ConsciousnessCoreRuntime):
            raise TypeError("runtime must be ConsciousnessCoreRuntime")
        self._runtime = runtime

    async def run(
        self,
        *,
        state: PersistentSelfState | Mapping[str, Any],
        world: RuntimeWorldState | Mapping[str, Any],
        workspace: CognitiveWorkspace | Mapping[str, Any],
        personality_snapshot: PersonalitySnapshot | Mapping[str, Any],
        profile: CognitiveProfile | Mapping[str, Any],
        relevant_memory_refs: list[str] | None = None,
        embodiment_state_ref: str | None = None,
        continuity_state: PostWakeContinuityState | Mapping[str, Any] | None = None,
        requested_reasoning_mode: ReasoningMode = "normal",
    ) -> CognitiveCycleResult:
        try:
            current = (
                state
                if isinstance(state, PersistentSelfState)
                else PersistentSelfState.model_validate(state)
            )
            profile_value = (
                profile
                if isinstance(profile, CognitiveProfile)
                else CognitiveProfile.model_validate(profile)
            )
        except ValidationError as exc:
            raise CognitiveCycleError("invalid cognitive-cycle runtime input") from exc

        before_ref = self_state_ref(current)
        before_revision = current.revision
        request, packet = assemble_thought_request(
            state=current,
            world=world,
            workspace=workspace,
            personality_snapshot=personality_snapshot,
            profile=profile_value,
            relevant_memory_refs=relevant_memory_refs,
            embodiment_state_ref=embodiment_state_ref,
            continuity_state=continuity_state,
            requested_reasoning_mode=requested_reasoning_mode,
        )

        context_payload = packet.model_dump(mode="json")
        if packet.continuity is None:
            # Keep pre-C29-F no-continuity model context shape unchanged.
            context_payload.pop("continuity", None)

        proposal = await self._runtime.think(
            request,
            profile_value,
            context=context_payload,
        )

        # The ThoughtEngine never receives the SelfState object by reference, but
        # re-hash anyway so the receipt proves the coordinator did not mutate it.
        after_ref = self_state_ref(current)
        if after_ref != before_ref or current.revision != before_revision:
            raise CognitiveCycleError("SelfState changed during model cognition")

        receipt = CognitiveCycleReceipt(
            schema="kaliv-consciousness-core/cycle-receipt/v1",
            cycle_id=request.cycle_id,
            request_id=request.request_id,
            self_state_ref=before_ref,
            world_state_ref=request.world_state_ref,
            workspace_ref=request.workspace_ref,
            personality_state_ref=request.personality_snapshot.personality_state_ref,
            cognitive_profile_ref=request.cognitive_profile_ref,
            proposal_ref=proposal_ref(proposal),
            self_id=current.self_id,
            person_id=current.person_id,
            person_revision=current.person_revision,
            self_revision_before=before_revision,
            self_revision_after=current.revision,
            self_state_unchanged=True,
            model_state_mutation_applied=False,
            execution_authority=False,
            scheduling_authority=False,
            durable_memory_write_authority=False,
            raw_chain_of_thought_persisted=False,
            production_activation=False,
        )
        return CognitiveCycleResult(
            schema="kaliv-consciousness-core/cycle-result/v1",
            request=request,
            proposal=proposal,
            receipt=receipt,
            production_activation=False,
        )
