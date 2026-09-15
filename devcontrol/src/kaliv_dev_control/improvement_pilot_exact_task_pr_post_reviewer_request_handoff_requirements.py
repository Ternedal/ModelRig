"""ADR-DC-074 post-reviewer-request handoff requirements.

Consumes one live authenticated ADR-DC-073 receipt and emits immutable,
non-mutating requirements for a later fresh review observation. Requesting a
reviewer is not evidence of a review decision.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_pr_reviewer_request_transaction as transaction_boundary

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-post-reviewer-request-handoff-requirements/v1"
AUTHORITY = "requirements-only-after-one-exact-reviewer-request"


class PostReviewerRequestHandoffError(ValueError):
    pass


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrPostReviewerRequestHandoffRequirements:
    document: Mapping[str, Any]
    transaction: transaction_boundary.PilotExactTaskPrReviewerRequestTransaction

    @property
    def sha256(self) -> str:
        return _sha(self.document)


def build_pilot_exact_task_pr_post_reviewer_request_handoff_requirements(
    reviewer_request_transaction: transaction_boundary.PilotExactTaskPrReviewerRequestTransaction,
) -> PilotExactTaskPrPostReviewerRequestHandoffRequirements:
    if type(reviewer_request_transaction) is not transaction_boundary.PilotExactTaskPrReviewerRequestTransaction:
        raise PostReviewerRequestHandoffError("exact ADR-DC-073 transaction required")
    if reviewer_request_transaction.transaction_authenticated is not True:
        raise PostReviewerRequestHandoffError("reloaded or unauthenticated ADR-DC-073 transaction rejected")
    live_inputs = transaction_boundary._get_live_pr_reviewer_request_transaction_inputs(reviewer_request_transaction)
    if live_inputs is None:
        raise PostReviewerRequestHandoffError("ADR-DC-073 live provenance unavailable")

    source = reviewer_request_transaction
    required_true = (
        "reviewer_request_performed",
        "exact_individual_reviewer_request_performed",
        "post_reviewer_request_readback_verified",
        "exact_reviewer_set_verified",
        "team_reviewers_absent_verified",
        "reviewer_request_authorization_consumed",
    )
    if any(getattr(source, key) is not True for key in required_true):
        raise PostReviewerRequestHandoffError("completed exact reviewer-request evidence required")
    if source.reviewer_mutation_authorized is not False:
        raise PostReviewerRequestHandoffError("spent reviewer mutation authority required")

    document = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "reviewer_request_transaction_sha256": source.sha256,
        "repository": source.repository,
        "pull_request_number": source.pull_request_number,
        "pull_request_node_id_sha256": source.pull_request_node_id_sha256,
        "base_branch": source.base_branch,
        "head_branch": source.head_branch,
        "predicted_commit_sha": source.predicted_commit_sha,
        "reviewer_login": source.reviewer_login,
        "reviewer_user_id": source.reviewer_user_id,
        "reviewer_node_id_sha256": source.reviewer_node_id_sha256,
        "reviewer_request_nonce_sha256": source.reviewer_request_nonce_sha256,
        "requested_updated_at_utc": source.requested_updated_at_utc,
        "exact_reviewer_request_verified": True,
        "review_observation_required": True,
        "fresh_pr_state_required": True,
        "exact_head_required": True,
        "exact_reviewer_identity_required": True,
        "requested_reviewer_continuity_required": True,
        "review_decision_not_yet_observed": True,
        "review_approval_not_verified": True,
        "review_changes_requested_not_verified": True,
        "review_comment_not_verified": True,
        "reviewer_mutation_authorized": False,
        "review_mutation_authorized": False,
        "label_mutation_authorized": False,
        "merge_authorized": False,
        "release_authorized": False,
        "deploy_authorized": False,
        "production_activation_authorized": False,
    }
    return PilotExactTaskPrPostReviewerRequestHandoffRequirements(
        document=MappingProxyType(document), transaction=reviewer_request_transaction
    )


__all__ = [
    "SCHEMA", "AUTHORITY", "PostReviewerRequestHandoffError",
    "PilotExactTaskPrPostReviewerRequestHandoffRequirements",
    "build_pilot_exact_task_pr_post_reviewer_request_handoff_requirements",
]
