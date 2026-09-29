"""Contract tests for the full live Consciousness lifecycle qualifier."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "consciousness_live_lifecycle_qualifier_test",
    ROOT / "scripts" / "consciousness_live_lifecycle_qualifier.py",
)
assert SPEC and SPEC.loader
qualifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qualifier
SPEC.loader.exec_module(qualifier)

SHA = "a" * 40
SELF_ID = "self-" + "1" * 32
PERSON_REVISION = "person-r0007"


def live_cycle():
    return {
        "schema": "kaliv-consciousness-core/live-cycle-probe/v1",
        "candidate": {
            "git_sha": SHA,
            "branch": "qualification",
            "working_tree_clean": True,
        },
        "worker": {"url": "http://127.0.0.1:8099", "health_ok": True},
        "admission": {
            "turn_ref": "turn:1",
            "evidence_ref": "world:1",
            "cognition_event_id": "cevt-" + "2" * 32,
            "observed_sequence": 1,
            "latency_ms": 1.0,
            "model_calls": 0,
        },
        "cycle": {
            "attempts": 1,
            "wait_count": 0,
            "decision": "RUN",
            "latency_ms_by_attempt": [2.0],
            "profile_ref": "profile:1",
            "self_state_ref": "self-state:1",
            "world_state_ref": "world-state:1",
            "workspace_ref": "workspace:1",
            "transition_receipt_ref": "transition:1",
            "completed_cycles": 1,
            "model_calls": 1,
        },
        "authority": {
            "automatic_repeat": False,
            "internal_thread_created": False,
            "internal_timer_created": False,
            "durable_memory_write_authority": False,
            "execution_authority": False,
            "scheduling_authority": False,
            "production_activation": False,
        },
        "gate": {
            "passed": True,
            "live_cycle_proven": True,
            "full_lifecycle_qualified": False,
            "model_swap_qualified": False,
            "dormancy_restart_qualified": False,
            "release_gate_satisfied": False,
            "production_activation": False,
        },
    }


def dormancy_receipt():
    return {
        "schema": "kaliv-consciousness-core/dormancy-bridge-receipt/v1",
        "bridge_id": "dormancy-bridge-" + "3" * 32,
        "wake_receipt_ref": "wake:1",
        "wake_orientation_ref": "orientation:1",
        "self_id": SELF_ID,
        "person_revision": PERSON_REVISION,
        "dormancy_kind": "UNPLANNED_DORMANCY",
        "sleep_id": None,
        "entry_anchor_ref": None,
        "wake_anchor_ref": "temporal-anchor:1",
        "from_cycle_id": "cycle-" + "4" * 32,
        "oriented_cycle_id": "cycle-" + "5" * 32,
        "duration_known": False,
        "offline_duration_ms": None,
        "offline_duration_upper_bound_ms": 10000,
        "cognition_during_gap": False,
        "explicit_wake_reorientation": True,
        "automatic_goal_resume": False,
        "automatic_loop_resume": False,
        "reference_only": True,
        "identity_authority": False,
        "persistent_state_authority": False,
        "durable_memory_write_authority": False,
        "execution_authority": False,
        "scheduling_authority": False,
        "model_authority": False,
        "raw_chain_of_thought_persisted": False,
        "production_activation": False,
    }


def model_swap_receipt():
    return {
        "schema": "kaliv-consciousness-core/model-swap-continuity-receipt/v1",
        "qualification_id": "model-swap-" + "6" * 32,
        "from_cognitive_profile_ref": "cognitive-profile:before",
        "to_cognitive_profile_ref": "cognitive-profile:after",
        "cognitive_profile_changed": True,
        "cognitive_capability_changed": True,
        "self_id": SELF_ID,
        "person_id": "person-" + "7" * 32,
        "person_revision": PERSON_REVISION,
        "self_state_ref": "self-state:1",
        "before_continuity_ref": "lived-continuity:before",
        "after_continuity_ref": "lived-continuity:after",
        "personality_state_ref": "personality:1",
        "durable_memory_binding_ref": "memory4:1",
        "identity_preserved": True,
        "person_binding_preserved": True,
        "self_state_preserved": True,
        "durable_memory_binding_preserved": True,
        "continuity_preserved": True,
        "raw_chain_of_thought_persisted": False,
        "identity_authority": False,
        "persistent_state_authority": False,
        "durable_memory_write_authority": False,
        "execution_authority": False,
        "scheduling_authority": False,
        "model_authority": False,
        "production_activation": False,
    }


def evidence():
    return {
        "schema": qualifier.SCHEMA,
        "candidate_git_sha": SHA,
        "live_cycle": live_cycle(),
        "dormancy_restart": {
            "candidate_git_sha": SHA,
            "restart_proven": True,
            "receipt": dormancy_receipt(),
        },
        "model_swap": {
            "candidate_git_sha": SHA,
            "receipt": model_swap_receipt(),
        },
        "production_activation": False,
    }


def must_reject(value, fragment):
    try:
        qualifier.qualify(value)
    except qualifier.LiveLifecycleQualificationError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"expected rejection containing {fragment!r}")


def test_valid_full_lifecycle_qualifies_exact_candidate():
    verdict = qualifier.qualify(evidence())
    assert verdict["state"] == "QUALIFIED"
    assert verdict["candidate_git_sha"] == SHA
    assert verdict["full_lifecycle_qualified"] is True
    assert verdict["consciousness_live_lifecycle_gate_satisfied"] is True
    assert verdict["identity_lineage_preserved"] is True
    assert len(verdict["evidence_refs"]) == 3
    assert verdict["production_activation"] is False


def test_mismatched_candidate_sha_fails_closed():
    value = evidence()
    value["model_swap"]["candidate_git_sha"] = "b" * 40
    must_reject(value, "model_swap candidate Git SHA")


def test_restart_must_be_explicitly_proven():
    value = evidence()
    value["dormancy_restart"]["restart_proven"] = False
    must_reject(value, "explicitly prove process restart")


def test_identity_lineage_mismatch_fails_closed():
    value = evidence()
    value["model_swap"]["receipt"]["self_id"] = "self-" + "9" * 32
    must_reject(value, "different Self identities")


def test_authority_overclaim_fails_closed():
    value = evidence()
    value["dormancy_restart"]["receipt"]["execution_authority"] = True
    must_reject(value, "overclaimed execution_authority")


def test_model_swap_refs_must_actually_change():
    value = evidence()
    value["model_swap"]["receipt"]["to_cognitive_profile_ref"] = (
        value["model_swap"]["receipt"]["from_cognitive_profile_ref"]
    )
    must_reject(value, "cognitive profile refs did not actually change")


def test_live_cycle_cannot_preclaim_full_lifecycle():
    value = evidence()
    value["live_cycle"]["gate"]["full_lifecycle_qualified"] = True
    must_reject(value, "unexpectedly claimed full_lifecycle_qualified")


def test_qualifier_never_accepts_production_activation():
    value = evidence()
    value["production_activation"] = True
    must_reject(value, "cannot activate production")


if __name__ == "__main__":
    test_valid_full_lifecycle_qualifies_exact_candidate()
    test_mismatched_candidate_sha_fails_closed()
    test_restart_must_be_explicitly_proven()
    test_identity_lineage_mismatch_fails_closed()
    test_authority_overclaim_fails_closed()
    test_model_swap_refs_must_actually_change()
    test_live_cycle_cannot_preclaim_full_lifecycle()
    test_qualifier_never_accepts_production_activation()
    print("Consciousness live lifecycle qualifier contract: PASS")
