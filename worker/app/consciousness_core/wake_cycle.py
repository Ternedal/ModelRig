"""C17 wake reorientation and first cognitive-cycle bridge.

A WakeReceipt is temporal continuity evidence, not evidence that cognition occurred
while the process was off. C17 turns that verified wake boundary into bounded
workspace material, advances only the in-memory workspace binding, runs exactly
one C15 cognitive cycle, and delegates the next-state transition to C16.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import CognitiveProfile, PersonalitySnapshot
from .continuity import build_post_wake_continuity_state
from .cycle import (
    CognitiveCycleCoordinator,
    CognitiveCycleResult,
    CognitiveWorkspace,
    RuntimeWorldState,
    WorkspaceCandidate,
    build_workspace,
    proposal_ref,
    self_state_ref,
    workspace_ref,
)
from .reducer import PostCycleReductionResult, reduce_post_cycle
from .runtime import ConsciousnessCoreRuntime
from .self_state import PersistentSelfState, advance_self_state
from .sleep import WakeReceipt


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CycleId = Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
CandidateId = Annotated[str, Field(pattern=r"^wc-[a-f0-9]{32}$")]

_MAX_PRIOR_CANDIDATES = 31
_MAX_WAKE_REFS_PER_CLASS = 16


class WakeCycleError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class WakeOrientationReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/wake-orientation-receipt/v1"]
    wake_receipt_ref: NonEmptyRef
    from_cycle_id: CycleId
    oriented_cycle_id: CycleId
    previous_self_state_ref: NonEmptyRef
    oriented_self_state_ref: NonEmptyRef
    previous_workspace_ref: NonEmptyRef
    oriented_workspace_ref: NonEmptyRef
    wake_candidate_id: CandidateId
    carried_candidate_ids: Annotated[list[CandidateId], Field(max_length=31)]
    resume_goal_refs_exposed: Annotated[list[NonEmptyRef], Field(max_length=16)]
    resume_open_loop_refs_exposed: Annotated[list[NonEmptyRef], Field(max_length=16)]
    pending_review_refs_exposed: Annotated[list[NonEmptyRef], Field(max_length=16)]
    self_revision_before: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after: Annotated[int, Field(ge=2, strict=True)]
    cognition_during_gap: Literal[False]
    automatic_goal_resume: Literal[False]
    automatic_loop_resume: Literal[False]
    self_state_store_write_applied: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]


class WakeOrientationResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/wake-orientation-result/v1"]
    oriented_workspace: CognitiveWorkspace
    oriented_self_state: PersistentSelfState
    receipt: WakeOrientationReceipt
    production_activation: Literal[False]


class WakeFirstCycleReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/wake-first-cycle-receipt/v1"]
    wake_receipt_ref: NonEmptyRef
    orientation_receipt_ref: NonEmptyRef
    first_cycle_id: CycleId
    thought_proposal_ref: NonEmptyRef
    transition_receipt_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    self_revision_before_wake: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after_orientation: Annotated[int, Field(ge=2, strict=True)]
    self_revision_after_first_cycle: Annotated[int, Field(ge=3, strict=True)]
    thought_engine_calls: Literal[1]
    cognition_during_gap: Literal[False]
    automatic_goal_resume: Literal[False]
    automatic_loop_resume: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]


class WakeFirstCycleResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/wake-first-cycle-result/v1"]
    orientation: WakeOrientationResult
    cognitive_cycle: CognitiveCycleResult
    reduction: PostCycleReductionResult
    receipt: WakeFirstCycleReceipt
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


def wake_receipt_ref(receipt: WakeReceipt | Mapping[str, Any]) -> str:
    try:
        wake = (
            receipt
            if isinstance(receipt, WakeReceipt)
            else WakeReceipt.model_validate(receipt)
        )
    except ValidationError as exc:
        raise WakeCycleError("invalid WakeReceipt") from exc
    return _ref("wake-receipt", wake)


def _candidate_id(*, wake_ref: str, role: str, source_ref: str) -> str:
    return "wc-" + _digest(
        {
            "wake_receipt_ref": wake_ref,
            "role": role,
            "source_ref": source_ref,
        }
    )[:32]


def _orientation_cycle_id(*, prior_cycle_id: str, wake_ref: str) -> str:
    return "cycle-" + _digest(
        {
            "prior_cycle_id": prior_cycle_id,
            "wake_receipt_ref": wake_ref,
            "transition": "wake-orientation-v1",
        }
    )[:32]


def _duration_summary(wake: WakeReceipt) -> str:
    if wake.duration_known and wake.offline_duration_ms is not None:
        duration = f"{wake.offline_duration_ms} ms"
    else:
        duration = "unknown"
    return (
        f"Wake reorientation after {wake.dormancy_kind}; offline duration "
        f"{duration}; cognition during the gap was false."
    )


def _reference_candidates(
    *,
    wake_ref: str,
    role: str,
    refs: list[str],
    kind: Literal["goal", "memory"],
    salience: float,
    summary: str,
) -> list[WorkspaceCandidate]:
    out: list[WorkspaceCandidate] = []
    for source_ref in list(dict.fromkeys(refs))[:_MAX_WAKE_REFS_PER_CLASS]:
        out.append(
            WorkspaceCandidate(
                candidate_id=_candidate_id(
                    wake_ref=wake_ref,
                    role=role,
                    source_ref=source_ref,
                ),
                kind=kind,
                salience=salience,
                summary=summary,
                source_ref=source_ref,
            )
        )
    return out


def build_wake_orientation(
    *,
    wake_receipt: WakeReceipt | Mapping[str, Any],
    current_state: PersistentSelfState | Mapping[str, Any],
    current_workspace: CognitiveWorkspace | Mapping[str, Any],
) -> WakeOrientationResult:
    """Create bounded wake context without resuming or executing anything."""

    try:
        wake = (
            wake_receipt
            if isinstance(wake_receipt, WakeReceipt)
            else WakeReceipt.model_validate(wake_receipt)
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
        raise WakeCycleError("invalid wake-orientation input") from exc

    if wake.self_id != state.self_id:
        raise WakeCycleError("WakeReceipt belongs to another self")
    if wake.person_revision != state.person_revision:
        raise WakeCycleError("WakeReceipt belongs to another Person Revision")
    if wake.cognition_during_gap is not False:
        raise WakeCycleError("WakeReceipt may not claim cognition during powered-off gap")

    prior_workspace_ref = workspace_ref(workspace)
    if state.workspace_ref != prior_workspace_ref:
        raise WakeCycleError("SelfState is not bound to current wake workspace")

    wake_ref = wake_receipt_ref(wake)
    carried = sorted(
        workspace.candidates,
        key=lambda item: (-item.salience, item.candidate_id),
    )[:_MAX_PRIOR_CANDIDATES]

    wake_candidate = WorkspaceCandidate(
        candidate_id=_candidate_id(
            wake_ref=wake_ref,
            role="wake",
            source_ref=wake_ref,
        ),
        kind="perception",
        salience=1.0,
        summary=_duration_summary(wake),
        source_ref=wake_ref,
    )
    goal_candidates = _reference_candidates(
        wake_ref=wake_ref,
        role="resume-goal-ref",
        refs=wake.resume_goal_refs,
        kind="goal",
        salience=0.90,
        summary=(
            "Goal reference was open before dormancy; wake does not automatically "
            "resume, select, complete, or execute it."
        ),
    )
    loop_candidates = _reference_candidates(
        wake_ref=wake_ref,
        role="resume-open-loop-ref",
        refs=wake.resume_open_loop_refs,
        kind="memory",
        salience=0.78,
        summary=(
            "Open-loop reference crossed dormancy as continuity context only; "
            "no work was executed during the gap."
        ),
    )
    review_candidates = _reference_candidates(
        wake_ref=wake_ref,
        role="pending-review-ref",
        refs=wake.pending_review_refs,
        kind="memory",
        salience=0.74,
        summary=(
            "Pending-review reference survived dormancy and still requires its "
            "original review authority."
        ),
    )

    oriented_cycle_id = _orientation_cycle_id(
        prior_cycle_id=workspace.cycle_id,
        wake_ref=wake_ref,
    )
    oriented_workspace = build_workspace(
        cycle_id=oriented_cycle_id,
        candidates=[
            wake_candidate,
            *goal_candidates,
            *loop_candidates,
            *review_candidates,
            *carried,
        ],
        max_active=workspace.max_active,
    )
    oriented_workspace_ref = workspace_ref(oriented_workspace)
    oriented_state = advance_self_state(
        state,
        workspace_ref=oriented_workspace_ref,
    )

    if oriented_state.self_id != state.self_id:
        raise WakeCycleError("wake orientation changed self identity")
    if oriented_state.person_id != state.person_id:
        raise WakeCycleError("wake orientation changed person identity")
    if oriented_state.person_revision != state.person_revision:
        raise WakeCycleError("wake orientation changed Person Revision")
    if oriented_state.personality_state_ref != state.personality_state_ref:
        raise WakeCycleError("wake orientation changed personality binding")
    if oriented_state.world_state_ref != state.world_state_ref:
        raise WakeCycleError("wake orientation changed world binding")
    if oriented_state.active_goal_refs != state.active_goal_refs:
        raise WakeCycleError("wake orientation changed active goals")
    if oriented_state.active_intention_refs != state.active_intention_refs:
        raise WakeCycleError("wake orientation changed active intentions")
    if oriented_state.affect != state.affect:
        raise WakeCycleError("wake orientation changed affect")
    if oriented_state.known_uncertainties != state.known_uncertainties:
        raise WakeCycleError("wake orientation changed durable uncertainties")
    if oriented_state.last_experience_ref != state.last_experience_ref:
        raise WakeCycleError("wake orientation changed memory binding")

    receipt = WakeOrientationReceipt(
        schema="kaliv-consciousness-core/wake-orientation-receipt/v1",
        wake_receipt_ref=wake_ref,
        from_cycle_id=workspace.cycle_id,
        oriented_cycle_id=oriented_workspace.cycle_id,
        previous_self_state_ref=self_state_ref(state),
        oriented_self_state_ref=self_state_ref(oriented_state),
        previous_workspace_ref=prior_workspace_ref,
        oriented_workspace_ref=oriented_workspace_ref,
        wake_candidate_id=wake_candidate.candidate_id,
        carried_candidate_ids=[item.candidate_id for item in carried],
        resume_goal_refs_exposed=[
            item.source_ref for item in goal_candidates
        ],
        resume_open_loop_refs_exposed=[
            item.source_ref for item in loop_candidates
        ],
        pending_review_refs_exposed=[
            item.source_ref for item in review_candidates
        ],
        self_revision_before=state.revision,
        self_revision_after=oriented_state.revision,
        cognition_during_gap=False,
        automatic_goal_resume=False,
        automatic_loop_resume=False,
        self_state_store_write_applied=False,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )
    return WakeOrientationResult(
        schema="kaliv-consciousness-core/wake-orientation-result/v1",
        oriented_workspace=oriented_workspace,
        oriented_self_state=oriented_state,
        receipt=receipt,
        production_activation=False,
    )


class WakeFirstCycleCoordinator:
    """Run exactly one cognition cycle after deterministic wake reorientation."""

    def __init__(self, runtime: ConsciousnessCoreRuntime) -> None:
        if not isinstance(runtime, ConsciousnessCoreRuntime):
            raise TypeError("runtime must be ConsciousnessCoreRuntime")
        self._cycle = CognitiveCycleCoordinator(runtime)

    async def run(
        self,
        *,
        wake_receipt: WakeReceipt | Mapping[str, Any],
        current_state: PersistentSelfState | Mapping[str, Any],
        current_world: RuntimeWorldState | Mapping[str, Any],
        current_workspace: CognitiveWorkspace | Mapping[str, Any],
        personality_snapshot: PersonalitySnapshot | Mapping[str, Any],
        profile: CognitiveProfile | Mapping[str, Any],
        relevant_memory_refs: list[str] | None = None,
        embodiment_state_ref: str | None = None,
    ) -> WakeFirstCycleResult:
        orientation = build_wake_orientation(
            wake_receipt=wake_receipt,
            current_state=current_state,
            current_workspace=current_workspace,
        )
        wake = (
            wake_receipt
            if isinstance(wake_receipt, WakeReceipt)
            else WakeReceipt.model_validate(wake_receipt)
        )
        continuity_state = build_post_wake_continuity_state(
            wake,
            expected_self_id=orientation.oriented_self_state.self_id,
            expected_person_revision=(
                orientation.oriented_self_state.person_revision
            ),
        )

        cycle_result = await self._cycle.run(
            state=orientation.oriented_self_state,
            world=current_world,
            workspace=orientation.oriented_workspace,
            personality_snapshot=personality_snapshot,
            profile=profile,
            relevant_memory_refs=relevant_memory_refs,
            embodiment_state_ref=embodiment_state_ref,
            continuity_state=continuity_state,
            requested_reasoning_mode="verify",
        )
        reduction = reduce_post_cycle(
            cycle_result,
            current_state=orientation.oriented_self_state,
            current_workspace=orientation.oriented_workspace,
        )

        final_state = reduction.next_self_state
        initial_state = (
            current_state
            if isinstance(current_state, PersistentSelfState)
            else PersistentSelfState.model_validate(current_state)
        )
        if final_state.self_id != initial_state.self_id:
            raise WakeCycleError("first wake cycle changed self identity")
        if final_state.person_id != initial_state.person_id:
            raise WakeCycleError("first wake cycle changed person identity")
        if final_state.person_revision != initial_state.person_revision:
            raise WakeCycleError("first wake cycle changed Person Revision")
        if final_state.revision != initial_state.revision + 2:
            raise WakeCycleError("wake + first-cycle revision sequence is invalid")

        transition_ref = _ref(
            "cognitive-transition-receipt",
            reduction.receipt,
        )
        orientation_ref = _ref(
            "wake-orientation-receipt",
            orientation.receipt,
        )
        receipt = WakeFirstCycleReceipt(
            schema="kaliv-consciousness-core/wake-first-cycle-receipt/v1",
            wake_receipt_ref=wake_receipt_ref(wake),
            orientation_receipt_ref=orientation_ref,
            first_cycle_id=cycle_result.receipt.cycle_id,
            thought_proposal_ref=proposal_ref(cycle_result.proposal),
            transition_receipt_ref=transition_ref,
            self_id=initial_state.self_id,
            person_id=initial_state.person_id,
            person_revision=initial_state.person_revision,
            self_revision_before_wake=initial_state.revision,
            self_revision_after_orientation=orientation.oriented_self_state.revision,
            self_revision_after_first_cycle=final_state.revision,
            thought_engine_calls=1,
            cognition_during_gap=False,
            automatic_goal_resume=False,
            automatic_loop_resume=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            raw_chain_of_thought_persisted=False,
            production_activation=False,
        )
        return WakeFirstCycleResult(
            schema="kaliv-consciousness-core/wake-first-cycle-result/v1",
            orientation=orientation,
            cognitive_cycle=cycle_result,
            reduction=reduction,
            receipt=receipt,
            production_activation=False,
        )
