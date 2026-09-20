"""Adversarial contract for ADR-DC-107 product-pilot execution plan."""
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
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_plan as plan  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
from kaliv_dev_control.tier_a_command_receipt import GitWorkspaceSnapshot  # noqa: E402
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


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-107 unexpectedly accepted unsafe execution-plan state")


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    capability_temp = None
    drift_path = None
    git_run_patch = None
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

        workspace = authority["workspace"]
        (workspace / ".git").mkdir()
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
            if args == ("rev-parse", "--show-toplevel"):
                return (os.fspath(workspace) + "\n").encode("utf-8")
            if args == ("rev-parse", "HEAD"):
                return (task.base_sha + "\n").encode("ascii")
            if args[0] == "diff":
                return b""
            if args == ("ls-files", "--others", "--exclude-standard", "-z"):
                paths = sorted(
                    path.relative_to(workspace).as_posix()
                    for path in workspace.rglob("*")
                    if path.is_file() and ".git" not in path.relative_to(workspace).parts
                )
                return b"".join(
                    item.encode("utf-8") + b"\0"
                    for item in paths
                )
            raise AssertionError(f"unexpected trusted Git command: {args!r}")

        git_run_patch = patch.object(
            authority["git_runner"], "run", side_effect=audited_git_run
        )
        git_run_patch.start()

        frozen = workspace_snapshot.materialize_pilot_exact_task_product_pilot_workspace_snapshot(
            executor_capability
        )
        assert frozen.snapshot_authenticated is True
        assert frozen.fixed_command_id == VERSION_CHECK_COMMAND_ID
        exact_snapshot = frozen.workspace_snapshot
        exact_snapshot_sha = frozen.workspace_snapshot_sha256
        git_calls_before_plan = len(observed)

        def forbidden_snapshot_materialization(*_args, **_kwargs):
            raise AssertionError(
                "ADR-DC-107 must consume ADR-DC-106, never replace its snapshot"
            )

        with patch.object(
            workspace_snapshot,
            "materialize_pilot_exact_task_product_pilot_workspace_snapshot",
            side_effect=forbidden_snapshot_materialization,
        ):
            receipt = plan.materialize_pilot_exact_task_product_pilot_execution_plan(
                frozen
            )

        assert receipt.plan_authenticated is True
        assert receipt.workspace_snapshot_receipt_sha256 == frozen.sha256
        assert receipt.executor_capability_sha256 == frozen.executor_capability_sha256
        assert receipt.execution_admission_sha256 == frozen.execution_admission_sha256
        assert receipt.execution_nonce_sha256 == frozen.execution_nonce_sha256
        assert receipt.development_task_id == task.task_id
        assert receipt.development_task_sha256 == frozen.development_task_sha256
        assert receipt.development_task_base_sha == task.base_sha
        assert receipt.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert receipt.workspace_snapshot is exact_snapshot
        assert receipt.workspace_snapshot_sha256 == exact_snapshot_sha
        assert receipt.workspace_snapshot.sha256 == exact_snapshot_sha
        assert receipt.catalog_sha256 == frozen.catalog_sha256
        assert receipt.toolchain_sha256 == frozen.toolchain_sha256
        assert receipt.lease_sha256 == frozen.lease_sha256
        assert receipt.signed_runtime_closure_sha256 == frozen.signed_runtime_closure_sha256
        assert receipt.trusted_git_runtime_receipt_sha256 == frozen.trusted_git_runtime_receipt_sha256
        assert receipt.trusted_git_runtime_manifest_sha256 == frozen.trusted_git_runtime_manifest_sha256
        assert receipt.workspace_snapshot_authenticated is True
        assert receipt.exact_workspace_snapshot_bound is True
        assert receipt.command_specification_bound is True
        assert receipt.execution_plan_materialized is True
        assert receipt.task_execution_authorized is True
        assert receipt.one_shot_task_execution_required is True
        assert receipt.pre_launch_substrate_revalidation_required is True
        assert receipt.pre_launch_workspace_snapshot_revalidation_required is True
        assert receipt.task_execution_started is False
        assert receipt.task_execution_completed is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False
        assert receipt.next_boundary_task_execution_required is True

        # ADR-DC-107 may trigger ADR-DC-106's live revalidation reads, but it
        # never materializes or substitutes a second snapshot. The durable plan
        # keeps the exact original snapshot object/hash.
        assert len(observed) > git_calls_before_plan
        assert {args[0] for args in observed} <= {"rev-parse", "diff", "ls-files"}

        live = plan._get_live_product_pilot_execution_plan_inputs(receipt)
        assert live is not None
        assert live["workspace_snapshot_receipt"] is frozen
        assert live["workspace_snapshot"].sha256 == exact_snapshot_sha
        assert live["executor_capability"] is executor_capability
        assert live["task"] == task

        serialized = plan.PilotExactTaskProductPilotExecutionPlanReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.plan_authenticated is False

        replayed_snapshot = (
            workspace_snapshot.PilotExactTaskProductPilotWorkspaceSnapshotReceipt.from_mapping(
                frozen.to_dict()
            )
        )
        assert replayed_snapshot.snapshot_authenticated is False
        _reject(
            lambda: plan.materialize_pilot_exact_task_product_pilot_execution_plan(
                replayed_snapshot
            )
        )

        drift_path = workspace / "adr-dc-107-post-plan-drift.tmp"
        drift_path.write_text("changed\n", encoding="utf-8")
        assert receipt.plan_authenticated is False
        drift_path.unlink()
        drift_path = None

        for field, value in (
            ("workspace_snapshot_authenticated", False),
            ("exact_workspace_snapshot_bound", False),
            ("command_specification_bound", False),
            ("execution_plan_materialized", False),
            ("task_execution_authorized", False),
            ("one_shot_task_execution_required", False),
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

        raw = receipt.to_dict()
        raw["workspace_snapshot"] = dict(raw["workspace_snapshot"])
        raw["workspace_snapshot"]["head_sha"] = "f" * 40
        _reject(
            lambda: plan.PilotExactTaskProductPilotExecutionPlanReceipt.from_mapping(
                raw
            )
        )
    finally:
        if git_run_patch is not None:
            git_run_patch.stop()
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
    fields = set(plan.PilotExactTaskProductPilotExecutionPlanReceipt.__dataclass_fields__)
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    nested = schema["properties"]["workspace_snapshot"]
    assert set(nested["properties"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert set(nested["required"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert nested["additionalProperties"] is False

    public = inspect.signature(
        plan.materialize_pilot_exact_task_product_pilot_execution_plan
    )
    assert tuple(public.parameters) == ("workspace_snapshot_receipt",)

    source = code_of(SOURCE)
    lowered = source.lower()
    assert "_get_live_product_pilot_workspace_snapshot_inputs" in source
    for forbidden_text in (
        "_gitworkspaceevidence",
        "_capture_workspace_snapshot(",
        "materialize_pilot_exact_task_product_pilot_workspace_snapshot(",
        "git_runner.run",
        "run_verified_tier_a_command",
        "run_single_verified_tier_a_command_with_receipt",
        "subprocess.",
        "requests.",
        "urllib.",
        "socket.",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden_text not in lowered


if __name__ == "__main__":
    run_contract()
