"""Adversarial contract for ADR-DC-108 one-shot product-pilot execution."""
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
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_workspace_snapshot as workspace_snapshot  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_plan as plan  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution as execution  # noqa: E402
from kaliv_dev_control import tier_a_command_receipt as command_receipt_boundary  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
from kaliv_dev_control.tier_a_command_receipt import TierACommandReceipt  # noqa: E402
from kaliv_dev_control.tier_a_result import TierAExecutionResult, TierAOutputStream  # noqa: E402
import rsi_pilot_exact_task_product_pilot_executor_capability_contract as capability_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import _authority_fixture  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-execution-receipt-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_execution.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-108 unexpectedly accepted unsafe execution state")


def _stream(payload: bytes) -> TierAOutputStream:
    return TierAOutputStream(
        captured=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        total_bytes=len(payload),
        truncated=False,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        # The portable contract patches only the final Tier-A launch. Native
        # Windows launch coverage remains in the dedicated isolation workflow.
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    capability_temp = None
    git_run_patch = None
    try:
        auth_temp, tx_temp, admitted, task = capability_contract._admission(fixture)
        capability_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-execution-"
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

        def audited_git_run(args, **kwargs):
            assert isinstance(args, tuple)
            assert args
            observed.append(args)
            if args == ("--version",):
                return b"git version adr-dc-108-fixture\n"
            if args == ("rev-parse", "--show-toplevel"):
                return (os.fspath(workspace) + "\n").encode("utf-8")
            if args == ("rev-parse", "HEAD"):
                return (task.base_sha + "\n").encode("ascii")
            if args[0] == "diff":
                return b""
            if args == ("ls-files", "--others", "--exclude-standard", "-z"):
                return b""
            raise AssertionError(f"unexpected trusted Git command: {args!r}")

        git_run_patch = patch.object(
            authority["git_runner"], "run", side_effect=audited_git_run
        )
        git_run_patch.start()

        frozen = workspace_snapshot.materialize_pilot_exact_task_product_pilot_workspace_snapshot(
            executor_capability
        )
        execution_plan = plan.materialize_pilot_exact_task_product_pilot_execution_plan(
            frozen
        )
        assert execution_plan.plan_authenticated is True

        result = TierAExecutionResult.create(
            task_id=task.task_id,
            task_sha256=execution_plan.development_task_sha256,
            base_sha=task.base_sha,
            command_id=VERSION_CHECK_COMMAND_ID,
            plan_sha256=execution_plan.sha256,
            lease_sha256=execution_plan.lease_sha256,
            signed_report_sha256=execution_plan.physical_report_sha256,
            returncode=0,
            duration_ms=11,
            timed_out=False,
            max_output_bytes=task.budget.max_output_bytes,
            stdout=_stream(b"2.0.13\n"),
            stderr=_stream(b""),
        )
        tier_a_receipt = TierACommandReceipt.create(
            task=task,
            git_runtime=authority["git_runner"].evidence(),
            result=result,
            before=execution_plan.workspace_snapshot,
            after=execution_plan.workspace_snapshot,
            reset=None,
        )
        assert tier_a_receipt.passed is True

        launch_calls = []

        def fake_launch(*args, **kwargs):
            launch_calls.append((args, kwargs))
            assert args[0] is task
            assert args[1] is authority["catalog"]
            assert args[2] is authority["toolchain"]
            assert args[3] is authority["attestation"]
            assert args[4] is authority["physical_verifier"]
            assert kwargs["git_runner"] is authority["git_runner"]
            assert kwargs["signed_runtime_closure"] is authority["signed_closure"]
            assert kwargs["runtime_closure_verifier"] is authority["runtime_verifier"]
            assert kwargs["trusted_runtime_root"] == authority["trusted"]
            assert kwargs["workspace_root"] == authority["workspace"]
            assert kwargs["control_plane_root"] == authority["control"]
            assert kwargs["expected_workspace_snapshot"] is execution_plan.workspace_snapshot
            assert (
                kwargs["expected_workspace_snapshot"].sha256
                == frozen.workspace_snapshot_sha256
            )
            assert kwargs["process_memory_bytes"] == execution_plan.process_memory_bytes
            assert kwargs["active_process_limit"] == execution_plan.active_process_limit
            return tier_a_receipt

        with patch.object(
            command_receipt_boundary,
            "run_single_verified_tier_a_command_with_receipt",
            side_effect=fake_launch,
        ):
            receipt = execution.execute_pilot_exact_task_product_pilot_plan(
                execution_plan
            )
            assert len(launch_calls) == 1

            # A separately materialized plan with the same signed execution nonce
            # must still be spent. One-shot authority is nonce-scoped, not tied
            # merely to Python object identity.
            second_plan = plan.materialize_pilot_exact_task_product_pilot_execution_plan(
                frozen
            )
            assert second_plan is not execution_plan
            assert second_plan.execution_nonce_sha256 == execution_plan.execution_nonce_sha256
            _reject(
                lambda: execution.execute_pilot_exact_task_product_pilot_plan(
                    second_plan
                )
            )
            _reject(
                lambda: execution.execute_pilot_exact_task_product_pilot_plan(
                    execution_plan
                )
            )
            assert len(launch_calls) == 1

        assert execution._product_pilot_execution_plan_consumed(execution_plan) is True
        assert receipt.execution_authenticated is True
        assert receipt.execution_plan_sha256 == execution_plan.sha256
        assert receipt.workspace_snapshot_receipt_sha256 == frozen.sha256
        assert receipt.executor_capability_sha256 == frozen.executor_capability_sha256
        assert receipt.execution_admission_sha256 == frozen.execution_admission_sha256
        assert receipt.execution_nonce_sha256 == frozen.execution_nonce_sha256
        assert receipt.development_task_id == task.task_id
        assert receipt.development_task_sha256 == execution_plan.development_task_sha256
        assert receipt.development_task_base_sha == task.base_sha
        assert receipt.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert receipt.workspace_snapshot_sha256 == frozen.workspace_snapshot_sha256
        assert receipt.tier_a_command_receipt is tier_a_receipt
        assert receipt.tier_a_command_receipt_sha256 == tier_a_receipt.sha256
        assert receipt.product_pilot_started is True
        assert receipt.execution_plan_authenticated_at_launch is True
        assert receipt.task_execution_consumed is True
        assert receipt.one_shot_execution_enforced is True
        assert receipt.exact_pre_execution_snapshot_verified is True
        assert receipt.tier_a_command_receipt_verified is True
        assert receipt.task_execution_started is True
        assert receipt.task_execution_completed is True
        assert receipt.task_execution_passed is True
        assert receipt.workspace_unchanged is True
        assert receipt.workspace_reset_performed is False
        assert receipt.recovery_required is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False
        assert receipt.next_boundary_execution_verification_required is True

        reloaded = execution.PilotExactTaskProductPilotExecutionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.execution_authenticated is False

        for field, value in (
            ("product_pilot_started", False),
            ("execution_plan_authenticated_at_launch", False),
            ("task_execution_consumed", False),
            ("one_shot_execution_enforced", False),
            ("exact_pre_execution_snapshot_verified", False),
            ("tier_a_command_receipt_verified", False),
            ("task_execution_started", False),
            ("task_execution_completed", False),
            ("task_execution_passed", False),
            ("workspace_unchanged", False),
            ("workspace_reset_performed", True),
            ("recovery_required", True),
            ("local_commit_authorized", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("next_boundary_execution_verification_required", False),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: execution.PilotExactTaskProductPilotExecutionReceipt.from_mapping(
                    raw
                )
            )

        raw = receipt.to_dict()
        raw["tier_a_command_receipt"] = dict(raw["tier_a_command_receipt"])
        raw["tier_a_command_receipt"]["command_id"] = "modelrig.other.check"
        _reject(
            lambda: execution.PilotExactTaskProductPilotExecutionReceipt.from_mapping(
                raw
            )
        )
    finally:
        if git_run_patch is not None:
            git_run_patch.stop()
        if capability_temp is not None:
            capability_temp.cleanup()
        if tx_temp is not None:
            tx_temp.cleanup()
        if auth_temp is not None:
            auth_temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(execution.PilotExactTaskProductPilotExecutionReceipt.__dataclass_fields__)
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    nested = schema["properties"]["tier_a_command_receipt"]
    assert set(nested["properties"]) == set(TierACommandReceipt.__dataclass_fields__)
    assert set(nested["required"]) == set(TierACommandReceipt.__dataclass_fields__)
    assert nested["additionalProperties"] is False

    public = inspect.signature(
        execution.execute_pilot_exact_task_product_pilot_plan
    )
    assert tuple(public.parameters) == ("execution_plan",)

    source = code_of(SOURCE)
    lowered = source.lower()
    assert "run_single_verified_tier_a_command_with_receipt" in source
    assert "expected_workspace_snapshot=plan.workspace_snapshot" in source
    for forbidden_text in (
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
        assert forbidden_text not in lowered


if __name__ == "__main__":
    run_contract()
