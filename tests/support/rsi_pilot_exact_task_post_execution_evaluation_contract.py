"""Adversarial contract for ADR-DC-040 mechanical post-execution evaluation."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_execution_transaction as execution_transaction,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_execution_evaluation as post_evaluation,
)
from rsi_pilot_exact_task_execution_plan_contract import _git_reader  # noqa: E402
from rsi_pilot_exact_task_execution_transaction_contract import (  # noqa: E402
    _live_reservation,
    _tier_a_receipt,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-post-execution-evaluation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-040 unexpectedly accepted invalid authority")


def _live_execution():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        reservation,
        plan,
        task,
        fixture,
        staged,
    ) = _live_reservation()
    execution_temp = tempfile.TemporaryDirectory(
        prefix="rsi-post-execution-evaluation-transaction-"
    )
    ledger = execution_transaction._PilotExactTaskExecutionTransactionLedger(
        Path(execution_temp.name).resolve()
    )
    tier_a = _tier_a_receipt(plan, task)
    _calls, reader = _git_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
    )
    times = iter(
        (
            "2026-09-15T05:00:00Z",
            "2026-09-15T05:00:01Z",
            "2026-09-15T05:00:02Z",
        )
    )
    with patch.object(
        fixture["git_runner"],
        "run",
        side_effect=reader,
    ), patch.object(
        execution_transaction,
        "run_single_verified_tier_a_command_with_receipt",
        return_value=tier_a,
    ):
        receipt = execution_transaction._execute_reserved_exact_task(
            prelaunch_reservation=reservation,
            ledger=ledger,
            now_provider=lambda: next(times),
        )
    assert receipt.transaction_authenticated is True
    assert receipt.task_execution_passed is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        reservation,
        receipt,
        plan,
        task,
        fixture,
        staged,
    )


def _evaluation_reader(
    *,
    workspace: Path,
    base_sha: str,
    staged: bytes,
    numstat: bytes,
    drift_after_numstat: bool = False,
):
    snapshot_number = 0
    calls: list[tuple[str, ...]] = []

    def run(args, *, cwd, **_kwargs):
        nonlocal snapshot_number
        args = tuple(args)
        calls.append(args)
        assert Path(cwd) == workspace
        if args == ("rev-parse", "--show-toplevel"):
            snapshot_number += 1
            return (os.fspath(workspace) + "\n").encode("utf-8")
        if args == ("rev-parse", "HEAD"):
            head = base_sha
            if drift_after_numstat and snapshot_number >= 2:
                head = "f" * 40
            return (head + "\n").encode("ascii")
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
            return b""
        if args == ("ls-files", "--others", "--exclude-standard", "-z"):
            return b""
        if args == (
            "diff",
            "--cached",
            "--numstat",
            "-z",
            "--no-renames",
            "--",
        ):
            return numstat
        raise AssertionError(f"ADR-DC-040 attempted unexpected Git command: {args!r}")

    return calls, run


def run_contract() -> None:
    if os.name == "nt":
        # Synthetic Trusted-Git fixture is POSIX-only. Native Windows substrate
        # remains covered by the existing Windows DevControl jobs.
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        reservation,
        execution_receipt,
        plan,
        task,
        fixture,
        staged,
    ) = _live_execution()
    try:
        numstat = b"1\t0\tVERSION\0"
        calls, reader = _evaluation_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            numstat=numstat,
        )
        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=reader,
        ):
            receipt = post_evaluation._evaluate_verified_pilot_exact_task_execution(
                execution_receipt=execution_receipt,
                now_provider=lambda: "2026-09-15T05:01:00Z",
            )

        assert len(calls) == 11
        assert receipt.evaluation_authenticated is True
        assert receipt.execution_transaction_sha256 == execution_receipt.sha256
        assert receipt.tier_a_receipt_sha256 == execution_receipt.tier_a_receipt_sha256
        assert receipt.execution_nonce_sha256 == execution_receipt.execution_nonce_sha256
        assert receipt.development_task_sha256 == execution_receipt.development_task_sha256
        assert receipt.task_id == task.task_id
        assert receipt.base_sha == task.base_sha
        assert receipt.fixed_command_plan_sha256 == plan.fixed_command_plan_sha256
        assert (
            receipt.pre_execution_workspace_snapshot_sha256
            == plan.workspace_snapshot_sha256
        )
        assert receipt.post_execution_workspace_snapshot == plan.workspace_snapshot
        assert (
            receipt.post_execution_workspace_snapshot_sha256
            == plan.workspace_snapshot_sha256
        )
        assert receipt.candidate_patch_sha256 == plan.workspace_snapshot.staged_patch_sha256
        assert receipt.candidate_patch_bytes == len(staged)
        assert receipt.candidate_numstat_sha256 == hashlib.sha256(numstat).hexdigest()
        assert receipt.changed_paths == ("VERSION",)
        assert receipt.changed_file_count == 1
        assert receipt.added_lines == 1
        assert receipt.deleted_lines == 0
        assert receipt.executed_command_id == plan.fixed_command_id
        assert receipt.required_tests == task.required_tests
        assert receipt.execution_transaction_authenticated is True
        assert receipt.task_execution_completed is True
        assert receipt.task_execution_passed is True
        assert receipt.post_execution_workspace_matched is True
        assert receipt.candidate_patch_bound is True
        assert receipt.candidate_patch_present is True
        assert receipt.scope_policy_passed is True
        assert receipt.required_tests_satisfied is True
        assert receipt.mechanical_evaluation_passed is True
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = (
            post_evaluation.PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.evaluation_authenticated is False

        _reject(
            lambda: post_evaluation.PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
                {**receipt.to_dict(), "local_commit_authorized": True}
            )
        )
        _reject(
            lambda: post_evaluation.PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
                {**receipt.to_dict(), "mechanical_evaluation_passed": False}
            )
        )
        _reject(
            lambda: post_evaluation.PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
                {**receipt.to_dict(), "candidate_patch_sha256": "a" * 64}
            )
        )
        _reject(
            lambda: post_evaluation.PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
                {**receipt.to_dict(), "changed_file_count": 2}
            )
        )
        _reject(
            lambda: post_evaluation.PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
                {**receipt.to_dict(), "production_activation_authorized": True}
            )
        )

        # Reloaded ADR-DC-039 evidence cannot recover live evaluation authority.
        reloaded_execution = (
            execution_transaction.PilotExactTaskExecutionTransactionReceipt.from_mapping(
                execution_receipt.to_dict()
            )
        )
        assert reloaded_execution.transaction_authenticated is False
        _reject(
            lambda: post_evaluation._evaluate_verified_pilot_exact_task_execution(
                execution_receipt=reloaded_execution,
                now_provider=lambda: "2026-09-15T05:01:01Z",
            )
        )

        # The immutable DevelopmentTask has max_deleted_lines=0. One deleted
        # line must therefore fail closed even though the Tier-A execution passed.
        _calls, deletion_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            numstat=b"1\t1\tVERSION\0",
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=deletion_reader
        ):
            _reject(
                lambda: post_evaluation._evaluate_verified_pilot_exact_task_execution(
                    execution_receipt=execution_receipt,
                    now_provider=lambda: "2026-09-15T05:01:02Z",
                )
            )

        # A path outside allowed_paths is equally non-evaluable for a favorable
        # result, regardless of successful command execution.
        _calls, outside_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            numstat=b"1\t0\tREADME.md\0",
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=outside_reader
        ):
            _reject(
                lambda: post_evaluation._evaluate_verified_pilot_exact_task_execution(
                    execution_receipt=execution_receipt,
                    now_provider=lambda: "2026-09-15T05:01:03Z",
                )
            )

        # Binary numstat has no trustworthy added/deleted line counts and must
        # fail closed instead of bypassing line budgets.
        _calls, binary_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            numstat=b"-\t-\tVERSION\0",
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=binary_reader
        ):
            _reject(
                lambda: post_evaluation._evaluate_verified_pilot_exact_task_execution(
                    execution_receipt=execution_receipt,
                    now_provider=lambda: "2026-09-15T05:01:04Z",
                )
            )

        # The candidate is snapshotted on both sides of numstat collection.
        # Any intervening workspace drift invalidates the mechanical evaluation.
        _calls, drift_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            numstat=numstat,
            drift_after_numstat=True,
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=drift_reader
        ):
            _reject(
                lambda: post_evaluation._evaluate_verified_pilot_exact_task_execution(
                    execution_receipt=execution_receipt,
                    now_provider=lambda: "2026-09-15T05:01:05Z",
                )
            )

        # A non-empty staged patch cannot be represented by empty or malformed
        # numstat evidence in a favorable receipt.
        for malformed in (b"", b"1\t0\tVERSION"):
            _calls, malformed_reader = _evaluation_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                numstat=malformed,
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=malformed_reader
            ):
                _reject(
                    lambda: post_evaluation._evaluate_verified_pilot_exact_task_execution(
                        execution_receipt=execution_receipt,
                        now_provider=lambda: "2026-09-15T05:01:06Z",
                    )
                )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["task_execution_passed"]["const"] is True
        assert props["scope_policy_passed"]["const"] is True
        assert props["mechanical_evaluation_passed"]["const"] is True
        assert props["local_commit_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            post_evaluation.evaluate_pilot_exact_task_execution
        ).parameters
        assert tuple(public_parameters) == ("execution_receipt",)

        source = inspect.getsource(post_evaluation)
        assert "PathPolicy(" in source
        assert '"--numstat"' in source
        assert "_GitWorkspaceEvidence(" in source
        assert "run_single_verified_tier_a_command_with_receipt(" not in source
        assert "run_verified_tier_a_command(" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
        assert '("commit",' not in source
        assert '("push",' not in source
    finally:
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
