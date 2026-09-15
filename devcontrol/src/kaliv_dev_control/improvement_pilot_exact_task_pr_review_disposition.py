"""ADR-DC-079 deterministic exact review-disposition evaluation.

Consumes one live ADR-DC-078 submitted-review observation and deterministically
classifies only the pinned reviewer's exact-head evidence as APPROVED, BLOCKED,
or PENDING. The policy is code-pinned and content-addressed. This boundary
never mutates GitHub and never grants merge readiness or merge authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_pr_submitted_review_observation as observation_boundary
from .improvement_pilot_exact_task_pr_submitted_review_observation import (
    PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_AUTHORITY,
    PilotExactTaskPrSubmittedReviewObservation,
)

PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-review-disposition/v1"
PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_AUTHORITY = "evaluated-one-dc-l16-exact-pr-review-disposition-only"
PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCOPE = "deterministic-exact-head-pinned-reviewer-policy-v1"
PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_POLICY_SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-review-disposition-policy/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY = "Ternedal/ModelRig"
_POLICY = MappingProxyType({
    "schema": PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_POLICY_SCHEMA,
    "repository": _REPOSITORY,
    "reviewer_source": "exact-pinned-reviewer-only",
    "head_scope": "exact-predicted-head-only",
    "required_approved_state": "APPROVED",
    "pending_review_blocks_approval": True,
    "stale_head_reviews_count_for_approval": False,
    "commented_is_approval": False,
    "dismissed_is_approval": False,
    "changes_requested_is_approval": False,
    "review_policy_only": True,
    "merge_readiness_granted": False,
    "merge_authority_granted": False,
})


class PilotExactTaskPrReviewDispositionError(ValueError):
    """Review evidence or deterministic policy input is invalid."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewDispositionError("review-disposition value is not canonical JSON") from exc


def _policy_sha256() -> str:
    return hashlib.sha256(_canonical(dict(_POLICY)).encode("utf-8")).hexdigest()


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewDispositionError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewDispositionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewDispositionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrReviewDispositionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_observation(value: Any) -> PilotExactTaskPrSubmittedReviewObservation:
    if type(value) is not PilotExactTaskPrSubmittedReviewObservation:
        raise PilotExactTaskPrReviewDispositionError("exact live ADR-DC-078 submitted-review observation is required")
    try:
        replayed = PilotExactTaskPrSubmittedReviewObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewDispositionError("ADR-DC-078 observation replay validation failed") from exc
    required_true = (
        "stable_double_observation_verified", "credential_free_reads", "fixed_origin_reads", "redirects_forbidden",
        "response_bounded", "pagination_bounded", "exact_pr_identity_revalidated", "exact_head_revalidated",
        "exact_reviewer_identity_bound", "other_requested_reviewers_absent_verified", "team_reviewers_absent_verified",
        "submitted_reviews_observed", "checkpoint_reusable",
    )
    forced_false = (
        "review_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized",
        "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized",
        "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized",
        "production_activation_authorized",
    )
    live = observation_boundary._get_live_pr_submitted_review_observation_inputs(value)
    checkpoint = None if live is None else live.get("review_observation_checkpoint")
    if (
        replayed != value or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PR_SUBMITTED_REVIEW_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != _REPOSITORY or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None or _LOGIN.fullmatch(value.reviewer_login) is None
        or checkpoint is None or getattr(checkpoint, "checkpoint_authenticated", None) is not True
        or checkpoint.sha256 != value.review_observation_checkpoint_sha256
        or checkpoint.checkpoint_key_sha256 != value.checkpoint_key_sha256
        or checkpoint.predicted_commit_sha != value.predicted_commit_sha
        or checkpoint.reviewer_login != value.reviewer_login
        or checkpoint.reviewer_user_id != value.reviewer_user_id
    ):
        raise PilotExactTaskPrReviewDispositionError("review disposition requires one live inert ADR-DC-078 observation")
    return value


def _classify(observation: PilotExactTaskPrSubmittedReviewObservation) -> tuple[str, str]:
    if observation.exact_head_pending_review_count > 0:
        return "PENDING", "pending-exact-head-review-present"
    if observation.latest_exact_head_review_present is not True:
        return "PENDING", "no-submitted-exact-head-review"
    state = observation.latest_exact_head_review_state
    if state == "APPROVED":
        return "APPROVED", "latest-exact-head-review-approved"
    if state == "CHANGES_REQUESTED":
        return "BLOCKED", "latest-exact-head-review-changes-requested"
    if state == "COMMENTED":
        return "PENDING", "latest-exact-head-review-commented"
    if state == "DISMISSED":
        return "PENDING", "latest-exact-head-review-dismissed"
    raise PilotExactTaskPrReviewDispositionError("latest exact-head review state is unsupported by policy")


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrSubmittedReviewObservation]]] = {}


def _mark_authenticated(result: Any, observation: PilotExactTaskPrSubmittedReviewObservation) -> None:
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(observation))


def _get_live_pr_review_disposition_inputs(result: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    pid, digest, result_ref, observation_ref = entry
    observation = observation_ref()
    if (
        pid != os.getpid() or result_ref() is not result or observation is None
        or observation.observation_authenticated is not True
        or observation.sha256 != result.submitted_review_observation_sha256
        or result.sha256 != digest
    ):
        return None
    return MappingProxyType({"submitted_review_observation": observation})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewDisposition:
    submitted_review_observation_sha256: str
    review_observation_checkpoint_sha256: str
    checkpoint_key_sha256: str
    source_reviewer_request_attestation_sha256: str
    reviewer_write_transaction_sha256: str
    reviewer_request_nonce_sha256: str
    review_disposition_policy_sha256: str
    repository: str
    pull_request_number: int
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    total_review_count: int
    pinned_reviewer_review_count: int
    pinned_exact_head_review_count: int
    pinned_stale_head_review_count: int
    exact_head_approved_review_count: int
    exact_head_changes_requested_review_count: int
    exact_head_commented_review_count: int
    exact_head_dismissed_review_count: int
    exact_head_pending_review_count: int
    latest_exact_head_review_present: bool
    latest_exact_head_review_id: int
    latest_exact_head_review_node_id_sha256: str
    latest_exact_head_review_state: str
    latest_exact_head_review_submitted_at_utc: str
    review_disposition: str
    disposition_reason: str
    evaluated_at_utc: str
    review_policy_evaluated: bool = True
    review_policy_passed: bool = False
    exact_head_approval_verified: bool = False
    stale_head_reviews_ignored: bool = True
    pinned_reviewer_only_policy: bool = True
    fresh_merge_preflight_required: bool = True
    semantic_pr_metadata_policy_required: bool = True
    checkpoint_reusable: bool = True
    reviewer_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_AUTHORITY
    evaluation_scope: str = PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_AUTHORITY or self.evaluation_scope != PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCOPE:
            raise PilotExactTaskPrReviewDispositionError("review-disposition schema/authority/scope unsupported")
        for name in (
            "submitted_review_observation_sha256", "review_observation_checkpoint_sha256", "checkpoint_key_sha256",
            "source_reviewer_request_attestation_sha256", "reviewer_write_transaction_sha256", "reviewer_request_nonce_sha256",
            "review_disposition_policy_sha256", "pull_request_node_id_sha256", "reviewer_user_node_id_sha256",
            "latest_exact_head_review_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.latest_exact_head_review_submitted_at_utc, name="latest_exact_head_review_submitted_at_utc")
        _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if (
            self.review_disposition_policy_sha256 != _policy_sha256() or self.repository != _REPOSITORY
            or self.base_branch != "main" or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or not isinstance(self.reviewer_login, str) or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool) or not isinstance(self.reviewer_user_id, int) or self.reviewer_user_id < 1
        ):
            raise PilotExactTaskPrReviewDispositionError("review-disposition target/policy binding invalid")
        count_names = (
            "total_review_count", "pinned_reviewer_review_count", "pinned_exact_head_review_count", "pinned_stale_head_review_count",
            "exact_head_approved_review_count", "exact_head_changes_requested_review_count", "exact_head_commented_review_count",
            "exact_head_dismissed_review_count", "exact_head_pending_review_count", "latest_exact_head_review_id",
        )
        if any(isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int) or getattr(self, name) < 0 for name in count_names):
            raise PilotExactTaskPrReviewDispositionError("review-disposition counts are invalid")
        if (
            self.pinned_reviewer_review_count != self.pinned_exact_head_review_count + self.pinned_stale_head_review_count
            or self.pinned_reviewer_review_count > self.total_review_count
            or sum((self.exact_head_approved_review_count, self.exact_head_changes_requested_review_count, self.exact_head_commented_review_count, self.exact_head_dismissed_review_count, self.exact_head_pending_review_count)) != self.pinned_exact_head_review_count
        ):
            raise PilotExactTaskPrReviewDispositionError("review-disposition counts are inconsistent")
        if self.review_disposition not in {"APPROVED", "BLOCKED", "PENDING"}:
            raise PilotExactTaskPrReviewDispositionError("review disposition is unsupported")
        expected_reasons = {
            "latest-exact-head-review-approved", "latest-exact-head-review-changes-requested",
            "latest-exact-head-review-commented", "latest-exact-head-review-dismissed",
            "pending-exact-head-review-present", "no-submitted-exact-head-review",
        }
        if self.disposition_reason not in expected_reasons:
            raise PilotExactTaskPrReviewDispositionError("review disposition reason is unsupported")
        approved = self.review_disposition == "APPROVED"
        if (
            not isinstance(self.review_policy_passed, bool) or not isinstance(self.exact_head_approval_verified, bool)
            or self.review_policy_passed is not approved or self.exact_head_approval_verified is not approved
            or (approved and (self.latest_exact_head_review_present is not True or self.latest_exact_head_review_state != "APPROVED" or self.exact_head_pending_review_count != 0))
        ):
            raise PilotExactTaskPrReviewDispositionError("review-disposition approval binding is invalid")
        required_true = (
            "review_policy_evaluated", "stale_head_reviews_ignored", "pinned_reviewer_only_policy",
            "fresh_merge_preflight_required", "semantic_pr_metadata_policy_required", "checkpoint_reusable",
        )
        forced_false = (
            "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized",
            "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewDispositionError("review-disposition evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewDispositionError("review-disposition evaluation cannot grant mutation authority")

    @property
    def disposition_authenticated(self) -> bool:
        return _get_live_pr_review_disposition_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewDisposition":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewDispositionError("review disposition must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewDispositionError("review-disposition fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_pr_review_disposition(*, submitted_review_observation: PilotExactTaskPrSubmittedReviewObservation, now_provider: Any) -> PilotExactTaskPrReviewDisposition:
    observation = _require_live_observation(submitted_review_observation)
    disposition, reason = _classify(observation)
    evaluated_at = now_provider()
    if _utc(evaluated_at, name="evaluated_at_utc") < _utc(observation.second_observed_at_utc, name="ADR-DC-078 second_observed_at_utc"):
        raise PilotExactTaskPrReviewDispositionError("clock moved backwards before review-disposition evaluation")
    approved = disposition == "APPROVED"
    result = PilotExactTaskPrReviewDisposition(
        submitted_review_observation_sha256=observation.sha256,
        review_observation_checkpoint_sha256=observation.review_observation_checkpoint_sha256,
        checkpoint_key_sha256=observation.checkpoint_key_sha256,
        source_reviewer_request_attestation_sha256=observation.source_reviewer_request_attestation_sha256,
        reviewer_write_transaction_sha256=observation.reviewer_write_transaction_sha256,
        reviewer_request_nonce_sha256=observation.reviewer_request_nonce_sha256,
        review_disposition_policy_sha256=_policy_sha256(),
        repository=observation.repository, pull_request_number=observation.pull_request_number,
        pull_request_node_id_sha256=observation.pull_request_node_id_sha256, base_branch=observation.base_branch,
        head_branch=observation.head_branch, predicted_commit_sha=observation.predicted_commit_sha,
        reviewer_login=observation.reviewer_login, reviewer_user_id=observation.reviewer_user_id,
        reviewer_user_node_id_sha256=observation.reviewer_user_node_id_sha256,
        total_review_count=observation.total_review_count, pinned_reviewer_review_count=observation.pinned_reviewer_review_count,
        pinned_exact_head_review_count=observation.pinned_exact_head_review_count, pinned_stale_head_review_count=observation.pinned_stale_head_review_count,
        exact_head_approved_review_count=observation.exact_head_approved_review_count,
        exact_head_changes_requested_review_count=observation.exact_head_changes_requested_review_count,
        exact_head_commented_review_count=observation.exact_head_commented_review_count,
        exact_head_dismissed_review_count=observation.exact_head_dismissed_review_count,
        exact_head_pending_review_count=observation.exact_head_pending_review_count,
        latest_exact_head_review_present=observation.latest_exact_head_review_present,
        latest_exact_head_review_id=observation.latest_exact_head_review_id,
        latest_exact_head_review_node_id_sha256=observation.latest_exact_head_review_node_id_sha256,
        latest_exact_head_review_state=observation.latest_exact_head_review_state,
        latest_exact_head_review_submitted_at_utc=observation.latest_exact_head_review_submitted_at_utc,
        review_disposition=disposition, disposition_reason=reason, evaluated_at_utc=evaluated_at,
        review_policy_passed=approved, exact_head_approval_verified=approved,
    )
    _mark_authenticated(result, observation)
    if result.disposition_authenticated is not True:
        raise PilotExactTaskPrReviewDispositionError("review-disposition evaluation lost live ADR-DC-078 provenance")
    return result


def evaluate_pilot_exact_task_pr_review_disposition(submitted_review_observation: PilotExactTaskPrSubmittedReviewObservation) -> PilotExactTaskPrReviewDisposition:
    """Evaluate deterministic exact-head review disposition; never mutate GitHub."""
    return _evaluate_verified_pilot_exact_task_pr_review_disposition(
        submitted_review_observation=submitted_review_observation,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCHEMA", "PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_SCOPE", "PILOT_EXACT_TASK_PR_REVIEW_DISPOSITION_POLICY_SCHEMA",
    "PilotExactTaskPrReviewDispositionError", "PilotExactTaskPrReviewDisposition",
    "evaluate_pilot_exact_task_pr_review_disposition",
]
