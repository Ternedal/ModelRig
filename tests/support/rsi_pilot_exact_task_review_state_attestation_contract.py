"""Adversarial contract for ADR-DC-057 exact GitHub review-state attestation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_lifecycle_attestation as post_lifecycle,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_review_state_attestation as review_state,
)
from rsi_pilot_exact_task_post_lifecycle_attestation_contract import (  # noqa: E402
    _attest as _attest_post_lifecycle,
)
from rsi_pilot_exact_task_pr_lifecycle_recovery_contract import (  # noqa: E402
    _RecoveryTransport,
    _cleanup_bundle,
    _recovery_ledger,
    _roots,
)
from rsi_pilot_exact_task_pr_lifecycle_transaction_contract import (  # noqa: E402
    _Transport as _LifecycleTransport,
    _live_lifecycle_authorization,
    _run,
    _transaction_ledger,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-review-state-attestation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-057 unexpectedly accepted unsafe review-state attestation"
    )


def _live_post_lifecycle_source():
    bundle = _live_lifecycle_authorization()
    (
        live,
        _publication_tx_temp,
        _publication_recovery_temp,
        lifecycle_auth_temp,
        publication_attestation,
        _plan,
        _publication_auth,
        _config,
        authorization,
    ) = bundle
    lifecycle_auth_root, publication_auth_root, local_root = _roots(
        live, lifecycle_auth_temp
    )
    tx_temp, tx_ledger = _transaction_ledger(
        "rsi-exact-task-review-state-source-tx-"
    )
    recovery_temp, recovery_ledger = _recovery_ledger(
        "rsi-exact-task-review-state-source-recovery-"
    )
    lifecycle_transport = _LifecycleTransport(
        authorization, publication_attestation
    )
    tx_receipt = _run(authorization, lifecycle_transport, tx_ledger)
    assert tx_receipt.transaction_authenticated is True
    remote = _RecoveryTransport(
        draft=False,
        usernames=authorization.reviewer_usernames,
        teams=authorization.reviewer_team_slugs,
    )
    source = _attest_post_lifecycle(
        authorization=authorization,
        tx_ledger=tx_ledger,
        recovery_ledger=recovery_ledger,
        lifecycle_auth_root=lifecycle_auth_root,
        publication_auth_root=publication_auth_root,
        local_root=local_root,
        transport=remote,
        now="2026-09-15T09:31:10Z",
    )
    assert source.attestation_authenticated is True
    assert source.completion_source == "transaction"
    return bundle, tx_temp, recovery_temp, tx_ledger, source, authorization


def _review(
    *,
    node_seed: str,
    login: str,
    state: str,
    submitted: str,
    commit_sha: str | None,
    association: str = "MEMBER",
):
    return review_state._SubmittedReview(
        review_node_id_sha256=__import__("hashlib").sha256(
            node_seed.encode("utf-8")
        ).hexdigest(),
        reviewer_login=login,
        state=state,
        submitted_at_utc=submitted,
        commit_sha=commit_sha,
        author_association=association,
    )


def _thread(
    *,
    node_seed: str,
    path: str,
    resolved: bool,
    outdated: bool,
):
    return review_state._ReviewThreadState(
        thread_node_id_sha256=__import__("hashlib").sha256(
            node_seed.encode("utf-8")
        ).hexdigest(),
        path=path,
        is_resolved=resolved,
        is_outdated=outdated,
    )


class _Transport:
    def __init__(self, source, *, scripted=None):
        self.source = source
        old_sha = "f" * 40
        if old_sha == source.predicted_commit_sha:
            old_sha = "e" * 40
        self.reviews = (
            _review(
                node_seed="review-1",
                login="reviewer-one",
                state="APPROVED",
                submitted="2026-09-15T09:32:00Z",
                commit_sha=source.predicted_commit_sha,
            ),
            _review(
                node_seed="review-2",
                login="reviewer-two",
                state="CHANGES_REQUESTED",
                submitted="2026-09-15T09:32:10Z",
                commit_sha=old_sha,
            ),
            _review(
                node_seed="review-3",
                login="reviewer-three",
                state="COMMENTED",
                submitted="2026-09-15T09:32:20Z",
                commit_sha=source.predicted_commit_sha,
                association="CONTRIBUTOR",
            ),
            _review(
                node_seed="review-4",
                login="reviewer-two",
                state="DISMISSED",
                submitted="2026-09-15T09:32:30Z",
                commit_sha=old_sha,
            ),
        )
        self.threads = (
            _thread(
                node_seed="thread-1",
                path="devcontrol/src/exact.py",
                resolved=True,
                outdated=False,
            ),
            _thread(
                node_seed="thread-2",
                path="devcontrol/src/exact.py",
                resolved=False,
                outdated=False,
            ),
            _thread(
                node_seed="thread-3",
                path="tests/support/exact_contract.py",
                resolved=False,
                outdated=True,
            ),
        )
        self.review_decision = "CHANGES_REQUESTED"
        self.calls: list[str] = []
        self.scripted = list(scripted or ())

    def validate_for(self, source):
        self.calls.append("validate")
        assert source is self.source

    def _state(self, *, threads=None, reviews=None, decision=None):
        return review_state._ReviewRemoteState(
            repository=self.source.repository,
            repository_id=self.source.repository_id,
            base_branch=self.source.base_branch,
            base_sha=self.source.exact_task_base_sha,
            head_branch=self.source.head_branch,
            head_sha=self.source.predicted_commit_sha,
            pull_request_number=self.source.pull_request_number,
            pull_request_api_url=self.source.pull_request_api_url,
            pull_request_node_id_sha256=self.source.pull_request_node_id_sha256,
            state="OPEN",
            draft=False,
            maintainer_can_modify=False,
            review_decision=(
                self.review_decision if decision is None else decision
            ),
            reviews=self.reviews if reviews is None else tuple(reviews),
            review_threads=(
                self.threads if threads is None else tuple(threads)
            ),
        )

    def observe(self, source):
        self.calls.append("observe")
        assert source is self.source
        if self.scripted:
            return self.scripted.pop(0)
        return self._state()


def _attest(source, tx_ledger, transport, *, now="2026-09-15T09:33:00Z",
            config_sha="a" * 64, path_sha="b" * 64):
    return review_state._attest_verified_pilot_exact_task_review_state(
        post_lifecycle_attestation=source,
        transaction_ledger_root=tx_ledger.root,
        transport=transport,
        publisher_credential_id="test-publisher-v1",
        publisher_credential_config_sha256=config_sha,
        publisher_credential_path_sha256=path_sha,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        bundle,
        tx_temp,
        recovery_temp,
        tx_ledger,
        source,
        authorization,
    ) = _live_post_lifecycle_source()
    try:
        transport = _Transport(source)
        receipt = _attest(source, tx_ledger, transport)

        assert transport.calls == ["validate", "observe", "observe"]
        assert receipt.attestation_authenticated is True
        assert receipt.post_lifecycle_attestation_sha256 == source.sha256
        assert (
            receipt.completion_source_receipt_sha256
            == source.completion_source_receipt_sha256
        )
        assert (
            receipt.pr_lifecycle_authorization_sha256
            == source.pr_lifecycle_authorization_sha256
        )
        assert receipt.lifecycle_config_sha256 == source.lifecycle_config_sha256
        assert receipt.reviewer_set_sha256 == source.reviewer_set_sha256
        assert receipt.execution_nonce_sha256 == source.execution_nonce_sha256
        assert receipt.development_task_sha256 == source.development_task_sha256
        assert receipt.candidate_patch_sha256 == source.candidate_patch_sha256
        assert receipt.pr_intent_sha256 == source.pr_intent_sha256
        assert receipt.transaction_lock_sha256 == source.transaction_lock_sha256
        assert (
            receipt.post_lifecycle_remote_observation_sha256
            == source.remote_observation_sha256
        )
        assert receipt.repository == source.repository
        assert receipt.repository_id == source.repository_id
        assert receipt.base_branch == source.base_branch
        assert receipt.head_branch == source.head_branch
        assert receipt.exact_task_base_sha == source.exact_task_base_sha
        assert receipt.predicted_commit_sha == source.predicted_commit_sha
        assert receipt.pull_request_number == source.pull_request_number
        assert receipt.pull_request_api_url == source.pull_request_api_url
        assert (
            receipt.pull_request_node_id_sha256
            == source.pull_request_node_id_sha256
        )
        assert (
            receipt.authorized_reviewer_usernames
            == source.reviewer_usernames
        )
        assert (
            receipt.authorized_reviewer_team_slugs
            == source.reviewer_team_slugs
        )
        assert receipt.publisher_credential_id == "test-publisher-v1"
        assert receipt.publisher_credential_config_sha256 == "a" * 64
        assert receipt.publisher_credential_path_sha256 == "b" * 64
        assert receipt.github_review_decision == "CHANGES_REQUESTED"
        assert receipt.submitted_review_count == 4
        assert receipt.approved_review_count == 1
        assert receipt.changes_requested_review_count == 1
        assert receipt.commented_review_count == 1
        assert receipt.dismissed_review_count == 1
        assert receipt.exact_head_approved_review_count == 1
        assert receipt.exact_head_changes_requested_review_count == 0
        assert receipt.review_thread_count == 3
        assert receipt.unresolved_review_thread_count == 2
        assert receipt.unresolved_outdated_review_thread_count == 1
        assert receipt.post_lifecycle_attestation_authenticated is True
        assert receipt.exact_pr_revalidated is True
        assert receipt.submitted_reviews_observed is True
        assert receipt.review_threads_observed is True
        assert receipt.double_observation_matched is True
        assert receipt.review_state_attested is True
        assert receipt.review_submission_authorized is False
        assert receipt.review_thread_mutation_authorized is False
        assert receipt.merge_readiness_authorized is False
        assert receipt.ready_for_review_authorized is False
        assert receipt.reviewer_request_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.draft is False
        assert receipt.nonce_reusable is False

        reloaded = (
            review_state.PilotExactTaskReviewStateAttestationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.attestation_authenticated is False

        # A reloaded ADR-DC-056 copy retains audit content but cannot mint ADR-DC-057.
        reloaded_source = (
            post_lifecycle.PilotExactTaskPostLifecycleAttestationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert reloaded_source.attestation_authenticated is False
        _reject(
            lambda: _attest(
                reloaded_source,
                tx_ledger,
                _Transport(reloaded_source),
            )
        )

        for field, value in (
            ("post_lifecycle_attestation_authenticated", False),
            ("exact_pr_revalidated", False),
            ("submitted_reviews_observed", False),
            ("review_threads_observed", False),
            ("double_observation_matched", False),
            ("review_state_attested", False),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("merge_readiness_authorized", True),
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
                    review_state.PilotExactTaskReviewStateAttestationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        # Thread-state drift between observations fails closed.
        first = transport._state()
        drift_threads = (
            transport.threads[0],
            review_state._ReviewThreadState(
                thread_node_id_sha256=transport.threads[1].thread_node_id_sha256,
                path=transport.threads[1].path,
                is_resolved=True,
                is_outdated=False,
            ),
            transport.threads[2],
        )
        second = transport._state(threads=drift_threads)
        drift = _Transport(source, scripted=(first, second))
        _reject(lambda: _attest(source, tx_ledger, drift))

        # Credential rotation/drift cannot silently change the authenticated read root.
        _reject(
            lambda: _attest(
                source,
                tx_ledger,
                _Transport(source),
                config_sha="c" * 64,
            )
        )
        _reject(
            lambda: _attest(
                source,
                tx_ledger,
                _Transport(source),
                path_sha="d" * 64,
            )
        )

        # Clock rollback behind ADR-DC-056 is rejected.
        _reject(
            lambda: _attest(
                source,
                tx_ledger,
                _Transport(source),
                now="2026-09-15T09:31:09Z",
            )
        )

        # Query transport refuses GraphQL mutation documents before network I/O.
        unsafe_transport = object.__new__(
            review_state._GitHubReviewStateTransport
        )
        _reject(
            lambda: unsafe_transport._graphql_query(
                query=(
                    "mutation Resolve($id:ID!){"
                    "resolveReviewThread(input:{threadId:$id}){thread{id}}}"
                ),
                variables={"id": "THREAD"},
            )
        )

        # Pending non-submitted review is ignored, but malformed submitted review fails.
        assert (
            review_state._GitHubReviewStateTransport._parse_review(
                {
                    "id": "PENDING_REVIEW",
                    "author": {"login": "reviewer-one"},
                    "authorAssociation": "MEMBER",
                    "state": "PENDING",
                    "submittedAt": None,
                    "commit": None,
                }
            )
            is None
        )
        _reject(
            lambda: review_state._GitHubReviewStateTransport._parse_review(
                {
                    "id": "BROKEN_REVIEW",
                    "author": {"login": "reviewer-one"},
                    "authorAssociation": "MEMBER",
                    "state": "APPROVED",
                    "submittedAt": None,
                    "commit": {"oid": source.predicted_commit_sha},
                }
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            review_state.PilotExactTaskReviewStateAttestationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert (
            schema["properties"]["production_activation_authorized"]["const"]
            is False
        )
        assert schema["properties"]["nonce_reusable"]["const"] is False

        public = inspect.signature(
            review_state.attest_pilot_exact_task_review_state
        ).parameters
        assert tuple(public) == ("post_lifecycle_attestation",)

        source_text = inspect.getsource(review_state)
        assert "query ReviewStateReviews" in source_text
        assert "query ReviewStateThreads" in source_text
        assert "markPullRequestReadyForReview" not in source_text
        assert "resolveReviewThread(input" not in source_text
        assert "unresolveReviewThread" not in source_text
        assert "dismissPullRequestReview" not in source_text
        assert "addPullRequestReview" not in source_text
        assert "mergePullRequest" not in source_text
        assert "request_reviewers(" not in source_text
        assert "merge_readiness_authorized: bool = False" in source_text
        assert "merge_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        recovery_temp.cleanup()
        tx_temp.cleanup()
        _cleanup_bundle(bundle)


if __name__ == "__main__":
    run_contract()
