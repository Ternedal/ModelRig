"""C16 deterministic post-cycle reducer for Consciousness Core.

C15 lets a replaceable ThoughtEngine produce one bounded ThoughtProposal. C16
turns that verified result into the next in-memory cognitive workspace through
Core-owned deterministic policy. The model still has no persistent-state,
durable-memory, scheduler, tool, body, voice, or execution authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Mapping, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .cycle import (
    CognitiveCycleResult,
    CognitiveWorkspace,
    WorkspaceCandidate,
    build_workspace,
    proposal_ref,
    self_state_ref,
    workspace_ref,
)
from .self_state import PersistentSelfState, advance_self_state


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
CandidateId = Annotated[str, Field(pattern=r"^wc-[a-f0-9]{32}$")]

_MAX_CARRIED_CANDIDATES = 31
_ATTENTION_BOOST = 0.05


class PostCycleReductionError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CognitiveTransitionReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/cognitive-transition-receipt/v1"]
    from_cycle_id: CycleId
    to_cycle_id: CycleId
    proposal_ref: NonEmptyRef
    previous_self_state_ref: NonEmptyRef
    next_self_state_ref: NonEmptyRef
    previous_workspace_ref: NonEmptyRef
    next_workspace_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    self_revision_before: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after: Annotated[int, Field(ge=2, strict=True)]
    carried_candidate_ids: Annotated[list[CandidateId], Field(max_length=31)]
    accepted_attention_targets: Annotated[list[NonEmptyRef], Field(max_length=32)]
    thought_result_candidate_id: CandidateId
    identity_unchanged: Literal[True]
    world_binding_unchanged: Literal[True]
    personality_binding_unchanged: Literal[True]
    goal_bindings_unchanged: Literal[True]
    intention_bindings_unchanged: Literal[True]
    affect_unchanged: Literal[True]
    durable_memory_binding_unchanged: Literal[True]
    model_state_mutation_applied: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]


class PostCycleReductionResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/post-cycle-reduction/v1"]
    next_workspace: CognitiveWorkspace
    next_self_state: PersistentSelfState
    receipt: CognitiveTransitionReceipt
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


def _next_cycle_id(*, current_cycle_id: str, proposal_reference: str) -> str:
    return "cycle-" + _digest(
        {
            "from_cycle_id": current_cycle_id,
            "proposal_ref": proposal_reference,
            "transition": "post-cycle-reducer-v1",
        }
    )[:32]


def _thought_candidate_id(*, current_cycle_id: str, proposal_reference: str) -> str:
    return "wc-" + _digest(
        {
            "from_cycle_id": current_cycle_id,
            "proposal_ref": proposal_reference,
            "kind": "thought_result",
        }
    )[:32]


def _bounded_interpretation(result: CognitiveCycleResult) -> str:
    text = result.proposal.interpretation.strip()
    if not text:
        text = f"Completed thought proposal {result.proposal.proposal_id}."
    return text[:2048]


def _accepted_attention_targets(
    workspace: CognitiveWorkspace,
    suggestions: list[str],
) -> list[str]:
    known: set[str] = set()
    for candidate in workspace.candidates:
        known.add(candidate.candidate_id)
        known.add(candidate.source_ref)
    return list(dict.fromkeys(item for item in suggestions if item in known))[:32]


def _carry_candidates(
    workspace: CognitiveWorkspace,
    *,
    accepted_attention_targets: list[str],
) -> list[WorkspaceCandidate]:
    accepted = set(accepted_attention_targets)
    adjusted: list[WorkspaceCandidate] = []
    for candidate in workspace.candidates:
        salience = candidate.salience
        if (
            candidate.candidate_id in accepted
            or candidate.source_ref in accepted
        ):
            salience = min(1.0, salience + _ATTENTION_BOOST)
        adjusted.append(
            candidate.model_copy(update={"salience": float(salience)})
        )

    adjusted.sort(key=lambda item: (-item.salience, item.candidate_id))
    return adjusted[:_MAX_CARRIED_CANDIDATES]


def _validate_bindings(
    *,
    result: CognitiveCycleResult,
    state: PersistentSelfState,
    workspace: CognitiveWorkspace,
) -> tuple[str, str, str]:
    state_reference = self_state_ref(state)
    workspace_reference = workspace_ref(workspace)
    current_proposal_ref = proposal_ref(result.proposal)

    if result.request.cycle_id != workspace.cycle_id:
        raise PostCycleReductionError("cycle result belongs to another workspace cycle")
    if result.receipt.cycle_id != result.request.cycle_id:
        raise PostCycleReductionError("cycle receipt belongs to another request cycle")
    if result.proposal.request_id != result.request.request_id:
        raise PostCycleReductionError("proposal belongs to another ThoughtRequest")
    if result.receipt.request_id != result.request.request_id:
        raise PostCycleReductionError("cycle receipt belongs to another ThoughtRequest")
    if result.receipt.proposal_ref != current_proposal_ref:
        raise PostCycleReductionError("cycle receipt proposal binding mismatch")

    if result.request.self_state_ref != state_reference:
        raise PostCycleReductionError("ThoughtRequest is not bound to current SelfState")
    if result.receipt.self_state_ref != state_reference:
        raise PostCycleReductionError("CycleReceipt is not bound to current SelfState")
    if result.request.workspace_ref != workspace_reference:
        raise PostCycleReductionError("ThoughtRequest is not bound to current workspace")
    if result.receipt.workspace_ref != workspace_reference:
        raise PostCycleReductionError("CycleReceipt is not bound to current workspace")
    if state.workspace_ref != workspace_reference:
        raise PostCycleReductionError("SelfState does not point at current workspace")

    if result.receipt.self_id != state.self_id:
        raise PostCycleReductionError("CycleReceipt belongs to another self")
    if result.receipt.person_id != state.person_id:
        raise PostCycleReductionError("CycleReceipt belongs to another person")
    if result.receipt.person_revision != state.person_revision:
        raise PostCycleReductionError("CycleReceipt belongs to another Person Revision")
    if (
        result.receipt.self_revision_before != state.revision
        or result.receipt.self_revision_after != state.revision
    ):
        raise PostCycleReductionError("CycleReceipt SelfState revision mismatch")

    return state_reference, workspace_reference, current_proposal_ref


def reduce_post_cycle(
    result: CognitiveCycleResult | Mapping[str, Any],
    *,
    current_state: PersistentSelfState | Mapping[str, Any],
    current_workspace: CognitiveWorkspace | Mapping[str, Any],
) -> PostCycleReductionResult:
    """Advance only the Core-owned transient workspace binding.

    The ThoughtProposal is evidence for cognition, not authority. C16 accepts
    model attention suggestions only when they refer to already-known workspace
    material and applies a fixed bounded Core policy. The only SelfState field
    changed here is workspace_ref (plus the mandatory revision increment).
    """

    try:
        cycle_result = (
            result
            if isinstance(result, CognitiveCycleResult)
            else CognitiveCycleResult.model_validate(result)
        )
        state = (
            current_state
            if isinstance(current_state, PersistentSelfState)
            else PersistentSelfState.model_validate(current_state)
        )
        workspace = (
            current_workspace
            if isinstance(current_workspace, CognitiveWorkspace)
            else CognitiveWorkspace.model_validate(current_workspace)
        )
    except ValidationError as exc:
        raise PostCycleReductionError("invalid post-cycle reduction input") from exc

    (
        previous_state_ref,
        previous_workspace_ref,
        current_proposal_ref,
    ) = _validate_bindings(
        result=cycle_result,
        state=state,
        workspace=workspace,
    )

    accepted_targets = _accepted_attention_targets(
        workspace,
        cycle_result.proposal.attention_suggestions,
    )
    carried = _carry_candidates(
        workspace,
        accepted_attention_targets=accepted_targets,
    )

    next_cycle_id = _next_cycle_id(
        current_cycle_id=workspace.cycle_id,
        proposal_reference=current_proposal_ref,
    )
    thought_id = _thought_candidate_id(
        current_cycle_id=workspace.cycle_id,
        proposal_reference=current_proposal_ref,
    )
    if thought_id in {item.candidate_id for item in carried}:
        raise PostCycleReductionError("deterministic thought candidate id collision")

    # Model uncertainty can influence how prominent its own transient thought
    # result is, but only inside a narrow Core-owned salience band [0.60, 0.90].
    thought_salience = float(
        0.60 + (1.0 - cycle_result.proposal.uncertainty) * 0.30
    )
    thought_candidate = WorkspaceCandidate(
        candidate_id=thought_id,
        kind="thought_result",
        salience=thought_salience,
        summary=_bounded_interpretation(cycle_result),
        source_ref=current_proposal_ref,
    )

    next_workspace = build_workspace(
        cycle_id=next_cycle_id,
        candidates=[*carried, thought_candidate],
        max_active=workspace.max_active,
    )
    next_workspace_reference = workspace_ref(next_workspace)

    next_state = advance_self_state(
        state,
        workspace_ref=next_workspace_reference,
    )

    # Guard the reducer's own authority boundary explicitly.
    if next_state.self_id != state.self_id or next_state.person_id != state.person_id:
        raise PostCycleReductionError("post-cycle transition changed identity")
    if next_state.person_revision != state.person_revision:
        raise PostCycleReductionError("post-cycle transition changed Person Revision")
    if next_state.personality_state_ref != state.personality_state_ref:
        raise PostCycleReductionError("post-cycle transition changed personality binding")
    if next_state.world_state_ref != state.world_state_ref:
        raise PostCycleReductionError("post-cycle transition changed world binding")
    if next_state.active_goal_refs != state.active_goal_refs:
        raise PostCycleReductionError("post-cycle transition changed goal bindings")
    if next_state.active_intention_refs != state.active_intention_refs:
        raise PostCycleReductionError("post-cycle transition changed intention bindings")
    if next_state.affect != state.affect:
        raise PostCycleReductionError("post-cycle transition changed affect")
    if next_state.known_uncertainties != state.known_uncertainties:
        raise PostCycleReductionError("post-cycle transition changed durable uncertainties")
    if next_state.last_experience_ref != state.last_experience_ref:
        raise PostCycleReductionError("post-cycle transition changed memory binding")
    if next_state.revision != state.revision + 1:
        raise PostCycleReductionError("post-cycle transition revision is not monotonic")

    receipt = CognitiveTransitionReceipt(
        schema="kaliv-consciousness-core/cognitive-transition-receipt/v1",
        from_cycle_id=workspace.cycle_id,
        to_cycle_id=next_workspace.cycle_id,
        proposal_ref=current_proposal_ref,
        previous_self_state_ref=previous_state_ref,
        next_self_state_ref=self_state_ref(next_state),
        previous_workspace_ref=previous_workspace_ref,
        next_workspace_ref=next_workspace_reference,
        self_id=state.self_id,
        person_id=state.person_id,
        person_revision=state.person_revision,
        self_revision_before=state.revision,
        self_revision_after=next_state.revision,
        carried_candidate_ids=[item.candidate_id for item in carried],
        accepted_attention_targets=accepted_targets,
        thought_result_candidate_id=thought_id,
        identity_unchanged=True,
        world_binding_unchanged=True,
        personality_binding_unchanged=True,
        goal_bindings_unchanged=True,
        intention_bindings_unchanged=True,
        affect_unchanged=True,
        durable_memory_binding_unchanged=True,
        model_state_mutation_applied=False,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        raw_chain_of_thought_persisted=False,
        production_activation=False,
    )
    return PostCycleReductionResult(
        schema="kaliv-consciousness-core/post-cycle-reduction/v1",
        next_workspace=next_workspace,
        next_self_state=next_state,
        receipt=receipt,
        production_activation=False,
    )
