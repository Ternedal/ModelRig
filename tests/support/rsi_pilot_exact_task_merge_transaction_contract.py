"""Adversarial contract for ADR-DC-060 exact one-shot merge transaction."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_merge_authorization as merge_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_merge_readiness_evaluation as readiness,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_merge_transaction as merge_tx,
)
from rsi_pilot_exact_task_merge_authorization_contract import (  # noqa: E402
    _authorize,
    _config,
    _dual_authority,
    _ledger as _authorization_ledger,
    _live_ready_evaluation,
    _payload,
)
from rsi_pilot_exact_task_merge_readiness_evaluation_contract import _evaluate  # noqa: E402
from rsi_pilot_exact_task_pr_lifecycle_recovery_contract import _cleanup_bundle  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-merge-transaction-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-060 unexpectedly accepted unsafe merge transaction")


def _transaction_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, merge_tx._PilotExactTaskMergeTransactionLedger(root)


def _live_merge_authorization():
    (
        bundle,
        tx_temp,
        recovery_temp,
        _tx_ledger,
        source,
        ready_review,
        policy,
        evaluation,
    ) = _live_ready_evaluation()
    auth_temp, auth_ledger = _authorization_ledger(
        "rsi-exact-task-merge-tx-source-auth-"
    )
    config = _config(evaluation)
    payload = _payload(evaluation, config)
    verifier, op_sig, review_sig = _dual_authority(payload)
    authorization = _authorize(
        evaluation,
        config,
        payload,
        verifier,
        op_sig,
        review_sig,
        auth_ledger,
    )
    assert authorization.authorization_authenticated is True
    return (
        bundle,
        tx_temp,
        recovery_temp,
        auth_temp,
        source,
        ready_review,
        policy,
        evaluation,
        authorization,
    )


class _Transport:
    def __init__(self, authorization):
        self.authorization = authorization
        self.credential_id = "test-publisher-v1"
        self.credential_config_sha256 = "a" * 64
        self.credential_path_sha256 = "b" * 64
        self.calls: list[str] = []
        self.pre_script = []
        self.post_script = []
        self.fail_merge = False
        self.merge_sha = "c" * 40
        if self.merge_sha in {authorization.base_sha, authorization.head_sha}:
            self.merge_sha = "d" * 40

    def validate_for(self, authorization):
        self.calls.append("validate")
        assert authorization is self.authorization

    def _pre(self, *, base_sha=None, head_sha=None, mergeable=True):
        return merge_tx._PreMergeRemoteState(
            repository=self.authorization.repository,
            repository_id=self.authorization.repository_id,
            base_branch=self.authorization.base_branch,
            base_sha=self.authorization.base_sha if base_sha is None else base_sha,
            head_branch=self.authorization.head_branch,
            head_sha=self.authorization.head_sha if head_sha is None else head_sha,
            pull_request_number=self.authorization.pull_request_number,
            pull_request_api_url=self.authorization.pull_request_api_url,
            pull_request_node_id_sha256=self.authorization.pull_request_node_id_sha256,
            state="open",
            draft=False,
            merged=False,
            maintainer_can_modify=False,
            mergeable=mergeable,
            mergeable_state="clean" if mergeable else "blocked",
        )

    def observe_pre(self, authorization):
        self.calls.append("observe-pre")
        assert authorization is self.authorization
        if self.pre_script:
            return self.pre_script.pop(0)
        return self._pre()

    def merge(self, authorization):
        self.calls.append("merge")
        assert authorization is self.authorization
        if self.fail_merge:
            raise merge_tx.PilotExactTaskMergeTransactionError("scripted merge failure")
        response = {
            "sha": self.merge_sha,
            "merged": True,
            "message": "Pull Request successfully merged",
        }
        return (
            self.merge_sha,
            __import__("hashlib").sha256(
                merge_tx._canonical(response).encode("utf-8")
            ).hexdigest(),
        )

    def _post(self, *, parent_sha=None, base_ref_sha=None):
        return merge_tx._PostMergeRemoteState(
            repository=self.authorization.repository,
            repository_id=self.authorization.repository_id,
            base_branch=self.authorization.base_branch,
            base_ref_sha=self.merge_sha if base_ref_sha is None else base_ref_sha,
            head_branch=self.authorization.head_branch,
            head_sha=self.authorization.head_sha,
            pull_request_number=self.authorization.pull_request_number,
            pull_request_api_url=self.authorization.pull_request_api_url,
            pull_request_node_id_sha256=self.authorization.pull_request_node_id_sha256,
            state="closed",
            draft=False,
            merged=True,
            merge_commit_sha=self.merge_sha,
            merge_commit_parent_sha=(
                self.authorization.base_sha if parent_sha is None else parent_sha
            ),
            maintainer_can_modify=False,
        )

    def observe_post(self, authorization, merge_commit_sha):
        self.calls.append("observe-post")
        assert authorization is self.authorization
        assert merge_commit_sha == self.merge_sha
        if self.post_script:
            return self.post_script.pop(0)
        return self._post()


def _fresh_sequence(ready_review, policy, *times):
    values = [_evaluate(ready_review, policy, now=value) for value in times]
    assert all(item.evaluation_authenticated for item in values)
    iterator = iter(values)
    return lambda _authorization: next(iterator)


def _run(
    authorization,
    transport,
    ledger,
    fresh_revalidator,
    *,
    times=(
        "2026-09-15T09:34:40Z",
        "2026-09-15T09:34:50Z",
        "2026-09-15T09:34:51Z",
        "2026-09-15T09:34:52Z",
    ),
):
    clock = iter(times)
    return merge_tx._execute_verified_pilot_exact_task_merge(
        merge_authorization=authorization,
        transaction_ledger=ledger,
        transport=transport,
        fresh_revalidator=fresh_revalidator,
        now_provider=lambda: next(clock),
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        bundle,
        tx_temp,
        recovery_temp,
        auth_temp,
        _source,
        ready_review,
        policy,
        evaluation,
        authorization,
    ) = _live_merge_authorization()
    transaction_temp, ledger = _transaction_ledger("rsi-exact-task-merge-transaction-")
    try:
        transport = _Transport(authorization)
        fresh = _fresh_sequence(
            ready_review,
            policy,
            "2026-09-15T09:34:35Z",
            "2026-09-15T09:34:45Z",
        )
        receipt = _run(authorization, transport, ledger, fresh)

        assert transport.calls == [
            "validate",
            "observe-pre",
            "observe-pre",
            "observe-pre",
            "merge",
            "observe-post",
            "observe-post",
        ]
        assert receipt.transaction_authenticated is True
        assert receipt.transaction_key_sha256 == authorization.execution_nonce_sha256
        assert receipt.merge_authorization_sha256 == authorization.sha256
        assert receipt.merge_readiness_evaluation_sha256 == authorization.merge_readiness_evaluation_sha256
        assert receipt.merge_readiness_policy_sha256 == authorization.merge_readiness_policy_sha256
        assert receipt.merge_config_sha256 == authorization.merge_config_sha256
        assert receipt.repository == authorization.repository
        assert receipt.repository_id == authorization.repository_id
        assert receipt.base_branch == authorization.base_branch
        assert receipt.authorized_base_sha == authorization.base_sha
        assert receipt.head_branch == authorization.head_branch
        assert receipt.head_sha == authorization.head_sha
        assert receipt.pull_request_number == authorization.pull_request_number
        assert receipt.merge_method == "squash"
        assert receipt.publisher_credential_id == "test-publisher-v1"
        assert receipt.merge_commit_sha == transport.merge_sha
        assert receipt.transaction_lock_committed is True
        assert receipt.merge_authorization_authenticated is True
        assert receipt.pre_lock_merge_readiness_revalidated is True
        assert receipt.pre_merge_remote_state_double_observed is True
        assert receipt.post_lock_merge_readiness_revalidated is True
        assert receipt.exact_sha_pinned_squash_merge_executed is True
        assert receipt.merge_response_verified is True
        assert receipt.post_merge_remote_state_double_observed is True
        assert receipt.exact_base_parent_verified is True
        assert receipt.merged is True
        assert receipt.merge_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = merge_tx.PilotExactTaskMergeTransactionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.transaction_authenticated is False

        _reject(
            lambda: _run(
                authorization,
                _Transport(authorization),
                ledger,
                _fresh_sequence(
                    ready_review,
                    policy,
                    "2026-09-15T09:34:35Z",
                    "2026-09-15T09:34:45Z",
                ),
            )
        )

        reloaded_auth = merge_auth.PilotExactTaskMergeAuthorizationReceipt.from_mapping(
            authorization.to_dict()
        )
        assert reloaded_auth.authorization_authenticated is False
        fresh_temp, fresh_ledger = _transaction_ledger("rsi-exact-task-merge-tx-reloaded-")
        try:
            _reject(
                lambda: _run(
                    reloaded_auth,
                    _Transport(reloaded_auth),
                    fresh_ledger,
                    lambda _value: evaluation,
                )
            )
        finally:
            fresh_temp.cleanup()

        drift_temp, drift_ledger = _transaction_ledger("rsi-exact-task-merge-tx-fresh-drift-")
        try:
            first = _evaluate(ready_review, policy, now="2026-09-15T09:34:35Z")
            stale = readiness.PilotExactTaskMergeReadinessEvaluationReceipt.from_mapping(
                _evaluate(ready_review, policy, now="2026-09-15T09:34:45Z").to_dict()
            )
            sequence = iter((first, stale))
            drift_transport = _Transport(authorization)
            _reject(
                lambda: _run(
                    authorization,
                    drift_transport,
                    drift_ledger,
                    lambda _value: next(sequence),
                )
            )
            final, lock, merged = drift_ledger._paths(authorization.execution_nonce_sha256)
            assert lock.exists()
            assert not merged.exists()
            assert not final.exists()
            assert "merge" not in drift_transport.calls
        finally:
            drift_temp.cleanup()

        remote_temp, remote_ledger = _transaction_ledger("rsi-exact-task-merge-tx-remote-drift-")
        try:
            remote_transport = _Transport(authorization)
            remote_transport.pre_script = [
                remote_transport._pre(),
                remote_transport._pre(),
                remote_transport._pre(head_sha="e" * 40),
            ]
            _reject(
                lambda: _run(
                    authorization,
                    remote_transport,
                    remote_ledger,
                    _fresh_sequence(
                        ready_review,
                        policy,
                        "2026-09-15T09:34:35Z",
                        "2026-09-15T09:34:45Z",
                    ),
                )
            )
            final, lock, merged = remote_ledger._paths(authorization.execution_nonce_sha256)
            assert lock.exists()
            assert not merged.exists()
            assert not final.exists()
            assert "merge" not in remote_transport.calls
        finally:
            remote_temp.cleanup()

        failure_temp, failure_ledger = _transaction_ledger("rsi-exact-task-merge-tx-endpoint-failure-")
        try:
            failure_transport = _Transport(authorization)
            failure_transport.fail_merge = True
            _reject(
                lambda: _run(
                    authorization,
                    failure_transport,
                    failure_ledger,
                    _fresh_sequence(
                        ready_review,
                        policy,
                        "2026-09-15T09:34:35Z",
                        "2026-09-15T09:34:45Z",
                    ),
                )
            )
            final, lock, merged = failure_ledger._paths(authorization.execution_nonce_sha256)
            assert lock.exists()
            assert not merged.exists()
            assert not final.exists()
        finally:
            failure_temp.cleanup()

        post_temp, post_ledger = _transaction_ledger("rsi-exact-task-merge-tx-post-drift-")
        try:
            post_transport = _Transport(authorization)
            post_transport.post_script = [
                post_transport._post(),
                post_transport._post(parent_sha="f" * 40),
            ]
            _reject(
                lambda: _run(
                    authorization,
                    post_transport,
                    post_ledger,
                    _fresh_sequence(
                        ready_review,
                        policy,
                        "2026-09-15T09:34:35Z",
                        "2026-09-15T09:34:45Z",
                    ),
                )
            )
            final, lock, merged = post_ledger._paths(authorization.execution_nonce_sha256)
            assert lock.exists()
            assert merged.exists()
            assert not final.exists()
        finally:
            post_temp.cleanup()

        expiry_temp, expiry_ledger = _transaction_ledger("rsi-exact-task-merge-tx-expiry-")
        try:
            expiry_transport = _Transport(authorization)
            _reject(
                lambda: _run(
                    authorization,
                    expiry_transport,
                    expiry_ledger,
                    _fresh_sequence(
                        ready_review,
                        policy,
                        "2026-09-15T09:34:35Z",
                        "2026-09-15T09:34:45Z",
                    ),
                    times=("2026-09-15T09:34:40Z", "2026-09-15T09:39:10Z"),
                )
            )
            final, lock, merged = expiry_ledger._paths(authorization.execution_nonce_sha256)
            assert lock.exists()
            assert not merged.exists()
            assert not final.exists()
            assert "merge" not in expiry_transport.calls
        finally:
            expiry_temp.cleanup()

        for field, value in (
            ("transaction_lock_committed", False),
            ("merge_authorization_authenticated", False),
            ("pre_lock_merge_readiness_revalidated", False),
            ("pre_merge_remote_state_double_observed", False),
            ("post_lock_merge_readiness_revalidated", False),
            ("exact_sha_pinned_squash_merge_executed", False),
            ("merge_response_verified", False),
            ("post_merge_remote_state_double_observed", False),
            ("exact_base_parent_verified", False),
            ("merged", False),
            ("merge_authorized", True),
            ("remote_write_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    merge_tx.PilotExactTaskMergeTransactionReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(merge_tx.PilotExactTaskMergeTransactionReceipt.__dataclass_fields__)
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["merged"]["const"] is True
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["release_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert schema["properties"]["nonce_reusable"]["const"] is False

        public = inspect.signature(merge_tx.execute_pilot_exact_task_merge).parameters
        assert tuple(public) == ("merge_authorization",)
        source_text = inspect.getsource(merge_tx)
        assert '"merge_method": "squash"' in source_text
        assert '"sha": authorization.head_sha' in source_text
        assert "enable_auto_merge" not in source_text
        assert "release_authorized: bool = False" in source_text
        assert "deploy_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
        assert "Ed25519PrivateKey" not in source_text
    finally:
        transaction_temp.cleanup()
        auth_temp.cleanup()
        recovery_temp.cleanup()
        tx_temp.cleanup()
        _cleanup_bundle(bundle)


if __name__ == "__main__":
    run_contract()
