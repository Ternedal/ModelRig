"""Contract checks for snapshot-driven live lifecycle assembly."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lifecycle_from_snapshots_test",
    ROOT / "scripts" / "consciousness_live_lifecycle_from_snapshots.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

SHA = "a" * 40


def snap(runtime_ref: str, model: str):
    return {
        "schema": module.SNAPSHOT_SCHEMA,
        "runtime_instance_ref": runtime_ref,
        "wake_receipt": {"schema": "wake"},
        "session_bootstrap_receipt": {"schema": "bootstrap"},
        "self_state": {"schema": "self"},
        "cognitive_profile": {"schema": "profile", "model": model},
        "lived_continuity": {"schema": "lived"},
        "production_activation": False,
    }


def test_snapshot_adapter_maps_runtime_evidence():
    before = snap("runtime-instance:" + "1" * 32, "a")
    after = snap("runtime-instance:" + "1" * 32, "b")
    pre_restart = {
        "schema": "kaliv-consciousness-core/runtime-status/v1",
        "runtime_instance_ref": "runtime-instance:" + "0" * 32,
    }
    with patch.object(module, "assemble", return_value={"state": "ok"}) as call:
        result = module.assemble_from_snapshots(
            candidate_git_sha=SHA,
            live_cycle={"candidate": {"git_sha": SHA}},
            pre_restart_status=pre_restart,
            pre_swap_snapshot=before,
            post_swap_snapshot=after,
        )
    assert result == {"state": "ok"}
    args = call.call_args.kwargs
    assert args["before_status"] == pre_restart
    assert args["after_status"]["runtime_instance_ref"] == before["runtime_instance_ref"]
    assert args["wake_orientation"] == before["session_bootstrap_receipt"]
    assert args["before_profile"] == before["cognitive_profile"]
    assert args["after_profile"] == after["cognitive_profile"]


def test_model_swap_snapshots_must_share_one_runtime():
    before = snap("runtime-instance:" + "1" * 32, "a")
    after = snap("runtime-instance:" + "2" * 32, "b")
    try:
        module.assemble_from_snapshots(
            candidate_git_sha=SHA,
            live_cycle={},
            pre_restart_status={},
            pre_swap_snapshot=before,
            post_swap_snapshot=after,
        )
    except module.EvidenceAssemblyError as exc:
        assert "cross another runtime restart" in str(exc)
    else:
        raise AssertionError("cross-runtime model-swap snapshots must fail")


def test_snapshot_schema_is_strict():
    value = snap("runtime-instance:" + "1" * 32, "a")
    value["schema"] = "other"
    try:
        module.assemble_from_snapshots(
            candidate_git_sha=SHA,
            live_cycle={},
            pre_restart_status={},
            pre_swap_snapshot=value,
            post_swap_snapshot=value,
        )
    except module.EvidenceAssemblyError as exc:
        assert "schema mismatch" in str(exc)
    else:
        raise AssertionError("wrong snapshot schema must fail")


if __name__ == "__main__":
    test_snapshot_adapter_maps_runtime_evidence()
    test_model_swap_snapshots_must_share_one_runtime()
    test_snapshot_schema_is_strict()
    print("Consciousness lifecycle snapshot adapter contract: PASS")
