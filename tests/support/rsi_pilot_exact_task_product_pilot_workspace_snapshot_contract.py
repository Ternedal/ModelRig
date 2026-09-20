"""Adversarial contract for ADR-DC-106 product-pilot workspace snapshot."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from source_code import code_of  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_executor_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_workspace_snapshot as workspace_snapshot  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
from kaliv_dev_control.tier_a_command_receipt import GitWorkspaceSnapshot  # noqa: E402
import rsi_pilot_exact_task_product_pilot_executor_capability_contract as capability_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import _authority_fixture  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-workspace-snapshot-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_workspace_snapshot.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-106 unexpectedly accepted unsafe workspace state")


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    capability_temp = None
    drift_path = None
    try:
        auth_temp, tx_temp, admitted, task = capability_contract._admission(fixture)
        assert admitted.fixed_command_id == VERSION_CHECK_COMMAND_ID
        capability_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-workspace-snapshot-"
        )
        authority = _authority_fixture(Path(capability_temp.name).resolve(), task)
        original_path_sha = capability._path_sha256

        def scoped_path_sha(path: Path) -> str:
            candidate = Path(path)
            if candidate == authority["workspace"]:
                return admitted.workspace_root_path_sha256
            return original_path_sha(candidate)

        executor_capability = capability._materialize_verified_product_pilot_executor_capability(
            execution_admission=admitted,
            catalog=authority["catalog"],
            toolchain=authority["toolchain"],
            isolation_attestation=authority["attestation"],
            physical_verifier=authority["physical_verifier"],
            signed_runtime_closure=authority["signed_closure"],
            runtime_closure_verifier=authority["runtime_verifier"],
            trusted_runtime_root=authority["trusted"],
            git_runner=authority["git_runner"],
            workspace_root=authority["workspace"],
            control_plane_root=authority["control"],
            path_sha256=scoped_path_sha,
        )
        assert executor_capability.capability_authenticated is True

        drift_path = authority["workspace"] / "adr-dc-106-untracked-drift.tmp"
        drift_path.write_text("unsafe\n", encoding="utf-8")
        _reject(
            lambda: workspace_snapshot.materialize_pilot_exact_task_product_pilot_workspace_snapshot(
                executor_capability
            )
        )
        drift_path.unlink()
        drift_path = None

        original_git_run = authority["git_runner"].run
        observed: list[tuple[str, ...]] = []
        forbidden = {
            "add",
            "am",
            "apply",
            "checkout",
            "cherry-pick",
            "clean",
            "clone",
            "commit",
            "fetch",
            "merge",
            "pull",
            "push",
            "rebase",
            "reset",
            "restore",
            "switch",
        }

        def audited_git_run(args, **kwargs):
            assert isinstance(args, tuple)
            assert args
            assert args[0] not in forbidden
            observed.append(args)
            return original_git_run(args, **kwargs)

        with patch.object(
            authority["git_runner"], "run", side_effect=audited_git_run
        ):
            receipt = workspace_snapshot.materialize_pilot_exact_task_product_pilot_workspace_snapshot(
                executor_capability
            )

        assert observed
        assert {args[0] for args in observed} <= {"rev-parse", "diff", "ls-files"}
        assert receipt.snapshot_authenticated is True
        assert receipt.executor_capability_sha256 == executor_capability.sha256
        assert receipt.execution_admission_sha256 == admitted.sha256
        assert receipt.execution_nonce_sha256 == executor_capability.execution_nonce_sha256
        assert receipt.development_task_id == task.task_id
        assert receipt.development_task_sha256 == executor_capability.development_task_sha256
        assert receipt.development_task_base_sha == task.base_sha
        assert receipt.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert receipt.catalog_sha256 == authority["catalog"].sha256
        assert receipt.toolchain_sha256 == authority["toolchain"].sha256
        assert receipt.signed_runtime_closure_sha256 == authority["signed_closure"].sha256
        assert receipt.workspace_root_authority_sha256 == authority["workspace_authority"]
        assert receipt.toolhost_sha256 == authority["toolhost_sha"]
        assert receipt.workspace_snapshot.head_sha == task.base_sha
        assert receipt.workspace_snapshot.has_unstaged_or_untracked is False
        assert receipt.workspace_snapshot.sha256 == receipt.workspace_snapshot_sha256
        assert receipt.fresh_substrate_revalidated is True
        assert receipt.workspace_snapshot_materialized is True
        assert receipt.execution_plan_materialization_authorized is True
        assert receipt.execution_plan_materialized is False
        assert receipt.task_execution_authorized is False
        assert receipt.task_execution_started is False
        assert receipt.task_execution_completed is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.next_boundary_execution_plan_required is True

        live = workspace_snapshot._get_live_product_pilot_workspace_snapshot_inputs(
            receipt
        )
        assert live is not None
        assert live["executor_capability"] is executor_capability
        assert live["git_runner"] is authority["git_runner"]
        assert live["task"] == task
        assert live["workspace_snapshot"].sha256 == receipt.workspace_snapshot_sha256

        serialized = workspace_snapshot.PilotExactTaskProductPilotWorkspaceSnapshotReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.snapshot_authenticated is False

        replayed_capability = capability.PilotExactTaskProductPilotExecutorCapabilityReceipt.from_mapping(
            executor_capability.to_dict()
        )
        assert replayed_capability.capability_authenticated is False
        _reject(
            lambda: workspace_snapshot.materialize_pilot_exact_task_product_pilot_workspace_snapshot(
                replayed_capability
            )
        )

        drift_path = authority["workspace"] / "adr-dc-106-post-capture-drift.tmp"
        drift_path.write_text("changed\n", encoding="utf-8")
        assert receipt.snapshot_authenticated is False
        drift_path.unlink()
        drift_path = None

        for field, value in (
            ("fresh_substrate_revalidated", False),
            ("workspace_snapshot_materialized", False),
            ("workspace_head_matches_task_base", False),
            ("workspace_has_unstaged_or_untracked", True),
            ("execution_plan_materialization_authorized", False),
            ("execution_plan_materialized", True),
            ("task_execution_authorized", True),
            ("task_execution_started", True),
            ("task_execution_completed", True),
            ("local_commit_authorized", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("next_boundary_execution_plan_required", False),
            ("nonce_reusable", True),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: workspace_snapshot.PilotExactTaskProductPilotWorkspaceSnapshotReceipt.from_mapping(
                    raw
                )
            )

        raw = receipt.to_dict()
        raw["workspace_snapshot"] = dict(raw["workspace_snapshot"])
        raw["workspace_snapshot"]["head_sha"] = "f" * 40
        _reject(
            lambda: workspace_snapshot.PilotExactTaskProductPilotWorkspaceSnapshotReceipt.from_mapping(
                raw
            )
        )
    finally:
        if drift_path is not None and drift_path.exists():
            drift_path.unlink()
        if capability_temp is not None:
            capability_temp.cleanup()
        if tx_temp is not None:
            tx_temp.cleanup()
        if auth_temp is not None:
            auth_temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        workspace_snapshot.PilotExactTaskProductPilotWorkspaceSnapshotReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    nested = schema["properties"]["workspace_snapshot"]
    assert set(nested["properties"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert set(nested["required"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert nested["additionalProperties"] is False

    public = inspect.signature(
        workspace_snapshot.materialize_pilot_exact_task_product_pilot_workspace_snapshot
    )
    assert tuple(public.parameters) == ("executor_capability",)

    source = code_of(SOURCE)
    lowered = source.lower()
    assert "_gitworkspaceevidence(" in lowered
    assert ".snapshot()" in lowered
    for forbidden_text in (
        "run_verified_tier_a_command",
        "run_single_verified_tier_a_command_with_receipt",
        ".reset_to_base(",
        "subprocess.",
        "requests.",
        "urllib.",
        "socket.",
        "create_once_file",
    ):
        assert forbidden_text not in lowered


if __name__ == "__main__":
    run_contract()
