"""Adversarial contract for ADR-DC-050 exact remote publication transaction."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import weakref
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
    improvement_pilot_exact_task_remote_publication_authorization as publication_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_transaction as transaction,
)
from rsi_pilot_exact_task_post_commit_integration_evaluation_contract import (  # noqa: E402
    _evaluation_reader,
)
from rsi_pilot_exact_task_remote_publication_authorization_contract import (  # noqa: E402
    _ledger as _authorization_ledger,
    _live_observation,
)
from rsi_pilot_exact_task_remote_state_observation_contract import (  # noqa: E402
    _Observer,
)

_LIVE_AUTHORIZATION_KEEPALIVES = {}


def _retain_observation(authorization, observation) -> None:
    key = id(authorization)

    def cleanup(_):
        _LIVE_AUTHORIZATION_KEEPALIVES.pop(key, None)

    _LIVE_AUTHORIZATION_KEEPALIVES[key] = (
        weakref.ref(authorization, cleanup),
        observation,
    )


SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-transaction-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-050 unexpectedly accepted unsafe remote transaction")


def _transaction_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, transaction._PilotExactTaskRemotePublicationTransactionLedger(root)


class _Transport:
    credential_id = "test-publisher-v1"
    credential_config_sha256 = "a" * 64
    credential_path_sha256 = "b" * 64

    def __init__(self, *, fail_push=False, fail_pr=False):
        self.fail_push = fail_push
        self.fail_pr = fail_pr
        self.calls = []

    def validate_for(self, plan):
        self.calls.append(("validate", plan.sha256))

    def push_exact_commit(
        self,
        *,
        plan,
        git_runner,
        workspace_root,
        ledger_root,
        transaction_key,
    ):
        self.calls.append(
            (
                "push",
                plan.predicted_commit_sha,
                plan.head_branch,
                transaction_key,
            )
        )
        if self.fail_push:
            raise ValueError("synthetic push failure")
        assert git_runner is not None
        assert Path(workspace_root).is_absolute()
        assert Path(ledger_root).is_absolute()
        return "c" * 64

    def observe_after_push(self, plan):
        self.calls.append(("post-push", plan.predicted_commit_sha))
        return {
            "base_sha": plan.base_sha,
            "head_sha": plan.predicted_commit_sha,
            "matching_pr_count": 0,
        }

    def create_draft_pr(self, plan):
        self.calls.append(("create-pr", plan.pr_intent_sha256))
        if self.fail_pr:
            raise ValueError("synthetic PR failure")
        number = 4242
        return {
            "number": number,
            "api_url": (
                f"https://api.github.com/repos/{plan.repository}/pulls/{number}"
            ),
        }

    def verify_draft_pr(self, plan, number):
        self.calls.append(("verify-pr", number))
        return {
            "number": number,
            "api_url": (
                f"https://api.github.com/repos/{plan.repository}/pulls/{number}"
            ),
        }


def _live_authorization():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_auth_temp,
        local_transaction_temp,
        identity,
        local_transaction,
        mechanical,
        ready,
        task,
        fixture,
        index_payload,
        commit_payload,
        plan,
        observation,
        good,
    ) = _live_observation()
    auth_temp, auth_ledger = _authorization_ledger(
        "rsi-exact-task-remote-publication-transaction-auth-"
    )
    observer = _Observer((good, dict(good), dict(good), dict(good)))
    calls, reader = _evaluation_reader(
        workspace=fixture["workspace"],
        local_ref=local_transaction.local_head_ref,
        base_sha=identity.base_sha,
        predicted_commit_sha=identity.predicted_commit_sha,
        root_tree_sha=identity.root_tree_sha,
        commit_payload=commit_payload,
        index_payload=index_payload,
    )
    times = iter(("2026-09-15T06:41:30Z", "2026-09-15T06:41:31Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        authorization = (
            publication_auth._authorize_verified_pilot_exact_task_remote_publication(
                remote_state_observation=observation,
                ledger=auth_ledger,
                observer=observer,
                now_provider=lambda: next(times),
            )
        )
    assert calls
    assert authorization.authorization_authenticated is True
    # ADR-DC-049 authenticates through a weak reference to ADR-DC-048.
    # Keep the complete upstream live chain reachable while authorization lives.
    _retain_observation(authorization, observation)
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_auth_temp,
        local_transaction_temp,
        auth_temp,
        identity,
        local_transaction,
        mechanical,
        ready,
        task,
        fixture,
        index_payload,
        commit_payload,
        plan,
        observation,
        authorization,
        good,
    )


def _reader(fixture, local_transaction, identity, commit_payload, index_payload):
    return _evaluation_reader(
        workspace=fixture["workspace"],
        local_ref=local_transaction.local_head_ref,
        base_sha=identity.base_sha,
        predicted_commit_sha=identity.predicted_commit_sha,
        root_tree_sha=identity.root_tree_sha,
        commit_payload=commit_payload,
        index_payload=index_payload,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_auth_temp,
        local_transaction_temp,
        auth_temp,
        identity,
        local_transaction,
        mechanical,
        ready,
        task,
        fixture,
        index_payload,
        commit_payload,
        plan,
        observation,
        authorization,
        good,
    ) = _live_authorization()
    transaction_temp, ledger = _transaction_ledger(
        "rsi-exact-task-remote-publication-transaction-"
    )
    try:
        observer = _Observer((good, dict(good), dict(good), dict(good)))
        transport = _Transport()
        calls, reader = _reader(
            fixture,
            local_transaction,
            identity,
            commit_payload,
            index_payload,
        )
        times = iter(
            (
                "2026-09-15T06:41:40Z",
                "2026-09-15T06:41:41Z",
                "2026-09-15T06:41:42Z",
                "2026-09-15T06:41:43Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = (
                transaction._execute_verified_pilot_exact_task_remote_publication(
                    remote_publication_authorization=authorization,
                    ledger=ledger,
                    observer=observer,
                    transport=transport,
                    now_provider=lambda: next(times),
                )
            )

        assert len(observer.calls) == 4
        assert len(calls) == 48
        assert transport.calls[0][0] == "validate"
        assert [item[0] for item in transport.calls[1:]] == [
            "push",
            "post-push",
            "create-pr",
            "verify-pr",
        ]
        assert receipt.transaction_authenticated is True
        assert receipt.transaction_key_sha256 == authorization.execution_nonce_sha256
        assert receipt.remote_publication_authorization_sha256 == authorization.sha256
        assert receipt.remote_state_observation_sha256 == observation.sha256
        assert receipt.remote_publication_plan_sha256 == plan.sha256
        assert receipt.integration_readiness_sha256 == ready.sha256
        assert receipt.remote_target_config_sha256 == plan.remote_target_config_sha256
        assert (
            receipt.remote_repository_identity_sha256
            == plan.remote_repository_identity_sha256
        )
        assert receipt.pr_intent_sha256 == plan.pr_intent_sha256
        assert receipt.execution_nonce_sha256 == plan.execution_nonce_sha256
        assert receipt.development_task_sha256 == plan.development_task_sha256
        assert receipt.candidate_patch_sha256 == plan.candidate_patch_sha256
        assert receipt.publisher_credential_id == "test-publisher-v1"
        assert receipt.publisher_credential_config_sha256 == "a" * 64
        assert receipt.publisher_credential_path_sha256 == "b" * 64
        assert receipt.push_result_sha256 == "c" * 64
        assert receipt.task_id == task.task_id
        assert receipt.repository == task.repository
        assert receipt.repository_id == plan.repository_id
        assert receipt.provider == "github"
        assert receipt.host == "github.com"
        assert receipt.remote_name == "origin"
        assert receipt.base_branch == "main"
        assert receipt.head_branch == plan.head_branch
        assert receipt.exact_task_base_sha == task.base_sha
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.pull_request_number == 4242
        assert receipt.pull_request_api_url == (
            f"https://api.github.com/repos/{plan.repository}/pulls/4242"
        )
        assert receipt.host_transaction_guard_committed is True
        assert receipt.remote_publication_authorization_authenticated is True
        assert receipt.remote_publication_authorization_consumed is True
        assert receipt.exact_lane_revalidated_after_consumption is True
        assert receipt.remote_branch_created is True
        assert receipt.exact_commit_pushed is True
        assert receipt.draft_pr_created is True
        assert receipt.draft_pr_verified is True
        assert receipt.remote_write_performed is True
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.product_pilot_started is False
        assert receipt.draft is True
        assert receipt.maintainer_can_modify is False
        assert "token" not in receipt.to_dict()

        final, lock, pushed, pr = ledger._paths(plan.execution_nonce_sha256)
        assert final.is_file()
        assert lock.is_file()
        assert pushed.is_file()
        assert pr.is_file()
        _reject(lambda: ledger.acquire(authorization=authorization, plan=plan))

        reloaded = (
            transaction.PilotExactTaskRemotePublicationTransactionReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.transaction_authenticated is False

        for field, value in (
            ("host_transaction_guard_committed", False),
            ("remote_publication_authorization_consumed", False),
            ("remote_branch_created", False),
            ("exact_commit_pushed", False),
            ("draft_pr_created", False),
            ("draft_pr_verified", False),
            ("remote_write_performed", False),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("maintainer_can_modify", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    transaction.PilotExactTaskRemotePublicationTransactionReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        reloaded_auth = (
            publication_auth.PilotExactTaskRemotePublicationAuthorizationReceipt.from_mapping(
                authorization.to_dict()
            )
        )
        assert reloaded_auth.authorization_authenticated is False
        other_temp, other_ledger = _transaction_ledger(
            "rsi-exact-task-remote-publication-transaction-reloaded-"
        )
        try:
            _reject(
                lambda: transaction._execute_verified_pilot_exact_task_remote_publication(
                    remote_publication_authorization=reloaded_auth,
                    ledger=other_ledger,
                    observer=_Observer((good, good, good, good)),
                    transport=_Transport(),
                    now_provider=lambda: "2026-09-15T06:41:50Z",
                )
            )
        finally:
            other_temp.cleanup()

        # Remote drift after durable consumption burns the transaction slot.
        drift_temp, drift_ledger = _transaction_ledger(
            "rsi-exact-task-remote-publication-transaction-drift-"
        )
        try:
            drift_observer = _Observer(
                (
                    good,
                    dict(good),
                    {**good, "head_exists": True},
                    {**good, "head_exists": True},
                )
            )
            drift_calls, drift_reader = _reader(
                fixture,
                local_transaction,
                identity,
                commit_payload,
                index_payload,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
                _reject(
                    lambda: transaction._execute_verified_pilot_exact_task_remote_publication(
                        remote_publication_authorization=authorization,
                        ledger=drift_ledger,
                        observer=drift_observer,
                        transport=_Transport(),
                        now_provider=lambda: "2026-09-15T06:41:51Z",
                    )
                )
            drift_final, drift_lock, drift_pushed, drift_pr = drift_ledger._paths(
                plan.execution_nonce_sha256
            )
            assert drift_lock.is_file()
            assert not drift_final.exists()
            assert not drift_pushed.exists()
            assert not drift_pr.exists()
            assert drift_calls
        finally:
            drift_temp.cleanup()

        # Push failure occurs only after durable authority consumption.
        push_temp, push_ledger = _transaction_ledger(
            "rsi-exact-task-remote-publication-transaction-push-fail-"
        )
        try:
            push_calls, push_reader = _reader(
                fixture,
                local_transaction,
                identity,
                commit_payload,
                index_payload,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=push_reader):
                _reject(
                    lambda: transaction._execute_verified_pilot_exact_task_remote_publication(
                        remote_publication_authorization=authorization,
                        ledger=push_ledger,
                        observer=_Observer((good, good, good, good)),
                        transport=_Transport(fail_push=True),
                        now_provider=lambda: "2026-09-15T06:41:52Z",
                    )
                )
            push_final, push_lock, push_pushed, push_pr = push_ledger._paths(
                plan.execution_nonce_sha256
            )
            assert push_lock.is_file()
            assert not push_final.exists()
            assert not push_pushed.exists()
            assert not push_pr.exists()
            assert push_calls
        finally:
            push_temp.cleanup()

        # PR failure leaves the verified pushed marker for later exact recovery.
        pr_temp, pr_ledger = _transaction_ledger(
            "rsi-exact-task-remote-publication-transaction-pr-fail-"
        )
        try:
            pr_calls, pr_reader = _reader(
                fixture,
                local_transaction,
                identity,
                commit_payload,
                index_payload,
            )
            pr_times = iter(
                (
                    "2026-09-15T06:41:53Z",
                    "2026-09-15T06:41:54Z",
                )
            )
            with patch.object(fixture["git_runner"], "run", side_effect=pr_reader):
                _reject(
                    lambda: transaction._execute_verified_pilot_exact_task_remote_publication(
                        remote_publication_authorization=authorization,
                        ledger=pr_ledger,
                        observer=_Observer((good, good, good, good)),
                        transport=_Transport(fail_pr=True),
                        now_provider=lambda: next(pr_times),
                    )
                )
            pr_final, pr_lock, pr_pushed, pr_marker = pr_ledger._paths(
                plan.execution_nonce_sha256
            )
            assert pr_lock.is_file()
            assert pr_pushed.is_file()
            assert not pr_marker.exists()
            assert not pr_final.exists()
            assert pr_calls
        finally:
            pr_temp.cleanup()

        # Clock rollback before durable consumption does not burn a slot.
        clock_temp, clock_ledger = _transaction_ledger(
            "rsi-exact-task-remote-publication-transaction-clock-"
        )
        try:
            clock_calls, clock_reader = _reader(
                fixture,
                local_transaction,
                identity,
                commit_payload,
                index_payload,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=clock_reader):
                _reject(
                    lambda: transaction._execute_verified_pilot_exact_task_remote_publication(
                        remote_publication_authorization=authorization,
                        ledger=clock_ledger,
                        observer=_Observer((good, good)),
                        transport=_Transport(),
                        now_provider=lambda: "2026-09-15T06:41:29Z",
                    )
                )
            _final, clock_lock, _pushed, _pr = clock_ledger._paths(
                plan.execution_nonce_sha256
            )
            assert not clock_lock.exists()
            assert clock_calls
        finally:
            clock_temp.cleanup()

        credential = transaction.PilotExactTaskGitHubPublisherCredential(
            credential_id="publisher-test",
            repository=plan.repository,
            repository_id=plan.repository_id,
            username="x-access-token",
            token="ghp_0123456789abcdefghijklmnopqrstuv",
        )
        payload = credential.canonical_json().encode("utf-8")
        parsed, digest = transaction._parse_credential_payload(payload)
        assert parsed == credential
        assert digest == __import__("hashlib").sha256(payload).hexdigest()
        assert "ghp_0123456789abcdefghijklmnopqrstuv" not in repr(credential)

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["remote_branch_created"]["const"] is True
        assert schema["properties"]["exact_commit_pushed"]["const"] is True
        assert schema["properties"]["draft_pr_created"]["const"] is True
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            transaction.execute_pilot_exact_task_remote_publication
        ).parameters
        assert tuple(public_parameters) == ("remote_publication_authorization",)

        source = inspect.getsource(transaction)
        assert "run_bounded_subprocess" in source
        assert "--force-with-lease=refs/heads/" in source
        assert "protocol.https.allow=always" in source
        assert 'method="POST"' in source
        assert '"Authorization": f"Bearer ' in source
        assert "shell=True" not in source
        assert 'method="PATCH"' not in source
        assert 'method="DELETE"' not in source
        assert "/merges" not in source
        assert "/releases" not in source
        assert "merge_pull_request" not in source
    finally:
        transaction_temp.cleanup()
        auth_temp.cleanup()
        local_transaction_temp.cleanup()
        local_auth_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
