"""Adversarial contract for ADR-DC-106 product-pilot execution plan."""
from __future__ import annotations

import hashlib
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
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_plan as plan  # noqa: E402
from kaliv_dev_control.tier_a_command_receipt import GitWorkspaceSnapshot  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
import rsi_pilot_exact_task_product_pilot_executor_capability_contract as capability_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import _authority_fixture  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-execution-plan-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_execution_plan.py"
)
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-106 unexpectedly accepted unsafe execution plan")


def _snapshot(task, *, staged_bytes: int = 0) -> GitWorkspaceSnapshot:
    return GitWorkspaceSnapshot(
        head_sha=task.base_sha,
        staged_patch_sha256=_EMPTY_SHA,
        staged_patch_bytes=staged_bytes,
        unstaged_patch_sha256=_EMPTY_SHA,
        unstaged_patch_bytes=0,
        untracked_paths_sha256=_EMPTY_SHA,
        untracked_path_count=0,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    capability_temp = None
    try:
        auth_temp, tx_temp, admitted, task = capability_contract._admission(fixture)
        capability_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-execution-plan-"
        )
        authority = _authority_fixture(Path(capability_temp.name).resolve(), task)
        original_path_sha = capability._path_sha256

        def scoped_path_sha(path: Path) -> str:
            candidate = Path(path)
            if candidate == authority["workspace"]:
                return admitted.workspace_root_path_sha256
            return original_path_sha(candidate)

        cap = capability._materialize_verified_product_pilot_executor_capability(
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
        assert cap.capability_authenticated is True

        clean = _snapshot(task)
        git_runtime_sha = authority["git_runner"].evidence().sha256
        with patch.object(
            plan,
            "_capture_workspace_snapshot",
            return_value=(clean, git_runtime_sha),
        ):
            receipt = plan._materialize_verified_product_pilot_execution_plan(cap)
            assert receipt.plan_authenticated is True
            assert receipt.executor_capability_sha256 == cap.sha256
            assert receipt.execution_admission_sha256 == cap.execution_admission_sha256
            assert receipt.execution_nonce_sha256 == cap.execution_nonce_sha256
            assert receipt.development_task_id == task.task_id
            assert receipt.development_task_sha256 == cap.development_task_sha256
            assert receipt.development_task_base_sha == task.base_sha
            assert receipt.fixed_command_id == VERSION_CHECK_COMMAND_ID
            assert receipt.catalog_sha256 == cap.catalog_sha256
            assert receipt.toolchain_sha256 == cap.toolchain_sha256
            assert receipt.lease_sha256 == cap.lease_sha256
            assert receipt.physical_report_sha256 == cap.physical_report_sha256
            assert receipt.signed_runtime_closure_sha256 == cap.signed_runtime_closure_sha256
            assert receipt.runtime_closure_manifest_sha256 == cap.runtime_closure_manifest_sha256
            assert receipt.trusted_git_runtime_receipt_sha256 == cap.trusted_git_runtime_receipt_sha256
            assert receipt.trusted_git_runtime_manifest_sha256 == cap.trusted_git_runtime_manifest_sha256
            assert receipt.workspace_snapshot == clean
            assert receipt.workspace_snapshot_sha256 == clean.sha256
            assert receipt.git_runtime_evidence_sha256 == git_runtime_sha
            assert receipt.task_max_runtime_seconds == task.budget.max_runtime_seconds
            assert receipt.task_max_output_bytes == task.budget.max_output_bytes
            assert receipt.product_pilot_started is True
            assert receipt.executor_capability_authenticated is True
            assert receipt.fresh_substrate_revalidated is True
            assert receipt.workspace_snapshot_frozen is True
            assert receipt.workspace_clean is True
            assert receipt.git_runtime_stable is True
            assert receipt.execution_plan_materialized is True
            assert receipt.task_execution_authorized is True
            assert receipt.one_shot_execution_required is True
            assert receipt.pre_launch_substrate_revalidation_required is True
            assert receipt.pre_launch_workspace_snapshot_revalidation_required is True
            assert receipt.task_execution_started is False
            assert receipt.task_execution_completed is False
            assert receipt.local_commit_authorized is False
            assert receipt.remote_write_authorized is False
            assert receipt.production_activation_authorized is False
            assert receipt.nonce_reusable is False
            assert receipt.next_boundary_task_execution_required is True

            live = plan._get_live_product_pilot_execution_plan_inputs(receipt)
            assert live is not None
            assert live["executor_capability"] is cap
            assert live["workspace_snapshot"] == clean

            serialized = plan.PilotExactTaskProductPilotExecutionPlanReceipt.from_mapping(
                receipt.to_dict()
            )
            assert serialized == receipt
            assert serialized.plan_authenticated is False

            replayed_capability = (
                capability.PilotExactTaskProductPilotExecutorCapabilityReceipt.from_mapping(
                    cap.to_dict()
                )
            )
            assert replayed_capability.capability_authenticated is False
            _reject(
                lambda: plan._materialize_verified_product_pilot_execution_plan(
                    replayed_capability
                )
            )

            for field, value in (
                ("executor_capability_authenticated", False),
                ("fresh_substrate_revalidated", False),
                ("workspace_snapshot_frozen", False),
                ("workspace_clean", False),
                ("git_runtime_stable", False),
                ("execution_plan_materialized", False),
                ("task_execution_authorized", False),
                ("one_shot_execution_required", False),
                ("pre_launch_substrate_revalidation_required", False),
                ("pre_launch_workspace_snapshot_revalidation_required", False),
                ("task_execution_started", True),
                ("task_execution_completed", True),
                ("local_commit_authorized", True),
                ("remote_write_authorized", True),
                ("push_authorized", True),
                ("pr_mutation_authorized", True),
                ("merge_authorized", True),
                ("release_authorized", True),
                ("deploy_authorized", True),
                ("production_activation_authorized", True),
                ("nonce_reusable", True),
                ("next_boundary_task_execution_required", False),
            ):
                raw = receipt.to_dict()
                raw[field] = value
                _reject(
                    lambda raw=raw: plan.PilotExactTaskProductPilotExecutionPlanReceipt.from_mapping(
                        raw
                    )
                )

            dirty = _snapshot(task, staged_bytes=1)
            with patch.object(
                plan,
                "_capture_workspace_snapshot",
                return_value=(dirty, git_runtime_sha),
            ):
                assert receipt.plan_authenticated is False

        _reject(
            lambda: plan.PilotExactTaskProductPilotExecutionPlanReceipt.from_mapping(
                {
                    **receipt.to_dict(),
                    "workspace_snapshot": {
                        **receipt.workspace_snapshot.to_dict(),
                        "staged_patch_bytes": 1,
                    },
                }
            )
        )
    finally:
        if capability_temp is not None:
            capability_temp.cleanup()
        if tx_temp is not None:
            tx_temp.cleanup()
        if auth_temp is not None:
            auth_temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(plan.PilotExactTaskProductPilotExecutionPlanReceipt.__dataclass_fields__)
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        plan.materialize_pilot_exact_task_product_pilot_execution_plan
    )
    assert tuple(public.parameters) == ("executor_capability",)

    source = code_of(SOURCE)
    lower = source.lower()
    assert "_GitWorkspaceEvidence" in source
    for forbidden in (
        "run_verified_tier_a_command",
        "run_single_verified_tier_a_command_with_receipt",
        "subprocess.",
        "requests.",
        "urllib.",
        "socket.",
        "git push",
        "create_pull_request",
        "merge_pull_request",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden.lower() not in lower


if __name__ == "__main__":
    run_contract()
