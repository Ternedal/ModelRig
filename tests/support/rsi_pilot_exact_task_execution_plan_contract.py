"""Focused adversarial contract for ADR-DC-037 exact execution-plan materialization."""
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
DEVCONTROL_TESTS = ROOT / "devcontrol" / "tests"
if str(DEVCONTROL_TESTS) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_TESTS))

import kaliv_dev_control.improvement_pilot_exact_task_development_task_binding as binding  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan as execution_plan  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan_requirements as plan_req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_executor_capability as capability  # noqa: E402
from rsi_pilot_exact_task_execution_plan_requirements_contract import _live_receipt  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import (  # noqa: E402
    _authority_fixture,
    _registry,
    _task,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-plan-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-037 unexpectedly accepted invalid input")


def _materialized_capability(receipt, root: Path):
    requirements = plan_req.build_pilot_exact_task_execution_plan_requirements(receipt)
    task = _task(requirements)
    task_binding = binding._bind_verified_development_task(
        plan_requirements=requirements,
        admission_receipt=receipt,
        registry_payload=_registry(requirements, task),
    )
    fixture = _authority_fixture(root, task)
    (fixture["workspace"] / ".git").mkdir()
    impl = capability._implementation
    original_path_sha = impl._path_sha256

    def scoped_path_sha(path: Path) -> str:
        candidate = Path(path)
        if candidate == fixture["workspace"]:
            return task_binding.workspace_root_path_sha256
        return original_path_sha(candidate)

    with patch.object(impl, "_path_sha256", side_effect=scoped_path_sha):
        proof = capability._materialize_verified_executor_capability(
            task_binding=task_binding,
            admission_receipt=receipt,
            catalog=fixture["catalog"],
            toolchain=fixture["toolchain"],
            isolation_attestation=fixture["attestation"],
            physical_verifier=fixture["physical_verifier"],
            signed_runtime_closure=fixture["signed_closure"],
            runtime_closure_verifier=fixture["runtime_verifier"],
            trusted_runtime_root=fixture["trusted"],
            git_runner=fixture["git_runner"],
            workspace_root=fixture["workspace"],
            control_plane_root=fixture["control"],
        )
    return task, fixture, proof


def _git_reader(workspace: Path, base_sha: str, *, head: str | None = None, untracked: bytes = b""):
    expected_head = base_sha if head is None else head

    def run(args, *, cwd, maximum, timeout_seconds):
        command = tuple(args)
        assert Path(cwd) == workspace
        assert maximum > 0
        assert timeout_seconds == 120
        if command == ("rev-parse", "--show-toplevel"):
            return (os.fspath(workspace) + "\n").encode("utf-8")
        if command == ("rev-parse", "HEAD"):
            return (expected_head + "\n").encode("ascii")
        if command and command[0] == "diff":
            if "--cached" in command:
                return b"candidate staged patch\n"
            return b""
        if command[:3] == ("ls-files", "--others", "--exclude-standard"):
            return untracked
        raise AssertionError(f"unexpected trusted-Git command: {command!r}")

    return run


def run_contract() -> None:
    if os.name == "nt":
        # The upstream trusted-Git fixture uses a synthetic POSIX executable.
        # Native Windows coverage remains in the existing Tier-A Windows jobs.
        return

    source_temp, ledger_temp, receipt = _live_receipt()
    plan_temp = tempfile.TemporaryDirectory(prefix="rsi-execution-plan-")
    try:
        task, fixture, proof = _materialized_capability(
            receipt,
            Path(plan_temp.name).resolve(),
        )
        assert proof.execution_plan_materialized is False
        assert proof.materialization_authenticated is True

        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=_git_reader(fixture["workspace"], task.base_sha),
        ):
            plan = execution_plan.materialize_pilot_exact_task_execution_plan(proof)

        assert plan.schema == execution_plan.PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA
        assert plan.authority == execution_plan.PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY
        assert plan.executor_capability is proof
        assert plan.executor_capability_sha256 == proof.sha256
        assert plan.admission_receipt_sha256 == receipt.sha256
        assert plan.execution_nonce_sha256 == receipt.execution_nonce_sha256
        assert plan.development_task_id == task.task_id
        assert plan.development_task_sha256 == proof.development_task_sha256
        assert plan.fixed_command_id == proof.fixed_command_id
        assert plan.trusted_git_runtime_receipt_sha256 == (
            proof.trusted_git_runtime_receipt_sha256
        )
        assert plan.workspace_snapshot.head_sha == task.base_sha
        assert plan.workspace_snapshot.staged_patch_bytes > 0
        assert plan.workspace_snapshot.unstaged_patch_bytes == 0
        assert plan.workspace_snapshot.untracked_path_count == 0
        assert plan.workspace_snapshot_sha256 == plan.workspace_snapshot.sha256
        assert plan.workspace_head_sha == task.base_sha
        assert plan.executor_capability_materialized is True
        assert plan.workspace_snapshot_verified is True
        assert plan.workspace_head_verified is True
        assert plan.workspace_unstaged_and_untracked_absent is True
        assert plan.execution_plan_materialized is True
        assert plan.execution_consumed is False
        assert plan.task_execution_started is False
        assert plan.task_execution_completed is False
        assert plan.local_commit_authorized is False
        assert plan.remote_write_authorized is False
        assert plan.push_authorized is False
        assert plan.pr_mutation_authorized is False
        assert plan.merge_authorized is False
        assert plan.release_authorized is False
        assert plan.deploy_authorized is False
        assert plan.production_activation_authorized is False
        assert plan.materialization_authenticated is True

        live = execution_plan._get_live_execution_plan_inputs(plan)
        assert live is not None
        assert live["executor_capability"] is proof
        assert live["task"].to_dict() == task.to_dict()
        assert live["git_runner"] is fixture["git_runner"]
        assert live["workspace_snapshot"] is plan.workspace_snapshot

        # Durable audit evidence survives; live process-local plan authority does not.
        reloaded = execution_plan.PilotExactTaskExecutionPlan.from_mapping(plan.to_dict())
        assert reloaded == plan
        assert reloaded.sha256 == plan.sha256
        assert reloaded.materialization_authenticated is False
        assert execution_plan._get_live_execution_plan_inputs(reloaded) is None

        reloaded_capability = capability.PilotExactTaskExecutorCapability.from_mapping(
            proof.to_dict()
        )
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=_git_reader(fixture["workspace"], task.base_sha),
        ):
            _reject(
                lambda: execution_plan.materialize_pilot_exact_task_execution_plan(
                    reloaded_capability
                )
            )

        # A changed HEAD is not the signed DevelopmentTask base.
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=_git_reader(fixture["workspace"], task.base_sha, head="f" * 40),
        ):
            _reject(
                lambda: execution_plan.materialize_pilot_exact_task_execution_plan(proof)
            )

        # Untracked input is rejected before any task command can be staged or run.
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=_git_reader(
                fixture["workspace"], task.base_sha, untracked=b"rogue.txt\0"
            ),
        ):
            _reject(
                lambda: execution_plan.materialize_pilot_exact_task_execution_plan(proof)
            )

        tampered_snapshot = {
            **plan.workspace_snapshot.to_dict(),
            "unstaged_patch_bytes": 1,
        }
        _reject(
            lambda: execution_plan.PilotExactTaskExecutionPlan.from_mapping(
                {**plan.to_dict(), "workspace_snapshot": tampered_snapshot}
            )
        )
        for field in (
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: execution_plan.PilotExactTaskExecutionPlan.from_mapping(
                    {**plan.to_dict(), field: True}
                )
            )
        for field in (
            "executor_capability_materialized",
            "workspace_snapshot_verified",
            "workspace_head_verified",
            "workspace_unstaged_and_untracked_absent",
            "execution_plan_materialized",
        ):
            _reject(
                lambda field=field: execution_plan.PilotExactTaskExecutionPlan.from_mapping(
                    {**plan.to_dict(), field: False}
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(plan.to_dict())
        assert set(schema["required"]) == set(plan.to_dict())
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema"]["const"] == (
            execution_plan.PILOT_EXACT_TASK_EXECUTION_PLAN_SCHEMA
        )
        assert schema["properties"]["authority"]["const"] == (
            execution_plan.PILOT_EXACT_TASK_EXECUTION_PLAN_AUTHORITY
        )
        assert schema["properties"]["execution_plan_materialized"]["const"] is True
        assert schema["properties"]["execution_consumed"]["const"] is False

        source = inspect.getsource(execution_plan)
        assert "_GitWorkspaceEvidence" in source
        assert "run_verified_tier_a_command(" not in source
        assert "run_single_verified_tier_a_command_with_receipt(" not in source
        assert "_run_tier_a_launch_plan(" not in source
        assert "TrustedRuntimeClosureStager" not in source
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
        ):
            assert forbidden not in source.lower(), forbidden
    finally:
        plan_temp.cleanup()
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
