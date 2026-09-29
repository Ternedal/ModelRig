"""C31-H privacy-safe operator-status contract checks."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.lived_continuity_status import (
    build_lived_continuity_operator_status,
)


def test_c31_operator_status_covers_a_through_g():
    status = build_lived_continuity_operator_status()
    assert status.slice_start == "C31-A"
    assert status.slice_end == "C31-G"
    assert status.lived_continuity_available is True
    assert status.present_context_available is True
    assert status.post_cycle_transition_available is True
    assert status.dormancy_bridge_available is True
    assert status.episode_carry_forward_available is True
    assert status.continuous_loop_supervisor_available is True
    assert status.model_swap_continuity_available is True


def test_c31_operator_status_is_privacy_safe_and_authority_free():
    status = build_lived_continuity_operator_status()
    assert status.identity_values_included is False
    assert status.person_revision_included is False
    assert status.memory_refs_included is False
    assert status.episode_contents_included is False
    assert status.model_outputs_included is False
    assert status.raw_chain_of_thought_included is False
    assert status.direct_memory4_write_authority is False
    assert status.identity_authority is False
    assert status.execution_authority is False
    assert status.scheduling_authority is False
    assert status.model_authority is False
    assert status.production_activation is False


if __name__ == "__main__":
    test_c31_operator_status_covers_a_through_g()
    test_c31_operator_status_is_privacy_safe_and_authority_free()
