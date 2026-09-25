"""Contract checks for C31-C post-cycle lived continuity."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.lived_continuity import LivedContinuityInputs, build_lived_continuity_receipt
from app.consciousness_core.lived_continuity_transition import LivedContinuityTransitionError, reduce_lived_continuity
from app.consciousness_core.reducer import CognitiveTransitionReceipt


def _lived():
    return build_lived_continuity_receipt(LivedContinuityInputs(
        schema="kaliv-consciousness-core/lived-continuity-inputs/v1",
        self_id="self-" + "1" * 32,
        person_revision="person-r0042",
        cycle_id="cycle-" + "2" * 32,
        self_state_ref="self-state:before",
        temporal_state_ref="temporal-state:before",
        workspace_ref="workspace:before",
        thought_proposal_ref="thought-proposal:1",
        active_episode_ref="episode:1",
        episode_closure_evidence_ref="closure:1",
        episode_review_ref="review:1",
        production_activation=False,
    ))


def _transition(**updates):
    values = dict(
        schema="kaliv-consciousness-core/cognitive-transition-receipt/v1",
        from_cycle_id="cycle-" + "2" * 32,
        to_cycle_id="cycle-" + "3" * 32,
        proposal_ref="thought-proposal:1",
        previous_self_state_ref="self-state:before",
        next_self_state_ref="self-state:after",
        previous_workspace_ref="workspace:before",
        next_workspace_ref="workspace:after",
        self_id="self-" + "1" * 32,
        person_id="person-" + "4" * 32,
        person_revision="person-r0042",
        self_revision_before=7,
        self_revision_after=8,
        carried_candidate_ids=[],
        accepted_attention_targets=[],
        thought_result_candidate_id="wc-" + "5" * 32,
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
    values.update(updates)
    return CognitiveTransitionReceipt(**values)


def test_transition_is_deterministic_reference_only_and_authority_free():
    first = reduce_lived_continuity(_lived(), _transition(), temporal_state_ref="temporal-state:after")
    second = reduce_lived_continuity(_lived(), _transition(), temporal_state_ref="temporal-state:after")
    assert first == second
    assert first.from_cycle_id == "cycle-" + "2" * 32
    assert first.to_cycle_id == "cycle-" + "3" * 32
    assert first.active_episode_ref == "episode:1"
    assert first.episode_review_ref == "review:1"
    assert first.reference_only is True
    assert first.identity_authority is False
    assert first.persistent_state_authority is False
    assert first.durable_memory_write_authority is False
    assert first.execution_authority is False
    assert first.scheduling_authority is False
    assert first.model_authority is False
    assert first.raw_chain_of_thought_persisted is False


def test_cross_cycle_transition_fails_closed():
    try:
        reduce_lived_continuity(_lived(), _transition(from_cycle_id="cycle-" + "9" * 32), temporal_state_ref="temporal-state:after")
    except LivedContinuityTransitionError:
        pass
    else:
        raise AssertionError("cross-cycle continuity transition must fail closed")


def test_cross_identity_transition_fails_closed():
    try:
        reduce_lived_continuity(_lived(), _transition(self_id="self-" + "9" * 32), temporal_state_ref="temporal-state:after")
    except LivedContinuityTransitionError:
        pass
    else:
        raise AssertionError("cross-self continuity transition must fail closed")


def test_stale_proposal_binding_fails_closed():
    try:
        reduce_lived_continuity(_lived(), _transition(proposal_ref="thought-proposal:stale"), temporal_state_ref="temporal-state:after")
    except LivedContinuityTransitionError:
        pass
    else:
        raise AssertionError("stale proposal continuity transition must fail closed")
