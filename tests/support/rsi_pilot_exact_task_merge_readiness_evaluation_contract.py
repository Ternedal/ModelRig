"""Adversarial contract for ADR-DC-058 exact merge-readiness evaluation."""
from __future__ import annotations

import hashlib
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
    improvement_pilot_exact_task_merge_readiness_evaluation as readiness,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_review_state_attestation as review_state,
)
from rsi_pilot_exact_task_pr_lifecycle_recovery_contract import _cleanup_bundle  # noqa: E402
from rsi_pilot_exact_task_review_state_attestation_contract import (  # noqa: E402
    _Transport,
    _attest,
    _live_post_lifecycle_source,
    _review,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-merge-readiness-evaluation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-058 unexpectedly accepted unsafe merge-readiness input")


def _policy(source, *, approvals=1, repository=None, repository_id=None):
    return readiness.PilotExactTaskMergeReadinessPolicy(
        repository=source.repository if repository is None else repository,
        repository_id=source.repository_id if repository_id is None else repository_id,
        minimum_exact_head_approved_reviews=approvals,
    )


def _evaluate(receipt, policy, *, now="2026-09-15T09:34:00Z", digest=None):
    return readiness._evaluate_verified_pilot_exact_task_merge_readiness(
        review_state_attestation=receipt,
        policy=policy,
        policy_sha256=policy.sha256 if digest is None else digest,
        now_provider=lambda: now,
    )


def _ready_review_transport(source):
    transport = _Transport(source)
    transport.reviews = (
        _review(
            node_seed="merge-ready-review-1",
            login="reviewer-one",
            state="APPROVED",
            submitted="2026-09-15T09:32:00Z",
            commit_sha=source.predicted_commit_sha,
        ),
    )
    transport.threads = ()
    transport.review_decision = "APPROVED"
    return transport


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle, tx_temp, recovery_temp, tx_ledger, source, _authorization = (
        _live_post_lifecycle_source()
    )
    try:
        # Positive readiness requires GitHub APPROVED + exact-head approval + no blockers.
        ready_review = _attest(source, tx_ledger, _ready_review_transport(source))
        assert ready_review.attestation_authenticated is True
        policy = _policy(source)
        receipt = _evaluate(ready_review, policy)
        assert receipt.evaluation_authenticated is True
        assert receipt.review_state_attestation_sha256 == ready_review.sha256
        assert receipt.post_lifecycle_attestation_sha256 == source.sha256
        assert receipt.review_state_sha256 == ready_review.review_state_sha256
        assert receipt.reviews_sha256 == ready_review.reviews_sha256
        assert receipt.review_threads_sha256 == ready_review.review_threads_sha256
        assert receipt.merge_readiness_policy_sha256 == policy.sha256
        assert receipt.execution_nonce_sha256 == ready_review.execution_nonce_sha256
        assert receipt.predicted_commit_sha == source.predicted_commit_sha
        assert receipt.pull_request_number == source.pull_request_number
        assert receipt.github_review_decision == "APPROVED"
        assert receipt.exact_head_approved_review_count == 1
        assert receipt.exact_head_changes_requested_review_count == 0
        assert receipt.unresolved_review_thread_count == 0
        assert receipt.github_review_decision_satisfied is True
        assert receipt.exact_head_approval_threshold_satisfied is True
        assert receipt.no_exact_head_changes_requested is True
        assert receipt.no_unresolved_review_threads is True
        assert receipt.blocker_codes == ()
        assert receipt.merge_readiness_evaluated is True
        assert receipt.merge_ready is True
        assert receipt.merge_readiness_authorized is False
        assert receipt.review_submission_authorized is False
        assert receipt.review_thread_mutation_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = readiness.PilotExactTaskMergeReadinessEvaluationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.evaluation_authenticated is False

        # Negative policy result is a valid authenticated evaluation, not an exception.
        blocked_review = _attest(source, tx_ledger, _Transport(source))
        blocked = _evaluate(blocked_review, policy)
        assert blocked.evaluation_authenticated is True
        assert blocked.merge_ready is False
        assert blocked.exact_head_approved_review_count == 1
        assert blocked.exact_head_changes_requested_review_count == 0
        assert blocked.unresolved_review_thread_count == 2
        assert blocked.blocker_codes == (
            "github-review-decision-not-approved",
            "unresolved-review-threads-present",
        )

        # Historical CHANGES_REQUESTED on an old commit is evidence but not the exact-head blocker.
        assert blocked_review.changes_requested_review_count == 1
        assert blocked_review.exact_head_changes_requested_review_count == 0

        # An exact-head changes request is an explicit blocker in addition to GitHub decision.
        exact_change_transport = _ready_review_transport(source)
        exact_change_transport.reviews = exact_change_transport.reviews + (
            _review(
                node_seed="merge-ready-review-change",
                login="reviewer-two",
                state="CHANGES_REQUESTED",
                submitted="2026-09-15T09:32:10Z",
                commit_sha=source.predicted_commit_sha,
            ),
        )
        exact_change_transport.review_decision = "CHANGES_REQUESTED"
        exact_change = _attest(source, tx_ledger, exact_change_transport)
        exact_change_result = _evaluate(exact_change, policy)
        assert exact_change_result.merge_ready is False
        assert exact_change_result.exact_head_changes_requested_review_count == 1
        assert exact_change_result.blocker_codes == (
            "github-review-decision-not-approved",
            "exact-head-changes-requested-present",
        )

        # Threshold comes only from host policy and is never inferred from raw review count.
        threshold_policy = _policy(source, approvals=2)
        threshold = _evaluate(ready_review, threshold_policy)
        assert threshold.merge_ready is False
        assert threshold.blocker_codes == ("insufficient-exact-head-approvals",)

        # Reloaded ADR-DC-057 loses live provenance and cannot mint readiness evidence.
        reloaded_review = review_state.PilotExactTaskReviewStateAttestationReceipt.from_mapping(
            ready_review.to_dict()
        )
        assert reloaded_review.attestation_authenticated is False
        _reject(lambda: _evaluate(reloaded_review, policy))

        # Caller cannot substitute repository policy or lie about its digest.
        _reject(lambda: _evaluate(ready_review, _policy(source, repository="other/repo")))
        _reject(lambda: _evaluate(ready_review, _policy(source, repository_id="999")))
        _reject(lambda: _evaluate(ready_review, policy, digest="f" * 64))

        # Clock rollback behind the exact review observation is rejected.
        _reject(lambda: _evaluate(ready_review, policy, now="2026-09-15T09:32:59Z"))

        # Canonical policy bytes are deterministic and non-canonical JSON is rejected.
        policy_payload = policy.canonical_json().encode("utf-8")
        assert readiness._parse_policy(policy_payload) == policy
        _reject(lambda: readiness._parse_policy(policy_payload + b"\n"))

        # Receipt tampering cannot turn evidence into authority or change evaluated truth.
        for field, value in (
            ("review_state_attestation_authenticated", False),
            ("merge_readiness_policy_host_pinned", False),
            ("merge_readiness_evaluated", False),
            ("merge_readiness_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("pr_mutation_authorized", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("merge_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("merge_ready", False),
        ):
            _reject(
                lambda field=field, value=value: (
                    readiness.PilotExactTaskMergeReadinessEvaluationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            readiness.PilotExactTaskMergeReadinessEvaluationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert schema["properties"]["nonce_reusable"]["const"] is False

        public = inspect.signature(
            readiness.evaluate_pilot_exact_task_merge_readiness
        ).parameters
        assert tuple(public) == ("review_state_attestation",)
        source_text = inspect.getsource(readiness)
        assert "urllib" not in source_text
        assert "subprocess" not in source_text
        assert "merge_pull_request" not in source_text
        assert "enable_auto_merge" not in source_text
        assert "add_review_to_pr" not in source_text
        assert "resolve_review_thread" not in source_text
        assert "merge_readiness_authorized: bool = False" in source_text
        assert "merge_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        recovery_temp.cleanup()
        tx_temp.cleanup()
        _cleanup_bundle(bundle)


if __name__ == "__main__":
    run_contract()
