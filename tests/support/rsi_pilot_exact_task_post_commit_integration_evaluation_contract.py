"""Adversarial contract for ADR-DC-045 post-commit integration evaluation."""
from __future__ import annotations

import inspect
import json
import os
import sys
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
    improvement_pilot_exact_task_local_commit_object_identity as object_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_transaction as transaction,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_commit_integration_evaluation as integration_eval,
)
from rsi_pilot_exact_task_local_commit_transaction_contract import (  # noqa: E402
    _live_authorization,
    _transaction_ledger,
    _transaction_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-post-commit-integration-evaluation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-045 unexpectedly accepted invalid integration evidence")


def _live_transaction():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        authorization,
        task,
        fixture,
        staged,
        index_payload,
    ) = _live_authorization()
    transaction_temp, ledger = _transaction_ledger(
        "rsi-exact-task-local-commit-045-source-"
    )
    payload = object_identity._commit_payload(
        tree_sha=identity.root_tree_sha,
        parent_sha=identity.base_sha,
        subject=identity.commit_subject,
        epoch_seconds=identity.commit_epoch_seconds,
    )
    calls, reader, state = _transaction_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
        root_tree_sha=identity.root_tree_sha,
        predicted_commit_sha=identity.predicted_commit_sha,
        commit_payload=payload,
    )
    times = iter(
        (
            "2026-09-15T06:40:00Z",
            "2026-09-15T06:40:01Z",
            "2026-09-15T06:40:02Z",
        )
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        receipt = transaction._execute_verified_pilot_exact_task_local_commit(
            local_commit_write_authorization=authorization,
            ledger=ledger,
            now_provider=lambda: next(times),
        )
    assert calls
    assert state()["current_head"] == identity.predicted_commit_sha
    assert receipt.transaction_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        authorization,
        receipt,
        task,
        fixture,
        index_payload,
        payload,
    )


def _evaluation_reader(
    *,
    workspace: Path,
    local_ref: str,
    base_sha: str,
    predicted_commit_sha: str,
    root_tree_sha: str,
    commit_payload: bytes,
    index_payload: bytes,
    drift_between_observations: bool = False,
    wrong_parent: bool = False,
    wrong_tree: bool = False,
    wrong_payload: bool = False,
    dirty_index: bool = False,
    dirty_worktree: bool = False,
    untracked: bool = False,
):
    calls: list[tuple[str, ...]] = []
    observation = 0

    def run(args, *, cwd, **_kwargs):
        nonlocal observation
        args = tuple(args)
        calls.append(args)
        assert Path(cwd) == workspace
        if args == ("symbolic-ref", "-q", "HEAD"):
            observation += 1
            return (local_ref + "\n").encode("ascii")
        current = predicted_commit_sha
        if drift_between_observations and observation >= 2:
            current = "f" * 40
        if args == ("rev-parse", "--verify", "HEAD"):
            return (current + "\n").encode("ascii")
        if args == ("rev-parse", "--verify", local_ref):
            return (current + "\n").encode("ascii")
        if args == ("rev-parse", "--verify", f"{predicted_commit_sha}^"):
            value = "e" * 40 if wrong_parent else base_sha
            return (value + "\n").encode("ascii")
        if args == ("rev-parse", "--verify", f"{predicted_commit_sha}^{{tree}}"):
            value = "d" * 40 if wrong_tree else root_tree_sha
            return (value + "\n").encode("ascii")
        if args == ("rev-parse", "--show-object-format"):
            return b"sha1\n"
        if args == ("cat-file", "-t", predicted_commit_sha):
            return b"commit\n"
        if args == ("cat-file", "commit", predicted_commit_sha):
            return b"wrong payload\n" if wrong_payload else commit_payload
        if args == ("ls-files", "--stage", "-z", "--"):
            return index_payload
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
            return b"dirty-index" if dirty_index else b""
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
            return b"dirty-worktree" if dirty_worktree else b""
        if args == ("ls-files", "--others", "--exclude-standard", "-z"):
            return b"untracked.txt\0" if untracked else b""
        raise AssertionError(f"ADR-DC-045 attempted unexpected Git command: {args!r}")

    return calls, run


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        auth_temp,
        transaction_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        authorization,
        local_transaction,
        task,
        fixture,
        index_payload,
        payload,
    ) = _live_transaction()
    try:
        calls, reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=payload,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = integration_eval._evaluate_verified_pilot_exact_task_post_commit_integration(
                local_commit_transaction=local_transaction,
                now_provider=lambda: "2026-09-15T06:40:10Z",
            )

        assert len(calls) == 24
        assert receipt.evaluation_authenticated is True
        assert receipt.local_commit_transaction_sha256 == local_transaction.sha256
        assert receipt.local_commit_write_authorization_sha256 == authorization.sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.post_execution_evaluation_sha256 == evaluation.sha256
        assert receipt.execution_nonce_sha256 == identity.execution_nonce_sha256
        assert receipt.development_task_sha256 == identity.development_task_sha256
        assert receipt.task_id == task.task_id
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.local_head_ref == local_transaction.local_head_ref
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.committed_at_utc == local_transaction.committed_at_utc
        assert receipt.local_commit_transaction_authenticated is True
        assert receipt.local_commit_created is True
        assert receipt.local_head_ref_verified is True
        assert receipt.commit_object_verified is True
        assert receipt.commit_payload_verified is True
        assert receipt.parent_base_verified is True
        assert receipt.root_tree_verified is True
        assert receipt.index_manifest_preserved is True
        assert receipt.index_clean is True
        assert receipt.worktree_clean is True
        assert receipt.double_observation_matched is True
        assert receipt.mechanical_integration_evaluation_passed is True
        assert receipt.integration_candidate_verified is True
        assert receipt.semantic_acceptance_criteria_evaluated is False
        assert receipt.integration_ready is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = integration_eval.PilotExactTaskPostCommitIntegrationEvaluationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.evaluation_authenticated is False

        for field, value in (
            ("integration_candidate_verified", False),
            ("semantic_acceptance_criteria_evaluated", True),
            ("integration_ready", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    integration_eval.PilotExactTaskPostCommitIntegrationEvaluationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        reloaded_transaction = transaction.PilotExactTaskLocalCommitTransactionReceipt.from_mapping(
            local_transaction.to_dict()
        )
        assert reloaded_transaction.transaction_authenticated is False
        _reject(
            lambda: integration_eval._evaluate_verified_pilot_exact_task_post_commit_integration(
                local_commit_transaction=reloaded_transaction,
                now_provider=lambda: "2026-09-15T06:40:11Z",
            )
        )

        for kwargs in (
            {"drift_between_observations": True},
            {"wrong_parent": True},
            {"wrong_tree": True},
            {"wrong_payload": True},
            {"dirty_index": True},
            {"dirty_worktree": True},
            {"untracked": True},
        ):
            bad_calls, bad_reader = _evaluation_reader(
                workspace=fixture["workspace"],
                local_ref=local_transaction.local_head_ref,
                base_sha=identity.base_sha,
                predicted_commit_sha=identity.predicted_commit_sha,
                root_tree_sha=identity.root_tree_sha,
                commit_payload=payload,
                index_payload=index_payload,
                **kwargs,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=bad_reader):
                _reject(
                    lambda: integration_eval._evaluate_verified_pilot_exact_task_post_commit_integration(
                        local_commit_transaction=local_transaction,
                        now_provider=lambda: "2026-09-15T06:40:12Z",
                    )
                )
            assert bad_calls

        rollback_calls, rollback_reader = _evaluation_reader(
            workspace=fixture["workspace"],
            local_ref=local_transaction.local_head_ref,
            base_sha=identity.base_sha,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
            commit_payload=payload,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=rollback_reader):
            _reject(
                lambda: integration_eval._evaluate_verified_pilot_exact_task_post_commit_integration(
                    local_commit_transaction=local_transaction,
                    now_provider=lambda: "2026-09-15T06:39:59Z",
                )
            )
        assert rollback_calls

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["integration_candidate_verified"]["const"] is True
        assert props["semantic_acceptance_criteria_evaluated"]["const"] is False
        assert props["integration_ready"]["const"] is False
        assert props["remote_write_authorized"]["const"] is False
        assert props["push_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            integration_eval.evaluate_pilot_exact_task_post_commit_integration
        ).parameters
        assert tuple(public_parameters) == ("local_commit_transaction",)

        source = inspect.getsource(integration_eval)
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("write-tree",' not in source
        assert '("hash-object",' not in source
        assert '("update-ref",' not in source
        # Read-only commit identity hashing is allowed; Git commit execution is not.
        assert '.run(("commit",' not in source
        assert '("push",' not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
    finally:
        transaction_temp.cleanup()
        auth_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
