"""Contract checks for C31-D dormancy bridge."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.dormancy_bridge import DormancyBridgeError, build_dormancy_bridge
from app.consciousness_core.sleep import prepare_sleep, wake_from_sleep
from app.consciousness_core.temporal import TemporalAnchor
from app.consciousness_core.wake_cycle import WakeOrientationReceipt, wake_receipt_ref


SELF = "self-" + "1" * 32
PERSON = "person-r0042"
CYCLE = "cycle-" + "2" * 32
ORIENTED = "cycle-" + "3" * 32


def _anchor(marker: str, wall: int, epoch: str) -> TemporalAnchor:
    return TemporalAnchor(
        schema="kaliv-consciousness-core/temporal-anchor/v1",
        anchor_id="tanch-" + marker * 32,
        event_ref="test:" + marker,
        wall_time_unix_ms=wall,
        runtime_epoch_id="epoch-" + epoch * 32,
        monotonic_ms=100,
        sequence=1,
        source_refs=["clock:test"],
        confidence=1.0,
        production_activation=False,
    )


def _wake(planned: bool = True):
    if planned:
        sleep = prepare_sleep(
            self_id=SELF,
            person_revision=PERSON,
            entry_anchor=_anchor("1", 1000, "a"),
            reason="app_closed",
        )
        return wake_from_sleep(
            wake_anchor=_anchor("2", 61000, "b"),
            sleep_record=sleep,
            expected_self_id=SELF,
            expected_person_revision=PERSON,
        )
    return wake_from_sleep(
        wake_anchor=_anchor("4", 61000, "d"),
        last_known_anchor=_anchor("3", 1000, "c"),
        expected_self_id=SELF,
        expected_person_revision=PERSON,
    )


def _orientation(wake):
    return WakeOrientationReceipt(
        schema="kaliv-consciousness-core/wake-orientation-receipt/v1",
        wake_receipt_ref=wake_receipt_ref(wake),
        from_cycle_id=CYCLE,
        oriented_cycle_id=ORIENTED,
        previous_self_state_ref="self-state:before",
        oriented_self_state_ref="self-state:after",
        previous_workspace_ref="workspace:before",
        oriented_workspace_ref="workspace:after",
        wake_candidate_id="wc-" + "5" * 32,
        carried_candidate_ids=[],
        resume_goal_refs_exposed=[],
        resume_open_loop_refs_exposed=[],
        pending_review_refs_exposed=[],
        self_revision_before=7,
        self_revision_after=8,
        cognition_during_gap=False,
        automatic_goal_resume=False,
        automatic_loop_resume=False,
        self_state_store_write_applied=False,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )


def test_planned_sleep_becomes_explicit_cognition_gap():
    wake = _wake(True)
    receipt = build_dormancy_bridge(wake, _orientation(wake))
    assert receipt.dormancy_kind == "PLANNED_SLEEP"
    assert receipt.duration_known is True
    assert receipt.offline_duration_ms == 60000
    assert receipt.cognition_during_gap is False
    assert receipt.explicit_wake_reorientation is True
    assert receipt.reference_only is True
    assert receipt.execution_authority is False
    assert receipt.durable_memory_write_authority is False
    assert receipt.model_authority is False


def test_unplanned_shutdown_never_invents_exact_gap_duration():
    wake = _wake(False)
    receipt = build_dormancy_bridge(wake, _orientation(wake))
    assert receipt.dormancy_kind == "UNPLANNED_DORMANCY"
    assert receipt.sleep_id is None
    assert receipt.duration_known is False
    assert receipt.offline_duration_ms is None
    assert receipt.cognition_during_gap is False


def test_orientation_for_another_wake_fails_closed():
    wake = _wake(True)
    forged = _orientation(wake).model_copy(update={"wake_receipt_ref": "wake-receipt:other"})
    try:
        build_dormancy_bridge(wake, forged)
    except DormancyBridgeError:
        pass
    else:
        raise AssertionError("cross-wake dormancy bridge must fail closed")


def test_bridge_is_deterministic():
    wake = _wake(True)
    orientation = _orientation(wake)
    assert build_dormancy_bridge(wake, orientation) == build_dormancy_bridge(wake, orientation)
