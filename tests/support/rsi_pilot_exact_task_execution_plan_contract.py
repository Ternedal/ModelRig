"""Adversarial contract for ADR-DC-037 exact workspace-snapshot-bound launch plan."""
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
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-037 unexpectedly accepted invalid authority")


def _materialized_capability():
    source_temp, ledger_temp, receipt = _live_receipt()
    capability_temp = tempfile.TemporaryDirectory(
        prefix="rsi-execution-plan-capability-"
    )
    requirements = plan_req.build_pilot_exact_task_execution_plan_requirements(
        receipt
    )
    task = _task(requirements)
    task_binding = binding._bind_verified_development_task(
        plan_requirements=requirements,
        admission_receipt=receipt,
        registry_payload=_registry(requirements, task),
    )
    fixture = _authority_fixture(
        Path(capability_temp.name).resolve(),
        task,
    )
    impl = capability._implementation
    original_path_sha = impl._path_sha256

    def scoped_path_sha(path: Path) -> str:
        candidate = Path(path)
        if candidate == fixture["workspace"]:
            return task_binding.workspace_root_path_sha256
        return original_path_sha(candidate)

    def forbidden_git_run(*_args, **_kwargs):
        raise AssertionError(
            "ADR-DC-036 capability materialization must remain process-free"
        )

    with patch.object(
        impl,
        "_path_sha256",
        side_effect=scoped_path_sha,
    ), patch.object(
        fixture["git_runner"],
        "run",
        side_effect=forbidden_git_run,
    ):
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

    return (
        source_temp,
        ledger_temp,
        capability_temp,
        proof,
        task,
        fixture,
    )


def _git_reader(
    *,
    workspace: Path,
    base_sha: str,
    staged: bytes = b"",
    unstaged: bytes = b"",
    untracked: bytes = b"",
):
    calls: list[tuple[str, ...]] = []

    def run(args, *, cwd, **_kwargs):
        args = tuple(args)
        calls.append(args)
        assert Path(cwd) == workspace
        if args == ("rev-parse", "--show-toplevel"):
            return (os.fspath(workspace) + "\n").encode("utf-8")
        if args == ("rev-parse", "HEAD"):
            return (base_sha + "\n").encode("ascii")
        if args == (
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        ):
            return staged
        if args == (
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        ):
            return unstaged
        if args == (
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ):
            return untracked
        raise AssertionError(f"ADR-DC-037 attempted unexpected Git command: {args!r}")

    return calls, run


def run_contract() -> None:
    if os.name == "nt":
        # The synthetic trusted-Git helper fixture is POSIX-only. Native Windows
        # substrate remains covered by the existing Windows DevControl jobs.
        return

    (
        source_temp,
        ledger_temp,
        capability_temp,
        proof,
        task,
        fixture,
    ) = _materialized_capability()
    try:
        workspace = fixture["workspace"]
        (workspace / ".git").mkdir()
        staged = (
            b"diff --git a/VERSION b/VERSION\n"
            b"index 1111111..2222222 100644\n"
            b"--- a/VERSION\n"
            b"+++ b/VERSION\n"
            b"@@ -1 +1 @@\n"
            b"-old\n"
            b"+new\n"
        )
        calls, reader = _git_reader(
            workspace=workspace,
            base_sha=task.base_sha,
            staged=staged,
        )

        def forbidden_evidence(*_args, **_kwargs):
            raise AssertionError(
                "ADR-DC-037 must not run TrustedGitRunner.evidence()"
            )

        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=reader,
        ), patch.object(
            fixture["git_runner"],
            "evidence",
            side_effect=forbidden_evidence,
        ):
            plan = execution_plan.materialize_pilot_exact_task_execution_plan(
                proof
            )

        assert plan.materialization_authenticated is True
        assert plan.executor_capability is proof
        assert plan.executor_capability_sha256 == proof.sha256
        assert plan.execution_nonce_sha256 == proof.execution_nonce_sha256
        assert plan.fixed_command_id == proof.fixed_command_id
        assert plan.fixed_command_plan.command_id == proof.fixed_command_id
        assert plan.fixed_command_plan.max_output_bytes == task.budget.max_output_bytes
        assert (
            plan.fixed_command_plan.source_environment_sha256
            == proof.source_environment_sha256
        )
        assert plan.workspace_snapshot.head_sha == task.base_sha
        assert plan.workspace_snapshot.staged_patch_bytes == len(staged)
        assert (
            plan.workspace_snapshot.staged_patch_sha256
            == hashlib.sha256(staged).hexdigest()
        )
        assert plan.workspace_snapshot.unstaged_patch_sha256 == EMPTY_SHA256
        assert plan.workspace_snapshot.untracked_paths_sha256 == EMPTY_SHA256
        assert plan.execution_plan_materialized is True
        assert plan.execution_consumed is False
        assert plan.task_execution_started is False
        assert plan.task_execution_completed is False
        assert plan.local_commit_authorized is False
        assert plan.remote_write_authorized is False
        assert plan.production_activation_authorized is False

        assert calls == [
            ("rev-parse", "--show-toplevel"),
            ("rev-parse", "HEAD"),
            (
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            ),
            (
                "diff",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            ),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ]

        reloaded = execution_plan.PilotExactTaskExecutionPlan.from_mapping(
            plan.to_dict()
        )
        assert reloaded == plan
        assert reloaded.sha256 == plan.sha256
        assert reloaded.materialization_authenticated is False

        _reject(
            lambda: execution_plan.PilotExactTaskExecutionPlan.from_mapping(
                {**plan.to_dict(), "execution_consumed": True}
            )
        )
        _reject(
            lambda: execution_plan.PilotExactTaskExecutionPlan.from_mapping(
                {**plan.to_dict(), "task_execution_started": True}
            )
        )
        _reject(
            lambda: execution_plan.PilotExactTaskExecutionPlan.from_mapping(
                {**plan.to_dict(), "production_activation_authorized": True}
            )
        )

        wrong_head_calls, wrong_head = _git_reader(
            workspace=workspace,
            base_sha="f" * 40,
        )
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=wrong_head,
        ):
            _reject(
                lambda: execution_plan.materialize_pilot_exact_task_execution_plan(
                    proof
                )
            )
        assert wrong_head_calls

        dirty_calls, dirty_reader = _git_reader(
            workspace=workspace,
            base_sha=task.base_sha,
            unstaged=b"dirty\n",
        )
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=dirty_reader,
        ):
            _reject(
                lambda: execution_plan.materialize_pilot_exact_task_execution_plan(
                    proof
                )
            )
        assert dirty_calls

        untracked_calls, untracked_reader = _git_reader(
            workspace=workspace,
            base_sha=task.base_sha,
            untracked=b"unexpected.txt\0",
        )
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=untracked_reader,
        ):
            _reject(
                lambda: execution_plan.materialize_pilot_exact_task_execution_plan(
                    proof
                )
            )
        assert untracked_calls

        # A serialized ADR-DC-036 capability is durable evidence only and cannot
        # mint a new live launch plan.
        replayed_capability = capability.PilotExactTaskExecutorCapability.from_mapping(
            proof.to_dict()
        )
        _reject(
            lambda: execution_plan.materialize_pilot_exact_task_execution_plan(
                replayed_capability
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(plan.to_dict())
        assert set(schema["required"]) == set(plan.to_dict())
        assert props["execution_plan_materialized"]["const"] is True
        assert props["execution_consumed"]["const"] is False
        assert props["task_execution_started"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            execution_plan.materialize_pilot_exact_task_execution_plan
        ).parameters
        assert tuple(public_parameters) == ("capability",)

        source = inspect.getsource(execution_plan)
        assert "run_verified_tier_a_command" not in source
        assert "run_single_verified_tier_a_command_with_receipt" not in source
        assert ".reset_to_base(" not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
        assert ".evidence()" not in source
    finally:
        capability_temp.cleanup()
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
