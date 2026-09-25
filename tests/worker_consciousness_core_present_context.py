"""Contract checks for C31-B present-context projection."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

import pytest

from app.consciousness_core.lived_continuity import (
    LivedContinuityInputs,
    build_lived_continuity_receipt,
)
from app.consciousness_core.present_context import (
    PresentContextError,
    project_present_context,
)
from app.consciousness_core.temporal import TemporalAnchor, TemporalState


def _lived():
    return build_lived_continuity_receipt(
        LivedContinuityInputs(
            schema="kaliv-consciousness-core/lived-continuity-inputs/v1",
            self_id="self-" + "1" * 32,
            person_revision="person-r0042",
            cycle_id="cycle-" + "2" * 32,
            self_state_ref="self-state:1",
            temporal_state_ref="temporal-state:1",
            workspace_ref="workspace:1",
            thought_proposal_ref="thought-proposal:1",
            active_episode_ref="episode:1",
            post_wake_continuity_ref=None,
            wake_orientation_ref=None,
            episode_closure_evidence_ref="closure:1",
            episode_review_ref="review:1",
            production_activation=False,
        )
    )


def _temporal(*, self_id=None, person_revision=None):
    return TemporalState(
        schema="kaliv-consciousness-core/temporal-state/v1",
        self_id=self_id or "self-" + "1" * 32,
        person_revision=person_revision or "person-r0042",
        runtime_epoch_id="epoch-" + "3" * 32,
        now_anchor=TemporalAnchor(
            schema="kaliv-consciousness-core/temporal-anchor/v1",
            anchor_id="tanch-" + "4" * 32,
            event_ref="consciousness-core:now",
            wall_time_unix_ms=123456,
            runtime_epoch_id="epoch-" + "3" * 32,
            monotonic_ms=456,
            sequence=7,
            source_refs=["clock-source:1"],
            confidence=0.9,
            production_activation=False,
        ),
        session_elapsed_ms=456,
        continuity_gap_detected=True,
        continuity_gap_ms=12000,
        clock_anomaly="runtime_epoch_changed",
        local_day_phase="morning",
        uncertainty=0.1,
        production_activation=False,
    )


def test_present_context_is_bounded_and_authority_free():
    value = project_present_context(_lived(), _temporal())
    assert value.local_day_phase == "morning"
    assert value.session_elapsed_ms == 456
    assert value.continuity_gap_detected is True
    assert value.continuity_gap_ms == 12000
    assert value.temporal_uncertainty == 0.1
    assert value.active_episode_ref == "episode:1"
    assert value.episode_review_ref == "review:1"
    assert value.reference_only is True
    assert value.raw_chain_of_thought_included is False
    assert value.identity_authority is False
    assert value.persistent_state_authority is False
    assert value.durable_memory_write_authority is False
    assert value.execution_authority is False
    assert value.scheduling_authority is False
    assert value.production_activation is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("self_id", "self-" + "9" * 32),
        ("person_revision", "person-r9999"),
    ],
)
def test_present_context_rejects_cross_identity_temporal_state(field, value):
    kwargs = {field: value}
    with pytest.raises(PresentContextError):
        project_present_context(_lived(), _temporal(**kwargs))
