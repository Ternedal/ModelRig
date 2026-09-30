from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_system_release_bind_consciousness_test",
    ROOT / "scripts" / "kaliv_system_release_bind_consciousness.py",
)
assert SPEC and SPEC.loader
binder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = binder
SPEC.loader.exec_module(binder)

SHA = "a" * 40
REF = "consciousness-live-lifecycle:" + SHA + ":" + "b" * 64


def manifest():
    gates = {
        "software_exact_green": {"status": "PENDING", "evidence_refs": []},
        "consciousness_live_lifecycle": {"status": "PENDING", "evidence_refs": []},
        "visionrig_physical_perception": {"status": "PENDING", "evidence_refs": []},
        "bodyrig_photoreal_likeness": {"status": "PENDING", "evidence_refs": []},
        "bodyrig_digital_twin_m6": {"status": "PENDING", "evidence_refs": []},
        "end_to_end_latency": {"status": "PENDING", "evidence_refs": []},
        "recovery_soak": {"status": "PENDING", "evidence_refs": []},
        "repository_authority": {"status": "PENDING", "evidence_refs": []},
    }
    return {
        "schema": binder.RELEASE_SCHEMA,
        "release_id": "kaliv-rc-test",
        "repositories": [
            {"repository": "Ternedal/ModelRig", "git_sha": SHA},
            {"repository": "Ternedal/BodyRig", "git_sha": "c" * 40},
            {"repository": "Ternedal/VisionRig", "git_sha": "d" * 40},
            {"repository": "Ternedal/VoiceRig", "git_sha": "e" * 40},
        ],
        "gates": gates,
        "production_activation": False,
    }


def verdict():
    return {
        "schema": binder.VERDICT_SCHEMA,
        "qualification_id": "live-lifecycle-" + "1" * 32,
        "candidate_git_sha": SHA,
        "state": "QUALIFIED",
        "evidence_refs": ["live:1", "dormancy:1", "swap:1"],
        "live_cycle_qualified": True,
        "dormancy_restart_qualified": True,
        "model_swap_qualified": True,
        "identity_lineage_preserved": True,
        "full_lifecycle_qualified": True,
        "consciousness_live_lifecycle_gate_satisfied": True,
        "raw_chain_of_thought_persisted": False,
        "identity_authority": False,
        "persistent_state_authority": False,
        "durable_memory_write_authority": False,
        "execution_authority": False,
        "scheduling_authority": False,
        "model_authority": False,
        "production_activation": False,
        "release_evidence_ref": REF,
    }


def reject(m, v, fragment):
    try:
        binder.bind(m, v)
    except binder.ConsciousnessReleaseBindingError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError("expected fail-closed rejection")


def test_valid_verdict_binds_only_consciousness_gate():
    before = manifest()
    result = binder.bind(before, verdict())
    assert before["gates"]["consciousness_live_lifecycle"]["status"] == "PENDING"
    assert result["gates"]["consciousness_live_lifecycle"] == {
        "status": "PASS",
        "evidence_refs": [REF],
    }
    for name, value in before["gates"].items():
        if name != "consciousness_live_lifecycle":
            assert result["gates"][name] == value
    assert result["production_activation"] is False


def test_binding_is_idempotent_for_same_evidence():
    first = binder.bind(manifest(), verdict())
    second = binder.bind(first, verdict())
    assert second == first


def test_candidate_sha_mismatch_fails_closed():
    v = verdict()
    v["candidate_git_sha"] = "f" * 40
    reject(manifest(), v, "another ModelRig SHA")


def test_missing_qualification_flag_fails_closed():
    v = verdict()
    v["model_swap_qualified"] = False
    reject(manifest(), v, "model_swap_qualified")


def test_authority_overclaim_fails_closed():
    v = verdict()
    v["execution_authority"] = True
    reject(manifest(), v, "overclaimed execution_authority")


def test_release_evidence_ref_must_bind_pinned_sha():
    v = verdict()
    v["release_evidence_ref"] = "consciousness-live-lifecycle:" + "f" * 40 + ":" + "b" * 64
    reject(manifest(), v, "release_evidence_ref")


def test_explicit_fail_is_never_overwritten():
    m = manifest()
    m["gates"]["consciousness_live_lifecycle"] = {
        "status": "FAIL",
        "evidence_refs": ["operator:failure"],
    }
    reject(m, verdict(), "cannot overwrite")


def test_existing_pass_with_other_evidence_fails_closed():
    m = manifest()
    m["gates"]["consciousness_live_lifecycle"] = {
        "status": "PASS",
        "evidence_refs": ["other:evidence"],
    }
    reject(m, verdict(), "different evidence")


def test_production_activation_is_rejected():
    m = manifest()
    m["production_activation"] = True
    reject(m, verdict(), "cannot activate production")


if __name__ == "__main__":
    test_valid_verdict_binds_only_consciousness_gate()
    test_binding_is_idempotent_for_same_evidence()
    test_candidate_sha_mismatch_fails_closed()
    test_missing_qualification_flag_fails_closed()
    test_authority_overclaim_fails_closed()
    test_release_evidence_ref_must_bind_pinned_sha()
    test_explicit_fail_is_never_overwritten()
    test_existing_pass_with_other_evidence_fails_closed()
    test_production_activation_is_rejected()
    print("Kaliv system release Consciousness evidence binding: PASS")
