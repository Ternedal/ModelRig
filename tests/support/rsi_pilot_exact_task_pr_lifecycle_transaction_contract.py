"""Adversarial contract for ADR-DC-054 exact PR lifecycle transaction."""
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
    improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pr_lifecycle_transaction as lifecycle_tx,
)
from rsi_pilot_exact_task_pr_lifecycle_authorization_contract import (  # noqa: E402
    _authority,
    _ledger as _authorization_ledger,
    _live_post_attestation,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-lifecycle-transaction-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-054 unexpectedly accepted unsafe lifecycle transaction")


def _transaction_ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, lifecycle_tx._PilotExactTaskPrLifecycleTransactionLedger(root)


def _live_lifecycle_authorization():
    live, tx_temp, recovery_temp, attestation, plan, publication_auth = (
        _live_post_attestation()
    )
    config = lifecycle_auth.PilotExactTaskPrLifecycleConfig(
        repository=attestation.repository,
        repository_id=attestation.repository_id,
        reviewer_usernames=("reviewer-one", "reviewer-two"),
        reviewer_team_slugs=("modelrig-reviewers",),
    )
    payload = lifecycle_auth._build_authorization_payload(
        post_publication_attestation=attestation,
        config=config,
        requested_at_utc="2026-09-15T09:30:10Z",
        expires_at_utc="2026-09-15T09:35:00Z",
        authorizer_actor_id="lifecycle.operator",
        authorizer_system_id="offline-lifecycle-authority",
        authorizer_key_id="pr-lifecycle-key-1",
    )
    verifier, signature = _authority(payload)
    lifecycle_temp, lifecycle_ledger = _authorization_ledger(
        "rsi-exact-task-pr-lifecycle-transaction-auth-"
    )
    authorization = lifecycle_auth._authorize_verified_pilot_exact_task_pr_lifecycle(
        post_publication_attestation=attestation,
        lifecycle_config=config,
        authorization_payload=payload,
        signature=signature,
        verifier=verifier,
        ledger=lifecycle_ledger,
        now_provider=lambda: "2026-09-15T09:30:20Z",
    )
    assert authorization.authorization_authenticated is True
    return (
        live,
        tx_temp,
        recovery_temp,
        lifecycle_temp,
        attestation,
        plan,
        publication_auth,
        config,
        authorization,
    )


class _Transport:
    def __init__(self, authorization, attestation, *, fail_ready=False, fail_reviewers=False):
        self.authorization = authorization
        self.attestation = attestation
        self.fail_ready = fail_ready
        self.fail_reviewers = fail_reviewers
        self.ready = False
        self.usernames: tuple[str, ...] = ()
        self.teams: tuple[str, ...] = ()
        self.calls: list[str] = []
        self.scripted: list[lifecycle_tx._LifecycleRemoteState] = []

    def validate_for(self, authorization):
        self.calls.append("validate")
        assert authorization is self.authorization

    def _state(self):
        return lifecycle_tx._LifecycleRemoteState(
            pull_request_node_id="PR_kwDOEXACTNODE1234",
            draft=not self.ready,
            reviewer_usernames=self.usernames,
            reviewer_team_slugs=self.teams,
            repository=self.authorization.repository,
            repository_id=self.authorization.repository_id,
            base_branch=self.authorization.base_branch,
            base_sha=self.attestation.exact_task_base_sha,
            head_branch=self.authorization.head_branch,
            head_sha=self.authorization.predicted_commit_sha,
            pull_request_number=self.authorization.pull_request_number,
            pull_request_api_url=self.authorization.pull_request_api_url,
            maintainer_can_modify=False,
            state="open",
        )

    def observe(self, authorization):
        self.calls.append("observe")
        assert authorization is self.authorization
        if self.scripted:
            return self.scripted.pop(0)
        return self._state()

    def mark_ready(self, *, authorization, pull_request_node_id):
        self.calls.append("mark-ready")
        assert authorization is self.authorization
        assert pull_request_node_id == "PR_kwDOEXACTNODE1234"
        if self.fail_ready:
            raise lifecycle_tx.PilotExactTaskPrLifecycleTransactionError(
                "injected mark-ready failure"
            )
        self.ready = True

    def request_reviewers(self, *, authorization):
        self.calls.append("request-reviewers")
        assert authorization is self.authorization
        if self.fail_reviewers:
            raise lifecycle_tx.PilotExactTaskPrLifecycleTransactionError(
                "injected reviewer failure"
            )
        self.usernames = authorization.reviewer_usernames
        self.teams = authorization.reviewer_team_slugs


def _run(authorization, transport, ledger, *, times=None):
    values = iter(
        times
        or (
            "2026-09-15T09:31:00Z",
            "2026-09-15T09:31:01Z",
            "2026-09-15T09:31:02Z",
            "2026-09-15T09:31:03Z",
        )
    )
    return lifecycle_tx._execute_verified_pilot_exact_task_pr_lifecycle(
        pr_lifecycle_authorization=authorization,
        ledger=ledger,
        transport=transport,
        credential_id="test-publisher-v1",
        credential_config_sha256="a" * 64,
        credential_path_sha256="b" * 64,
        now_provider=lambda: next(values),
    )


def _copy_state(state, *, reviewer_usernames=None, reviewer_team_slugs=None, draft=None):
    return lifecycle_tx._LifecycleRemoteState(
        pull_request_node_id=state.pull_request_node_id,
        draft=state.draft if draft is None else draft,
        reviewer_usernames=(
            state.reviewer_usernames
            if reviewer_usernames is None
            else reviewer_usernames
        ),
        reviewer_team_slugs=(
            state.reviewer_team_slugs
            if reviewer_team_slugs is None
            else reviewer_team_slugs
        ),
        repository=state.repository,
        repository_id=state.repository_id,
        base_branch=state.base_branch,
        base_sha=state.base_sha,
        head_branch=state.head_branch,
        head_sha=state.head_sha,
        pull_request_number=state.pull_request_number,
        pull_request_api_url=state.pull_request_api_url,
        maintainer_can_modify=state.maintainer_can_modify,
        state=state.state,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        live,
        publication_tx_temp,
        recovery_temp,
        lifecycle_auth_temp,
        attestation,
        plan,
        publication_auth,
        config,
        authorization,
    ) = _live_lifecycle_authorization()
    del plan, publication_auth, config

    tx_temp, ledger = _transaction_ledger(
        "rsi-exact-task-pr-lifecycle-transaction-"
    )
    try:
        transport = _Transport(authorization, attestation)
        receipt = _run(authorization, transport, ledger)
        assert transport.calls == [
            "validate",
            "observe",
            "observe",
            "mark-ready",
            "observe",
            "request-reviewers",
            "observe",
            "observe",
        ]
        assert receipt.transaction_authenticated is True
        assert receipt.transaction_key_sha256 == authorization.execution_nonce_sha256
        assert receipt.pr_lifecycle_authorization_sha256 == authorization.sha256
        assert (
            receipt.post_publication_attestation_sha256
            == authorization.post_publication_attestation_sha256
        )
        assert receipt.lifecycle_config_sha256 == authorization.lifecycle_config_sha256
        assert receipt.reviewer_set_sha256 == authorization.reviewer_set_sha256
        assert receipt.predicted_commit_sha == authorization.predicted_commit_sha
        assert receipt.pull_request_number == authorization.pull_request_number
        assert receipt.reviewer_usernames == authorization.reviewer_usernames
        assert receipt.reviewer_team_slugs == authorization.reviewer_team_slugs
        assert receipt.publisher_credential_id == "test-publisher-v1"
        assert receipt.host_transaction_guard_committed is True
        assert receipt.pr_lifecycle_authorization_authenticated is True
        assert receipt.pr_lifecycle_authorization_consumed is True
        assert receipt.exact_pr_revalidated_after_consumption is True
        assert receipt.ready_for_review_completed is True
        assert receipt.reviewer_requests_completed is True
        assert receipt.final_pr_state_verified is True
        assert receipt.remote_write_performed is True
        assert receipt.ready_for_review_authorized is False
        assert receipt.reviewer_request_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.push_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.draft is False
        assert receipt.nonce_reusable is False
        assert "token" not in receipt.to_dict()

        final, lock, ready, reviewers = ledger._paths(
            authorization.execution_nonce_sha256
        )
        assert final.is_file()
        assert lock.is_file()
        assert ready.is_file()
        assert reviewers.is_file()

        reloaded = lifecycle_tx.PilotExactTaskPrLifecycleTransactionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.transaction_authenticated is False

        for field, value in (
            ("host_transaction_guard_committed", False),
            ("ready_for_review_completed", False),
            ("reviewer_requests_completed", False),
            ("final_pr_state_verified", False),
            ("remote_write_performed", False),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("draft", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    lifecycle_tx.PilotExactTaskPrLifecycleTransactionReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        # Reloaded ADR-DC-053 authority has audit value only and cannot execute.
        reloaded_auth = (
            lifecycle_auth.PilotExactTaskPrLifecycleAuthorizationReceipt.from_mapping(
                authorization.to_dict()
            )
        )
        assert reloaded_auth.authorization_authenticated is False
        reload_temp, reload_ledger = _transaction_ledger(
            "rsi-exact-task-pr-lifecycle-reloaded-"
        )
        try:
            _reject(
                lambda: _run(
                    reloaded_auth,
                    _Transport(authorization, attestation),
                    reload_ledger,
                )
            )
            assert not reload_ledger._paths(
                authorization.execution_nonce_sha256
            )[1].exists()
        finally:
            reload_temp.cleanup()

        # Remote drift after transaction consumption burns the slot before mutation.
        drift_temp, drift_ledger = _transaction_ledger(
            "rsi-exact-task-pr-lifecycle-drift-"
        )
        try:
            drift = _Transport(authorization, attestation)
            exact = drift._state()
            intruder = _copy_state(
                exact, reviewer_usernames=("intruder-reviewer",)
            )
            drift.scripted = [exact, intruder]
            _reject(lambda: _run(authorization, drift, drift_ledger))
            d_final, d_lock, d_ready, d_reviewers = drift_ledger._paths(
                authorization.execution_nonce_sha256
            )
            assert d_lock.is_file()
            assert not d_ready.exists()
            assert not d_reviewers.exists()
            assert not d_final.exists()
            assert "mark-ready" not in drift.calls
        finally:
            drift_temp.cleanup()

        # A mark-ready failure happens after durable transaction consumption.
        ready_fail_temp, ready_fail_ledger = _transaction_ledger(
            "rsi-exact-task-pr-lifecycle-ready-failure-"
        )
        try:
            ready_fail = _Transport(
                authorization, attestation, fail_ready=True
            )
            _reject(lambda: _run(authorization, ready_fail, ready_fail_ledger))
            f_final, f_lock, f_ready, f_reviewers = ready_fail_ledger._paths(
                authorization.execution_nonce_sha256
            )
            assert f_lock.is_file()
            assert not f_ready.exists()
            assert not f_reviewers.exists()
            assert not f_final.exists()
        finally:
            ready_fail_temp.cleanup()

        # Reviewer-request failure leaves a durable ready marker for recovery.
        reviewer_fail_temp, reviewer_fail_ledger = _transaction_ledger(
            "rsi-exact-task-pr-lifecycle-reviewer-failure-"
        )
        try:
            reviewer_fail = _Transport(
                authorization, attestation, fail_reviewers=True
            )
            _reject(
                lambda: _run(
                    authorization, reviewer_fail, reviewer_fail_ledger
                )
            )
            r_final, r_lock, r_ready, r_reviewers = reviewer_fail_ledger._paths(
                authorization.execution_nonce_sha256
            )
            assert r_lock.is_file()
            assert r_ready.is_file()
            assert not r_reviewers.exists()
            assert not r_final.exists()
        finally:
            reviewer_fail_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["ready_for_review_completed"]["const"] is True
        assert schema["properties"]["reviewer_requests_completed"]["const"] is True
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public = inspect.signature(
            lifecycle_tx.execute_pilot_exact_task_pr_lifecycle
        ).parameters
        assert tuple(public) == ("pr_lifecycle_authorization",)
        source = inspect.getsource(lifecycle_tx)
        assert "markPullRequestReadyForReview" in source
        assert "/requested_reviewers" in source
        assert "push_exact_commit" not in source
        assert "mergePullRequest" not in source
        assert "merge_pull_request" not in source
        assert "merge_authorized: bool = False" in source
    finally:
        tx_temp.cleanup()
        lifecycle_auth_temp.cleanup()
        recovery_temp.cleanup()
        publication_tx_temp.cleanup()
        (
            source_temp,
            admission_ledger_temp,
            capability_temp,
            reservation_temp,
            execution_temp,
            local_auth_temp,
            local_transaction_temp,
            auth_temp,
            *_rest,
        ) = live
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
