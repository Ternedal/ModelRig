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


def status(ch):
    return {
        "schema": assembler.STATUS_SCHEMA,
        "runtime_instance_ref": "runtime-instance:" + ch * 32,
    }


def live_cycle():
    return {
        "schema": "kaliv-consciousness-core/live-cycle-probe/v1",
        "candidate": {"git_sha": SHA, "working_tree_clean": True},
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


if __name__ == "__main__":
    test_distinct_runtime_instances_assemble_bounded_bundle()
    test_same_runtime_instance_fails_closed()
    test_live_cycle_candidate_mismatch_fails_closed()
    test_identity_lineage_mismatch_fails_closed()
    test_invalid_runtime_ref_fails_closed()
    print("Consciousness live lifecycle evidence assembler contract: PASS")
