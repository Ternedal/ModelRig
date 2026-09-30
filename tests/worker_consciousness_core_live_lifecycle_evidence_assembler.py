"""Contract checks for live lifecycle evidence assembly."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "live_lifecycle_evidence_assembler_test",
    ROOT / "scripts" / "consciousness_live_lifecycle_evidence_assembler.py",
)
assert SPEC and SPEC.loader
assembler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = assembler
SPEC.loader.exec_module(assembler)

QUALIFIER_SPEC = importlib.util.spec_from_file_location(
    "live_lifecycle_qualifier_integration_test",
    ROOT / "scripts" / "consciousness_live_lifecycle_qualifier.py",
)
assert QUALIFIER_SPEC and QUALIFIER_SPEC.loader
qualifier = importlib.util.module_from_spec(QUALIFIER_SPEC)
sys.modules[QUALIFIER_SPEC.name] = qualifier
QUALIFIER_SPEC.loader.exec_module(qualifier)

SHA = "a" * 40


class Receipt:
    def __init__(self, *, self_id="self-" + "1" * 32, person_revision="person-r0007"):
        self.self_id = self_id
        self.person_revision = person_revision

    def model_dump(self, mode="json"):
        return {
            "self_id": self.self_id,
            "person_revision": self.person_revision,
            "production_activation": False,
        }


class FullReceipt:
    def __init__(self, payload: dict):
        self.payload = payload
        self.self_id = payload["self_id"]
        self.person_revision = payload["person_revision"]

    def model_dump(self, mode="json"):
        return dict(self.payload)


def full_dormancy_receipt() -> FullReceipt:
    return FullReceipt({
        "schema": "kaliv-consciousness-core/dormancy-bridge-receipt/v1",
        "bridge_id": "dormancy-bridge-" + "3" * 32,
        "wake_receipt_ref": "wake:1",
        "wake_orientation_ref": "orientation:1",
        "self_id": "self-" + "1" * 32,
        "person_revision": "person-r0007",
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
    })


def full_model_swap_receipt() -> FullReceipt:
    return FullReceipt({
        "schema": "kaliv-consciousness-core/model-swap-continuity-receipt/v1",
        "qualification_id": "model-swap-" + "6" * 32,
        "from_cognitive_profile_ref": "cognitive-profile:before",
        "to_cognitive_profile_ref": "cognitive-profile:after",
        "cognitive_profile_changed": True,
        "cognitive_capability_changed": True,
        "self_id": "self-" + "1" * 32,
        "person_id": "person-" + "7" * 32,
        "person_revision": "person-r0007",
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
    })


def status(ch):
    return {
        "schema": assembler.STATUS_SCHEMA,
        "runtime_instance_ref": "runtime-instance:" + ch * 32,
    }


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


def kwargs():
    return {
        "candidate_git_sha": SHA,
        "live_cycle": live_cycle(),
        "before_status": status("1"),
        "after_status": status("2"),
        "wake_receipt": {},
        "wake_orientation": {},
        "before_profile": {},
        "after_profile": {},
        "before_self_state": {},
        "after_self_state": {},
        "before_continuity": {},
        "after_continuity": {},
    }


def test_distinct_runtime_instances_assemble_bounded_bundle():
    with patch.object(assembler, "build_dormancy_bridge", return_value=Receipt()), patch.object(
        assembler,
        "qualify_model_swap_continuity",
        return_value=Receipt(),
    ):
        bundle = assembler.assemble(**kwargs())
    assert bundle["schema"] == assembler.SCHEMA
    assert bundle["candidate_git_sha"] == SHA
    assert bundle["dormancy_restart"]["restart_proven"] is True
    assert bundle["dormancy_restart"]["candidate_git_sha"] == SHA
    assert bundle["model_swap"]["candidate_git_sha"] == SHA
    assert bundle["production_activation"] is False


def test_same_runtime_instance_fails_closed():
    value = kwargs()
    value["after_status"] = status("1")
    try:
        assembler.assemble(**value)
    except assembler.EvidenceAssemblyError as exc:
        assert "restart is not proven" in str(exc)
    else:
        raise AssertionError("same runtime instance must not prove restart")


def test_live_cycle_candidate_mismatch_fails_closed():
    value = kwargs()
    value["live_cycle"]["candidate"]["git_sha"] = "b" * 40
    try:
        assembler.assemble(**value)
    except assembler.EvidenceAssemblyError as exc:
        assert "another candidate SHA" in str(exc)
    else:
        raise AssertionError("candidate mismatch must fail")


def test_identity_lineage_mismatch_fails_closed():
    with patch.object(
        assembler,
        "build_dormancy_bridge",
        return_value=Receipt(self_id="self-" + "1" * 32),
    ), patch.object(
        assembler,
        "qualify_model_swap_continuity",
        return_value=Receipt(self_id="self-" + "9" * 32),
    ):
        try:
            assembler.assemble(**kwargs())
        except assembler.EvidenceAssemblyError as exc:
            assert "different Self identities" in str(exc)
        else:
            raise AssertionError("identity mismatch must fail")


def test_invalid_runtime_ref_fails_closed():
    value = kwargs()
    value["after_status"]["runtime_instance_ref"] = "runtime-instance:not-valid"
    try:
        assembler.assemble(**value)
    except assembler.EvidenceAssemblyError as exc:
        assert "valid runtime_instance_ref" in str(exc)
    else:
        raise AssertionError("invalid runtime ref must fail")


def test_assembled_bundle_is_accepted_by_live_lifecycle_qualifier():
    with patch.object(
        assembler,
        "build_dormancy_bridge",
        return_value=full_dormancy_receipt(),
    ), patch.object(
        assembler,
        "qualify_model_swap_continuity",
        return_value=full_model_swap_receipt(),
    ):
        bundle = assembler.assemble(**kwargs())

    verdict = qualifier.qualify(bundle)
    assert verdict["state"] == "QUALIFIED"
    assert verdict["candidate_git_sha"] == SHA
    assert verdict["consciousness_live_lifecycle_gate_satisfied"] is True
    assert verdict["release_evidence_ref"].startswith(
        "consciousness-live-lifecycle:" + SHA + ":"
    )
    assert verdict["production_activation"] is False


if __name__ == "__main__":
    test_distinct_runtime_instances_assemble_bounded_bundle()
    test_same_runtime_instance_fails_closed()
    test_live_cycle_candidate_mismatch_fails_closed()
    test_identity_lineage_mismatch_fails_closed()
    test_invalid_runtime_ref_fails_closed()
    test_assembled_bundle_is_accepted_by_live_lifecycle_qualifier()
    print("Consciousness live lifecycle evidence assembler contract: PASS")
