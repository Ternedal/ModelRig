"""Contract checks for C31-A lived continuity."""
from __future__ import annotations

from pydantic import ValidationError

from worker.app.consciousness_core.lived_continuity import (
    LivedContinuityInputs,
    build_lived_continuity_receipt,
)


def _inputs(**overrides):
    values = {
        "schema": "kaliv-consciousness-core/lived-continuity-inputs/v1",
        "self_id": "self-" + "1" * 32,
        "person_revision": "person-r0042",
        "cycle_id": "cycle-" + "2" * 32,
        "self_state_ref": "self-state:1",
        "temporal_state_ref": "temporal-state:1",
        "workspace_ref": "workspace:1",
        "thought_proposal_ref": "thought-proposal:1",
        "active_episode_ref": "episode:1",
        "post_wake_continuity_ref": None,
        "wake_orientation_ref": None,
        "episode_closure_evidence_ref": None,
        "episode_review_ref": None,
        "production_activation": False,
    }
    values.update(overrides)
    return LivedContinuityInputs(**values)


def test_receipt_is_deterministic_and_authority_free():
    inputs = _inputs()
    first = build_lived_continuity_receipt(inputs)
    second = build_lived_continuity_receipt(inputs)
    assert first == second
    assert first.continuity_loop_id.startswith("lived-")
    assert first.reference_only is True
    assert first.raw_chain_of_thought_persisted is False
    assert first.cognition_during_gap_claimed is False
    assert first.identity_authority is False
    assert first.persistent_state_authority is False
    assert first.durable_memory_write_authority is False
    assert first.execution_authority is False
    assert first.scheduling_authority is False
    assert first.model_authority is False
    assert first.production_activation is False


def test_wake_refs_are_exactly_paired():
    try:
        _inputs(post_wake_continuity_ref="continuity:1")
    except ValidationError:
        pass
    else:
        raise AssertionError("unpaired wake continuity ref must fail closed")


def test_review_requires_closure_evidence():
    try:
        _inputs(episode_review_ref="review:1")
    except ValidationError:
        pass
    else:
        raise AssertionError("review without closure evidence must fail closed")


def test_review_and_wake_refs_can_be_joined_without_authority():
    receipt = build_lived_continuity_receipt(
        _inputs(
            post_wake_continuity_ref="continuity:1",
            wake_orientation_ref="wake-orientation:1",
            episode_closure_evidence_ref="closure:1",
            episode_review_ref="review:1",
        )
    )
    assert receipt.post_wake_continuity_ref == "continuity:1"
    assert receipt.wake_orientation_ref == "wake-orientation:1"
    assert receipt.episode_closure_evidence_ref == "closure:1"
    assert receipt.episode_review_ref == "review:1"
