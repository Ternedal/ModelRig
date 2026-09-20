"""Adversarial contract for ADR-DC-109 execution verification/recovery closure."""
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
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_verification as verification  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
from kaliv_dev_control.tier_a_command_receipt import GitWorkspaceSnapshot, TierACommandReceipt  # noqa: E402
from kaliv_dev_control.tier_a_result import TierAExecutionResult, TierAOutputStream  # noqa: E402
import rsi_pilot_exact_task_product_pilot_executor_capability_contract as capability_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import _authority_fixture  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-execution-verification-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_execution_verification.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-109 unexpectedly accepted unsafe closure state")


def _stream(payload: bytes) -> TierAOutputStream:
    return TierAOutputStream(
        captured=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        total_bytes=len(payload),
        truncated=False,
    )


def _result(task, execution_plan, *, returncode: int) -> TierAExecutionResult:
    return TierAExecutionResult.create(
        task_id=task.task_id,
        task_sha256=execution_plan.development_task_sha256,
        base_sha=task.base_sha,
        command_id=VERSION_CHECK_COMMAND_ID,
        plan_sha256=execution_plan.sha256,
        lease_sha256=execution_plan.lease_sha256,
        signed_report_sha256=execution_plan.physical_report_sha256,
        returncode=returncode,
        duration_ms=9,
        timed_out=False,
        max_output_bytes=task.budget.max_output_bytes,
        stdout=_stream(b"2.0.13\n" if returncode == 0 else b""),
        stderr=_stream(b"" if returncode == 0 else b"failed\n"),
    )


def _execution_receipt(
    *,
    execution_plan,
    command: TierACommandReceipt,
    passed: bool,
):
    return execution.PilotExactTaskProductPilotExecutionReceipt(
        execution_plan_sha256=execution_plan.sha256,
        workspace_snapshot_receipt_sha256=execution_plan.workspace_snapshot_receipt_sha256,
        executor_capability_sha256=execution_plan.executor_capability_sha256,
        execution_admission_sha256=execution_plan.execution_admission_sha256,
        execution_nonce_sha256=execution_plan.execution_nonce_sha256,
        development_task_id=execution_plan.development_task_id,
        development_task_sha256=execution_plan.development_task_sha256,
        development_task_base_sha=execution_plan.development_task_base_sha,
        fixed_command_id=execution_plan.fixed_command_id,
        workspace_snapshot_sha256=execution_plan.workspace_snapshot_sha256,
        tier_a_command_receipt_sha256=command.sha256,
        tier_a_command_receipt=command,
        product_pilot_started=True,
        execution_plan_authenticated_at_launch=True,
        task_execution_consumed=True,
        one_shot_execution_enforced=True,
        exact_pre_execution_snapshot_verified=True,
        tier_a_command_receipt_verified=True,
        task_execution_started=True,
        task_execution_completed=True,
        task_execution_passed=passed,
        workspace_unchanged=command.workspace_unchanged,
        workspace_reset_performed=command.workspace_reset_performed,
        recovery_required=not passed,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    capability_temp = None
    git_run_patch = None
    drift_path = None
    try:
        auth_temp, tx_temp, admitted, task = capability_contract._admission(fixture)
        capability_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-execution-verification-"
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

        workspace = authority["workspace"]
        (workspace / ".git").mkdir()
        observed: list[tuple[str, ...]] = []

        def audited_git_run(args, **kwargs):
            assert isinstance(args, tuple)
            assert args
            observed.append(args)
            if args == ("--version",):
                return b"git version adr-dc-109-fixture\\n"
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
        execution_plan = plan.materialize_pilot_exact_task_product_pilot_execution_plan(
            frozen
        )
        clean = execution_plan.workspace_snapshot

        passing_command = TierACommandReceipt.create(
            task=task,
            git_runtime=authority["git_runner"].evidence(),
            result=_result(task, execution_plan, returncode=0),
            before=clean,
            after=clean,
            reset=None,
        )
        passing_execution = _execution_receipt(
            execution_plan=execution_plan,
            command=passing_command,
            passed=True,
        )
        execution._mark_product_pilot_execution_authenticated(
            passing_execution,
            executor_capability=executor_capability,
        )
        assert passing_execution.execution_authenticated is True

        verified = verification.verify_pilot_exact_task_product_pilot_execution(
            passing_execution
        )
        assert observed
        assert {args[0] for args in observed} <= {"--version", "rev-parse", "diff", "ls-files"}
        assert verified.execution_receipt_sha256 == passing_execution.sha256
        assert verified.execution_plan_sha256 == execution_plan.sha256
        assert verified.execution_nonce_sha256 == execution_plan.execution_nonce_sha256
        assert verified.development_task_id == task.task_id
        assert verified.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert verified.tier_a_command_receipt_sha256 == passing_command.sha256
        assert verified.pre_execution_workspace_snapshot_sha256 == clean.sha256
        assert verified.expected_post_execution_workspace_snapshot_sha256 == clean.sha256
        assert verified.post_execution_workspace_snapshot_sha256 == clean.sha256
        assert verified.post_execution_workspace_snapshot.sha256 == clean.sha256
        assert verified.execution_outcome_passed is True
        assert verified.recovery_required is False
        assert verified.recovery_verified is False
        assert verified.execution_receipt_authenticated is True
        assert verified.tier_a_execution_verified is True
        assert verified.post_execution_workspace_verified is True
        assert verified.product_pilot_execution_closed is True
        assert verified.first_product_pilot_task_closed is True
        assert verified.local_commit_authorized is False
        assert verified.remote_write_authorized is False
        assert verified.production_activation_authorized is False
        assert verified.nonce_reusable is False
        assert verified.next_boundary_stack_consolidation_required is True

        reloaded = (
            verification.PilotExactTaskProductPilotExecutionVerificationReceipt.from_mapping(
                verified.to_dict()
            )
        )
        assert reloaded == verified
        assert reloaded.sha256 == verified.sha256

        # Verify the recovery branch separately: a failed command may close only
        # when the canonical Tier-A receipt proves an exact-base reset and the
        # fresh current workspace equals that reset snapshot.
        mutated = GitWorkspaceSnapshot(
            head_sha=task.base_sha,
            staged_patch_sha256="1" * 64,
            staged_patch_bytes=17,
            unstaged_patch_sha256=clean.unstaged_patch_sha256,
            unstaged_patch_bytes=0,
            untracked_paths_sha256=clean.untracked_paths_sha256,
            untracked_path_count=0,
        )
        failed_command = TierACommandReceipt.create(
            task=task,
            git_runtime=authority["git_runner"].evidence(),
            result=_result(task, execution_plan, returncode=1),
            before=clean,
            after=mutated,
            reset=clean,
        )
        failed_execution = _execution_receipt(
            execution_plan=execution_plan,
            command=failed_command,
            passed=False,
        )
        execution._mark_product_pilot_execution_authenticated(
            failed_execution,
            executor_capability=executor_capability,
        )
        recovered = verification.verify_pilot_exact_task_product_pilot_execution(
            failed_execution
        )
        assert recovered.execution_outcome_passed is False
        assert recovered.recovery_required is True
        assert recovered.recovery_verified is True
        assert recovered.expected_post_execution_workspace_snapshot_sha256 == clean.sha256
        assert recovered.post_execution_workspace_snapshot_sha256 == clean.sha256
        assert recovered.product_pilot_execution_closed is True

        drift_path = workspace / "adr-dc-109-post-execution-drift.tmp"
        drift_path.write_text("unsafe\n", encoding="utf-8")
        _reject(
            lambda: verification.verify_pilot_exact_task_product_pilot_execution(
                passing_execution
            )
        )
        drift_path.unlink()
        drift_path = None

        for field, value in (
            ("execution_receipt_authenticated", False),
            ("tier_a_execution_verified", False),
            ("post_execution_workspace_verified", False),
            ("product_pilot_execution_closed", False),
            ("first_product_pilot_task_closed", False),
            ("local_commit_authorized", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("next_boundary_stack_consolidation_required", False),
        ):
            raw = verified.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: verification.PilotExactTaskProductPilotExecutionVerificationReceipt.from_mapping(
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
    fields = set(
        verification.PilotExactTaskProductPilotExecutionVerificationReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    nested = schema["properties"]["post_execution_workspace_snapshot"]
    assert set(nested["properties"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert set(nested["required"]) == set(GitWorkspaceSnapshot.__dataclass_fields__)
    assert nested["additionalProperties"] is False

    public = inspect.signature(
        verification.verify_pilot_exact_task_product_pilot_execution
    )
    assert tuple(public.parameters) == ("execution_receipt",)

    source = code_of(SOURCE)
    lowered = source.lower()
    assert "_gitworkspaceevidence" in lowered
    assert ".snapshot()" in lowered
    for forbidden_text in (
        ".reset_to_base(",
        "run_single_verified_tier_a_command_with_receipt",
        "run_verified_tier_a_command",
        "subprocess.",
        "requests.",
        "urllib.",
        "socket.",
        "git push",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden_text not in lowered


if __name__ == "__main__":
    run_contract()
