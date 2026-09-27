"""C31-H privacy-safe operator status and capability qualification.

This closes the C31 lived-continuity stack with two read-only surfaces:
- a compact operator status built only from already-issued C31 evidence; and
- a static capability manifest describing the C31-A..G authority contract.

Neither surface creates runtime work, exposes raw cognitive/user content, persists
state, calls a model, or grants identity, memory, scheduling, or execution authority.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .continuous_loop_supervisor import (
    CONTINUOUS_LOOP_FLAG,
    ContinuousLoopSupervisorPlan,
)
from .dormancy_bridge import DormancyBridgeReceipt
from .episode_carry_forward import EpisodeCarryForwardPlan
from .lived_continuity import LivedContinuityReceipt
from .lived_continuity_transition import LivedContinuityTransitionReceipt
from .model_swap_continuity import ModelSwapContinuityReceipt
from .present_context import PresentContextProjection


NonEmpty = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class LivedContinuityOperatorStatus(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/lived-continuity-operator-status/v1"
    ]
    state: Literal[
        "NO_EVIDENCE",
        "CONTINUITY_PRESENT",
        "DORMANCY_PROVEN",
        "LOOP_STEP_PLANNED",
    ]
    continuity_present: bool
    present_context_present: bool
    post_cycle_transition_present: bool
    dormancy_proven: bool
    episode_carry_forward_present: bool
    reviewed_episode_reference_admitted: bool
    continuous_loop_plan_present: bool
    loop_enabled: bool
    loop_disposition: Literal[
        "DISABLED", "IDLE", "DEFER", "RUN_ONE_CYCLE"
    ] | None
    model_swap_qualified: bool
    model_capability_changed: bool
    raw_user_text_included: Literal[False]
    raw_assistant_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    identity_refs_included: Literal[False]
    person_refs_included: Literal[False]
    memory_refs_included: Literal[False]
    episode_refs_included: Literal[False]
    model_refs_included: Literal[False]
    model_calls: Literal[0]
    persistence_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    notification_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "LivedContinuityOperatorStatus":
        if self.loop_disposition is None and self.continuous_loop_plan_present:
            raise ValueError("loop plan presence requires disposition")
        if self.loop_disposition is not None and not self.continuous_loop_plan_present:
            raise ValueError("loop disposition requires plan presence")
        if self.model_capability_changed and not self.model_swap_qualified:
            raise ValueError("capability change requires qualified model swap")
        if self.reviewed_episode_reference_admitted and not self.episode_carry_forward_present:
            raise ValueError("reviewed carry-forward requires carry-forward evidence")
        return self


class LivedContinuityCapabilityManifest(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/lived-continuity-capability-manifest/v1"
    ]
    capability: Literal["C31_LIVED_CONTINUITY_LOOP"]
    slice_start: Literal["C31-A"]
    slice_end: Literal["C31-H"]
    implemented_slices: Annotated[list[NonEmpty], Field(min_length=8, max_length=8)]
    continuous_loop_flag: Literal[
        "KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED"
    ]
    continuous_loop_default_enabled: Literal[False]
    thought_engine_replaceable: Literal[True]
    self_state_identity_preserved_across_model_swap: Literal[True]
    person_binding_preserved_across_model_swap: Literal[True]
    durable_memory_binding_preserved_across_model_swap: Literal[True]
    powered_off_time_is_dormancy: Literal[True]
    cognition_during_gap_allowed: Literal[False]
    explicit_wake_reorientation_required: Literal[True]
    episode_carry_forward_reference_only: Literal[True]
    automatic_durable_memory_write: Literal[False]
    continuous_loop_internal_repeat: Literal[False]
    continuous_loop_internal_timer: Literal[False]
    max_cycles_per_supervisor_plan: Literal[1]
    agent3_execution_required: Literal[True]
    existing_runtime_gates_required: Literal[True]
    raw_chain_of_thought_persisted: Literal[False]
    operator_status_raw_text_included: Literal[False]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    model_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_slices(self) -> "LivedContinuityCapabilityManifest":
        expected = [
            "C31-A",
            "C31-B",
            "C31-C",
            "C31-D",
            "C31-E",
            "C31-F",
            "C31-G",
            "C31-H",
        ]
        if self.implemented_slices != expected:
            raise ValueError("C31 manifest must enumerate exact A-H slice chain")
        return self


def build_lived_continuity_operator_status(
    *,
    continuity: LivedContinuityReceipt | None = None,
    present_context: PresentContextProjection | None = None,
    post_cycle_transition: LivedContinuityTransitionReceipt | None = None,
    dormancy: DormancyBridgeReceipt | None = None,
    carry_forward: EpisodeCarryForwardPlan | None = None,
    loop_plan: ContinuousLoopSupervisorPlan | None = None,
    model_swap: ModelSwapContinuityReceipt | None = None,
) -> LivedContinuityOperatorStatus:
    """Project privacy-safe booleans/state from already-authoritative evidence."""
    if loop_plan is not None:
        state = "LOOP_STEP_PLANNED"
    elif dormancy is not None:
        state = "DORMANCY_PROVEN"
    elif continuity is not None:
        state = "CONTINUITY_PRESENT"
    else:
        state = "NO_EVIDENCE"

    reviewed_episode_reference_admitted = bool(
        carry_forward is not None
        and carry_forward.disposition == "ADMIT_REFERENCE"
        and carry_forward.review_ref is not None
    )

    return LivedContinuityOperatorStatus(
        schema=(
            "kaliv-consciousness-core/"
            "lived-continuity-operator-status/v1"
        ),
        state=state,
        continuity_present=continuity is not None,
        present_context_present=present_context is not None,
        post_cycle_transition_present=post_cycle_transition is not None,
        dormancy_proven=dormancy is not None,
        episode_carry_forward_present=carry_forward is not None,
        reviewed_episode_reference_admitted=reviewed_episode_reference_admitted,
        continuous_loop_plan_present=loop_plan is not None,
        loop_enabled=bool(loop_plan is not None and loop_plan.enabled),
        loop_disposition=None if loop_plan is None else loop_plan.disposition,
        model_swap_qualified=model_swap is not None,
        model_capability_changed=bool(
            model_swap is not None and model_swap.cognitive_capability_changed
        ),
        raw_user_text_included=False,
        raw_assistant_text_included=False,
        raw_chain_of_thought_included=False,
        identity_refs_included=False,
        person_refs_included=False,
        memory_refs_included=False,
        episode_refs_included=False,
        model_refs_included=False,
        model_calls=0,
        persistence_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        notification_authority=False,
        production_activation=False,
    )


def build_lived_continuity_capability_manifest(
) -> LivedContinuityCapabilityManifest:
    """Return the static qualification contract for the complete C31 stack."""
    return LivedContinuityCapabilityManifest(
        schema=(
            "kaliv-consciousness-core/"
            "lived-continuity-capability-manifest/v1"
        ),
        capability="C31_LIVED_CONTINUITY_LOOP",
        slice_start="C31-A",
        slice_end="C31-H",
        implemented_slices=[
            "C31-A",
            "C31-B",
            "C31-C",
            "C31-D",
            "C31-E",
            "C31-F",
            "C31-G",
            "C31-H",
        ],
        continuous_loop_flag=CONTINUOUS_LOOP_FLAG,
        continuous_loop_default_enabled=False,
        thought_engine_replaceable=True,
        self_state_identity_preserved_across_model_swap=True,
        person_binding_preserved_across_model_swap=True,
        durable_memory_binding_preserved_across_model_swap=True,
        powered_off_time_is_dormancy=True,
        cognition_during_gap_allowed=False,
        explicit_wake_reorientation_required=True,
        episode_carry_forward_reference_only=True,
        automatic_durable_memory_write=False,
        continuous_loop_internal_repeat=False,
        continuous_loop_internal_timer=False,
        max_cycles_per_supervisor_plan=1,
        agent3_execution_required=True,
        existing_runtime_gates_required=True,
        raw_chain_of_thought_persisted=False,
        operator_status_raw_text_included=False,
        identity_authority=False,
        persistent_state_authority=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        model_authority=False,
        production_activation=False,
    )
