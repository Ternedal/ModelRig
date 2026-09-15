"""Adversarial contract for ADR-DC-044 exact one-shot local commit transaction."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_object_identity as object_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_transaction as transaction,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_authorization as write_auth,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
)
from rsi_pilot_exact_task_local_commit_write_authorization_contract import (  # noqa: E402
    _live_identity,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-transaction-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-044 unexpectedly accepted invalid commit transaction")


def _transaction_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, transaction._PilotExactTaskLocalCommitTransactionLedger(root)


def _authorization_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, write_auth._PilotExactTaskLocalCommitWriteAuthorizationLedger(root)


def _live_authorization():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        task,
        fixture,
        staged,
        index_payload,
    ) = _live_identity()
    auth_temp, auth_ledger = _authorization_ledger("rsi-exact-task-local-write-auth-044-")
    calls, reader = _identity_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    times = iter(("2026-09-15T06:10:00Z", "2026-09-15T06:10:01Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        authorization = write_auth._authorize_verified_pilot_exact_task_local_commit_write(
            local_commit_object_identity=identity,
            ledger=auth_ledger,
            now_provider=lambda: next(times),
        )
    assert calls
    assert authorization.authorization_authenticated is True
    return (
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
    )


def _transaction_reader(
    *,
    workspace: Path,
    base_sha: str,
    staged: bytes,
    index_payload: bytes,
    root_tree_sha: str,
    predicted_commit_sha: str,
    commit_payload: bytes,
    local_ref: str = "refs/heads/rsi-pilot-test",
    drift_after_marker: bool = False,
    wrong_tree: bool = False,
    fail_update_ref: bool = False,
):
    calls: list[tuple[str, ...]] = []
    current_head = base_sha
    snapshot_number = 0
    update_ref_count = 0

    def run(args, *, cwd, stdin=None, **_kwargs):
        nonlocal current_head, snapshot_number, update_ref_count
        args = tuple(args)
        calls.append(args)
        assert Path(cwd) == workspace

        if args == ("rev-parse", "--show-toplevel"):
            snapshot_number += 1
            return (os.fspath(workspace) + "\n").encode("utf-8")
        if args == ("rev-parse", "HEAD"):
            if drift_after_marker and snapshot_number >= 2:
                return ("f" * 40 + "\n").encode("ascii")
            return (current_head + "\n").encode("ascii")
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
            return staged if current_head == base_sha else b""
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
        if args == ("rev-parse", "--show-object-format"):
            return b"sha1\n"
        if args == ("ls-files", "--stage", "-z", "--"):
            return index_payload
        if args == ("symbolic-ref", "-q", "HEAD"):
            return (local_ref + "\n").encode("ascii")
        if args == ("rev-parse", "--verify", local_ref):
            return (current_head + "\n").encode("ascii")
        if args == ("rev-parse", "--verify", "HEAD"):
            return (current_head + "\n").encode("ascii")
        if args == ("write-tree",):
            tree = "e" * 40 if wrong_tree else root_tree_sha
            return (tree + "\n").encode("ascii")
        if args == ("hash-object", "-t", "commit", "-w", "--stdin"):
            assert stdin == commit_payload
            return (predicted_commit_sha + "\n").encode("ascii")
        if args == ("cat-file", "-t", predicted_commit_sha):
            return b"commit\n"
        if args == ("cat-file", "commit", predicted_commit_sha):
            return commit_payload
        if args == ("update-ref", local_ref, predicted_commit_sha, base_sha):
            update_ref_count += 1
            if fail_update_ref:
                raise ValueError("simulated compare-and-swap failure")
            assert current_head == base_sha
            current_head = predicted_commit_sha
            return b""
        raise AssertionError(f"ADR-DC-044 attempted unexpected Git command: {args!r}")

    def state():
        return {
            "current_head": current_head,
            "snapshot_number": snapshot_number,
            "update_ref_count": update_ref_count,
        }

    return calls, run, state


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
    transaction_temp, ledger = _transaction_ledger("rsi-exact-task-local-commit-044-")
    try:
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
                "2026-09-15T06:10:10Z",
                "2026-09-15T06:10:11Z",
                "2026-09-15T06:10:12Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = transaction._execute_verified_pilot_exact_task_local_commit(
                local_commit_write_authorization=authorization,
                ledger=ledger,
                now_provider=lambda: next(times),
            )

        assert state()["current_head"] == identity.predicted_commit_sha
        assert state()["update_ref_count"] == 1
        assert calls.count(("write-tree",)) == 1
        assert calls.count(("hash-object", "-t", "commit", "-w", "--stdin")) == 1
        assert calls.count(
            ("update-ref", "refs/heads/rsi-pilot-test", identity.predicted_commit_sha, task.base_sha)
        ) == 1
        assert receipt.transaction_authenticated is True
        assert receipt.transaction_key_sha256 == identity.execution_nonce_sha256
        assert receipt.local_commit_write_authorization_sha256 == authorization.sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.local_commit_plan_sha256 == local_plan.sha256
        assert receipt.execution_nonce_sha256 == execution_receipt.execution_nonce_sha256
        assert receipt.development_task_sha256 == identity.development_task_sha256
        assert receipt.task_id == task.task_id
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.local_head_ref == "refs/heads/rsi-pilot-test"
        assert receipt.candidate_patch_sha256 == identity.candidate_patch_sha256
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.host_replay_guard_committed is True
        assert receipt.local_commit_write_authorization_authenticated is True
        assert receipt.local_commit_write_authority_consumed is True
        assert receipt.prewrite_workspace_revalidated is True
        assert receipt.local_head_ref_bound is True
        assert receipt.write_tree_sha_matched is True
        assert receipt.commit_object_sha_matched is True
        assert receipt.commit_object_payload_matched is True
        assert receipt.local_ref_compare_and_swap_succeeded is True
        assert receipt.post_commit_head_verified is True
        assert receipt.post_commit_index_clean is True
        assert receipt.post_commit_worktree_clean is True
        assert receipt.local_commit_created is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = transaction.PilotExactTaskLocalCommitTransactionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.transaction_authenticated is False

        for field, value in (
            ("transaction_key_sha256", "a" * 64),
            ("local_commit_created", False),
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("push_authorized", True),
            ("merge_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    transaction.PilotExactTaskLocalCommitTransactionReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        # The durable transaction marker and final receipt permanently consume
        # this execution nonce independently of the now-moved Git ref.
        final, pending, lock = ledger._paths(identity.execution_nonce_sha256)
        assert final.exists()
        assert lock.exists()
        assert not pending.exists()
        _reject(
            lambda: ledger.acquire(
                authorization=authorization,
                identity=identity,
                local_head_ref="refs/heads/rsi-pilot-test",
            )
        )

        # Reloaded ADR-DC-043 evidence is audit-only and cannot start mutation.
        reloaded_authorization = (
            write_auth.PilotExactTaskLocalCommitWriteAuthorizationReceipt.from_mapping(
                authorization.to_dict()
            )
        )
        assert reloaded_authorization.authorization_authenticated is False
        fresh_temp, fresh_ledger = _transaction_ledger("rsi-exact-task-local-reload-044-")
        try:
            _reject(
                lambda: transaction._execute_verified_pilot_exact_task_local_commit(
                    local_commit_write_authorization=reloaded_authorization,
                    ledger=fresh_ledger,
                    now_provider=lambda: "2026-09-15T06:10:20Z",
                )
            )
        finally:
            fresh_temp.cleanup()

        # Drift after the durable consumption marker burns the transaction
        # before write-tree; the lock survives and no local ref mutation occurs.
        drift_temp, drift_ledger = _transaction_ledger("rsi-exact-task-local-drift-044-")
        try:
            drift_calls, drift_reader, drift_state = _transaction_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
                root_tree_sha=identity.root_tree_sha,
                predicted_commit_sha=identity.predicted_commit_sha,
                commit_payload=payload,
                drift_after_marker=True,
            )
            drift_times = iter(("2026-09-15T06:10:30Z", "2026-09-15T06:10:31Z"))
            with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
                _reject(
                    lambda: transaction._execute_verified_pilot_exact_task_local_commit(
                        local_commit_write_authorization=authorization,
                        ledger=drift_ledger,
                        now_provider=lambda: next(drift_times),
                    )
                )
            _final, _pending, drift_lock = drift_ledger._paths(
                identity.execution_nonce_sha256
            )
            assert drift_lock.exists()
            assert ("write-tree",) not in drift_calls
            assert drift_state()["update_ref_count"] == 0
        finally:
            drift_temp.cleanup()

        # A mismatching write-tree identity burns the transaction and never
        # reaches commit-object or ref mutation.
        tree_temp, tree_ledger = _transaction_ledger("rsi-exact-task-local-tree-044-")
        try:
            tree_calls, tree_reader, tree_state = _transaction_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
                root_tree_sha=identity.root_tree_sha,
                predicted_commit_sha=identity.predicted_commit_sha,
                commit_payload=payload,
                wrong_tree=True,
            )
            tree_times = iter(("2026-09-15T06:10:40Z", "2026-09-15T06:10:41Z"))
            with patch.object(fixture["git_runner"], "run", side_effect=tree_reader):
                _reject(
                    lambda: transaction._execute_verified_pilot_exact_task_local_commit(
                        local_commit_write_authorization=authorization,
                        ledger=tree_ledger,
                        now_provider=lambda: next(tree_times),
                    )
                )
            _final, _pending, tree_lock = tree_ledger._paths(identity.execution_nonce_sha256)
            assert tree_lock.exists()
            assert ("hash-object", "-t", "commit", "-w", "--stdin") not in tree_calls
            assert tree_state()["update_ref_count"] == 0
        finally:
            tree_temp.cleanup()

        # Ref movement is compare-and-swap. A raced/mismatching old ref leaves
        # the transaction consumed but never produces a successful receipt.
        cas_temp, cas_ledger = _transaction_ledger("rsi-exact-task-local-cas-044-")
        try:
            cas_calls, cas_reader, cas_state = _transaction_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
                root_tree_sha=identity.root_tree_sha,
                predicted_commit_sha=identity.predicted_commit_sha,
                commit_payload=payload,
                fail_update_ref=True,
            )
            cas_times = iter(("2026-09-15T06:10:50Z", "2026-09-15T06:10:51Z"))
            with patch.object(fixture["git_runner"], "run", side_effect=cas_reader):
                _reject(
                    lambda: transaction._execute_verified_pilot_exact_task_local_commit(
                        local_commit_write_authorization=authorization,
                        ledger=cas_ledger,
                        now_provider=lambda: next(cas_times),
                    )
                )
            _final, _pending, cas_lock = cas_ledger._paths(identity.execution_nonce_sha256)
            assert cas_lock.exists()
            assert cas_state()["current_head"] == task.base_sha
            assert cas_state()["update_ref_count"] == 1
            assert ("update-ref", "refs/heads/rsi-pilot-test", identity.predicted_commit_sha, task.base_sha) in cas_calls
        finally:
            cas_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["local_commit_created"]["const"] is True
        assert props["git_object_write_authorized"]["const"] is False
        assert props["local_ref_update_authorized"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["remote_write_authorized"]["const"] is False
        assert props["push_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            transaction.execute_pilot_exact_task_local_commit
        ).parameters
        assert tuple(public_parameters) == ("local_commit_write_authorization",)

        source = inspect.getsource(transaction)
        assert '("write-tree",)' in source
        assert '("hash-object", "-t", "commit", "-w", "--stdin")' in source
        assert '("update-ref", ref, identity.predicted_commit_sha, identity.base_sha)' in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '"commit-tree"' not in source
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
