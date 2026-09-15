"""ADR-DC-058 exact merge-readiness policy evaluation.

This boundary accepts only one fresh live ADR-DC-057 review-state attestation and
one host-admin-pinned canonical merge-readiness policy. It evaluates immutable
review facts into ``merge_ready`` plus explicit blocker codes.

It performs no GitHub/network mutation and grants no merge authority. A positive
``merge_ready`` result is evidence only; later authority must be a separate
boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_review_state_attestation as review_boundary
from .improvement_pilot_exact_task_review_state_attestation import (
    PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_AUTHORITY,
    PilotExactTaskReviewStateAttestationReceipt,
)

PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-merge-readiness-evaluation-receipt/v1"
)
PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-merge-readiness-only"
)
PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCOPE = (
    "exact-review-policy-evaluation-only-v1"
)
PILOT_EXACT_TASK_MERGE_READINESS_POLICY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-merge-readiness-policy/v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"
_BLOCKER_ORDER = (
    "github-review-decision-not-approved",
    "insufficient-exact-head-approvals",
    "exact-head-changes-requested-present",
    "unresolved-review-threads-present",
)
_POSIX_POLICY = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-merge-readiness-policy-v1.json"
)
_WINDOWS_POLICY = Path(
    r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-merge-readiness-policy-v1.json"
)


class PilotExactTaskMergeReadinessEvaluationError(ValueError):
    """Review evidence or merge-readiness policy is stale, invalid or over-broad."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskMergeReadinessEvaluationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskMergeReadinessEvaluationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskMergeReadinessEvaluationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskMergeReadinessEvaluationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskMergeReadinessEvaluationError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskMergeReadinessPolicy:
    repository: str
    repository_id: str
    minimum_exact_head_approved_reviews: int = 1
    required_github_review_decision: str = "APPROVED"
    require_no_exact_head_changes_requested: bool = True
    require_no_unresolved_review_threads: bool = True
    schema: str = PILOT_EXACT_TASK_MERGE_READINESS_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_MERGE_READINESS_POLICY_SCHEMA:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness policy schema is unsupported"
            )
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskMergeReadinessEvaluationError("policy repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskMergeReadinessEvaluationError("policy repository_id is invalid")
        if (
            isinstance(self.minimum_exact_head_approved_reviews, bool)
            or not isinstance(self.minimum_exact_head_approved_reviews, int)
            or not 1 <= self.minimum_exact_head_approved_reviews <= 20
        ):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "policy exact-head approval threshold is invalid"
            )
        if self.required_github_review_decision != "APPROVED":
            raise PilotExactTaskMergeReadinessEvaluationError(
                "policy must require GitHub APPROVED reviewDecision"
            )
        if self.require_no_exact_head_changes_requested is not True:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "policy must reject exact-head changes requested"
            )
        if self.require_no_unresolved_review_threads is not True:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "policy must reject unresolved review threads"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "minimum_exact_head_approved_reviews": self.minimum_exact_head_approved_reviews,
            "required_github_review_decision": self.required_github_review_decision,
            "require_no_exact_head_changes_requested": self.require_no_exact_head_changes_requested,
            "require_no_unresolved_review_threads": self.require_no_unresolved_review_threads,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskMergeReadinessPolicy":
        expected = {
            "repository",
            "repository_id",
            "minimum_exact_head_approved_reviews",
            "required_github_review_decision",
            "require_no_exact_head_changes_requested",
            "require_no_unresolved_review_threads",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness policy fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_policy(payload: bytes) -> PilotExactTaskMergeReadinessPolicy:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy JSON is invalid"
        ) from exc
    policy = PilotExactTaskMergeReadinessPolicy.from_mapping(raw)
    if policy.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy is not canonical JSON"
        )
    return policy


def _read_host_policy(path: Path) -> tuple[PilotExactTaskMergeReadinessPolicy, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy changed while being read"
        )
    policy = _parse_policy(second)
    return policy, hashlib.sha256(second).hexdigest()


def _require_live_review_state(
    value: Any,
) -> PilotExactTaskReviewStateAttestationReceipt:
    if type(value) is not PilotExactTaskReviewStateAttestationReceipt:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "exact live ADR-DC-057 review-state attestation is required"
        )
    try:
        replayed = PilotExactTaskReviewStateAttestationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "ADR-DC-057 review-state replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "ADR-DC-057 review-state identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_REVIEW_STATE_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.post_lifecycle_attestation_authenticated is not True
        or value.exact_pr_revalidated is not True
        or value.submitted_reviews_observed is not True
        or value.review_threads_observed is not True
        or value.double_observation_matched is not True
        or value.review_state_attested is not True
        or value.review_submission_authorized is not False
        or value.review_thread_mutation_authorized is not False
        or value.merge_readiness_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskMergeReadinessEvaluationError(
            "ADR-DC-058 requires one fresh read-only ADR-DC-057 attestation"
        )
    live = review_boundary._get_live_review_state_attestation_inputs(value)
    if live is None or live.get("review_state_sha256") != value.review_state_sha256:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "ADR-DC-057 live provenance is unavailable"
        )
    return value


def _blockers(
    source: PilotExactTaskReviewStateAttestationReceipt,
    policy: PilotExactTaskMergeReadinessPolicy,
) -> tuple[str, ...]:
    result: list[str] = []
    if source.github_review_decision != policy.required_github_review_decision:
        result.append("github-review-decision-not-approved")
    if source.exact_head_approved_review_count < policy.minimum_exact_head_approved_reviews:
        result.append("insufficient-exact-head-approvals")
    if source.exact_head_changes_requested_review_count != 0:
        result.append("exact-head-changes-requested-present")
    if source.unresolved_review_thread_count != 0:
        result.append("unresolved-review-threads-present")
    return tuple(code for code in _BLOCKER_ORDER if code in result)


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], str]] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskReviewStateAttestationReceipt,
        policy_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            policy_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, policy_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.attestation_authenticated is not True
            or source.sha256 != receipt.review_state_attestation_sha256
            or receipt.merge_readiness_policy_sha256 != policy_sha
        ):
            return None
        return MappingProxyType(
            {
                "review_state_attestation": source,
                "merge_readiness_policy_sha256": policy_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_merge_readiness_evaluation_authenticated, _get_live_merge_readiness_evaluation_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskMergeReadinessEvaluationReceipt:
    review_state_attestation_sha256: str
    post_lifecycle_attestation_sha256: str
    review_state_sha256: str
    reviews_sha256: str
    review_threads_sha256: str
    merge_readiness_policy_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    github_review_decision: str
    exact_head_approved_review_count: int
    exact_head_changes_requested_review_count: int
    unresolved_review_thread_count: int
    unresolved_outdated_review_thread_count: int
    minimum_exact_head_approved_reviews: int
    required_github_review_decision: str
    blocker_codes: tuple[str, ...]
    review_state_observed_at_utc: str
    evaluated_at_utc: str
    review_state_attestation_authenticated: bool = True
    merge_readiness_policy_host_pinned: bool = True
    github_review_decision_satisfied: bool = False
    exact_head_approval_threshold_satisfied: bool = False
    no_exact_head_changes_requested: bool = False
    no_unresolved_review_threads: bool = False
    merge_readiness_evaluated: bool = True
    merge_ready: bool = False
    merge_readiness_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    pr_mutation_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    evaluation_scope: str = PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCOPE
    authority: str = PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_AUTHORITY
            or self.evaluation_scope != PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCOPE
        ):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness evaluation identity is unsupported"
            )
        for name in (
            "review_state_attestation_sha256",
            "post_lifecycle_attestation_sha256",
            "review_state_sha256",
            "reviews_sha256",
            "review_threads_sha256",
            "merge_readiness_policy_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.exact_task_base_sha, name="exact_task_base_sha")
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness pull-request identity is invalid"
            )
        counts = (
            self.exact_head_approved_review_count,
            self.exact_head_changes_requested_review_count,
            self.unresolved_review_thread_count,
            self.unresolved_outdated_review_thread_count,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness review counts are invalid"
            )
        if self.unresolved_outdated_review_thread_count > self.unresolved_review_thread_count:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "unresolved outdated review count is inconsistent"
            )
        if (
            isinstance(self.minimum_exact_head_approved_reviews, bool)
            or not isinstance(self.minimum_exact_head_approved_reviews, int)
            or not 1 <= self.minimum_exact_head_approved_reviews <= 20
            or self.required_github_review_decision != "APPROVED"
        ):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness policy projection is invalid"
            )
        expected_blockers: list[str] = []
        criteria = (
            self.github_review_decision_satisfied,
            self.exact_head_approval_threshold_satisfied,
            self.no_exact_head_changes_requested,
            self.no_unresolved_review_threads,
        )
        if any(not isinstance(value, bool) for value in criteria):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness criteria flags are invalid"
            )
        if self.github_review_decision_satisfied != (self.github_review_decision == "APPROVED"):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "GitHub review-decision criterion is inconsistent"
            )
        if self.exact_head_approval_threshold_satisfied != (
            self.exact_head_approved_review_count >= self.minimum_exact_head_approved_reviews
        ):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "exact-head approval criterion is inconsistent"
            )
        if self.no_exact_head_changes_requested != (self.exact_head_changes_requested_review_count == 0):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "exact-head changes-requested criterion is inconsistent"
            )
        if self.no_unresolved_review_threads != (self.unresolved_review_thread_count == 0):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "unresolved-thread criterion is inconsistent"
            )
        if not self.github_review_decision_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[0])
        if not self.exact_head_approval_threshold_satisfied:
            expected_blockers.append(_BLOCKER_ORDER[1])
        if not self.no_exact_head_changes_requested:
            expected_blockers.append(_BLOCKER_ORDER[2])
        if not self.no_unresolved_review_threads:
            expected_blockers.append(_BLOCKER_ORDER[3])
        if tuple(expected_blockers) != self.blocker_codes:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness blocker set is inconsistent"
            )
        if self.merge_ready != all(criteria) or self.merge_ready != (not self.blocker_codes):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge_ready does not equal evaluated criteria"
            )
        source_time = _utc(self.review_state_observed_at_utc, name="review_state_observed_at_utc")
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if evaluated < source_time:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness evaluation predates review-state attestation"
            )
        if self.review_state_attestation_authenticated is not True or self.merge_readiness_policy_host_pinned is not True or self.merge_readiness_evaluated is not True:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness evaluation evidence is incomplete"
            )
        forced_false = (
            "merge_readiness_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "pr_mutation_authorized",
            "remote_write_authorized",
            "push_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness evaluation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def evaluation_authenticated(self) -> bool:
        return _get_live_merge_readiness_evaluation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["blocker_codes"] = list(self.blocker_codes)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskMergeReadinessEvaluationReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness evaluation fields mismatch"
            )
        blockers = value.get("blocker_codes")
        if not isinstance(blockers, list):
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness blocker codes must be an array"
            )
        data = dict(value)
        data["blocker_codes"] = tuple(blockers)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_merge_readiness(
    *,
    review_state_attestation: PilotExactTaskReviewStateAttestationReceipt,
    policy: PilotExactTaskMergeReadinessPolicy,
    policy_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskMergeReadinessEvaluationReceipt:
    source = _require_live_review_state(review_state_attestation)
    if type(policy) is not PilotExactTaskMergeReadinessPolicy:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "exact host merge-readiness policy is required"
        )
    supplied_policy_sha = _hex64(policy_sha256, name="merge_readiness_policy_sha256")
    if policy.sha256 != supplied_policy_sha:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy digest mismatch"
        )
    if policy.repository != source.repository or policy.repository_id != source.repository_id:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy is not bound to exact repository"
        )
    blockers = _blockers(source, policy)
    github_ok = source.github_review_decision == policy.required_github_review_decision
    approvals_ok = (
        source.exact_head_approved_review_count >= policy.minimum_exact_head_approved_reviews
    )
    changes_ok = source.exact_head_changes_requested_review_count == 0
    threads_ok = source.unresolved_review_thread_count == 0
    evaluated_at = now_provider()
    if _utc(evaluated_at, name="evaluated_at_utc") < _utc(
        source.observed_at_utc, name="review_state_observed_at_utc"
    ):
        raise PilotExactTaskMergeReadinessEvaluationError(
            "system clock moved backwards after ADR-DC-057"
        )
    receipt = PilotExactTaskMergeReadinessEvaluationReceipt(
        review_state_attestation_sha256=source.sha256,
        post_lifecycle_attestation_sha256=source.post_lifecycle_attestation_sha256,
        review_state_sha256=source.review_state_sha256,
        reviews_sha256=source.reviews_sha256,
        review_threads_sha256=source.review_threads_sha256,
        merge_readiness_policy_sha256=supplied_policy_sha,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        base_branch=source.base_branch,
        head_branch=source.head_branch,
        exact_task_base_sha=source.exact_task_base_sha,
        predicted_commit_sha=source.predicted_commit_sha,
        pull_request_number=source.pull_request_number,
        pull_request_api_url=source.pull_request_api_url,
        pull_request_node_id_sha256=source.pull_request_node_id_sha256,
        github_review_decision=source.github_review_decision,
        exact_head_approved_review_count=source.exact_head_approved_review_count,
        exact_head_changes_requested_review_count=(
            source.exact_head_changes_requested_review_count
        ),
        unresolved_review_thread_count=source.unresolved_review_thread_count,
        unresolved_outdated_review_thread_count=(
            source.unresolved_outdated_review_thread_count
        ),
        minimum_exact_head_approved_reviews=policy.minimum_exact_head_approved_reviews,
        required_github_review_decision=policy.required_github_review_decision,
        blocker_codes=blockers,
        review_state_observed_at_utc=source.observed_at_utc,
        evaluated_at_utc=evaluated_at,
        github_review_decision_satisfied=github_ok,
        exact_head_approval_threshold_satisfied=approvals_ok,
        no_exact_head_changes_requested=changes_ok,
        no_unresolved_review_threads=threads_ok,
        merge_ready=not blockers,
    )
    _mark_merge_readiness_evaluation_authenticated(
        receipt,
        source=source,
        policy_sha256=supplied_policy_sha,
    )
    if receipt.evaluation_authenticated is not True:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness evaluation lost live provenance"
        )
    return receipt


def _canonical_policy() -> tuple[PilotExactTaskMergeReadinessPolicy, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_POLICY
        elif os.name == "nt":
            path = _WINDOWS_POLICY
        else:
            raise PilotExactTaskMergeReadinessEvaluationError(
                "merge-readiness policy platform is unsupported"
            )
        return _read_host_policy(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "merge-readiness policy requires an elevated host operator"
        ) from exc


def evaluate_pilot_exact_task_merge_readiness(
    review_state_attestation: PilotExactTaskReviewStateAttestationReceipt,
) -> PilotExactTaskMergeReadinessEvaluationReceipt:
    """Evaluate exact review-state evidence under the fixed host merge policy."""
    try:
        policy, digest = _canonical_policy()
        return _evaluate_verified_pilot_exact_task_merge_readiness(
            review_state_attestation=review_state_attestation,
            policy=policy,
            policy_sha256=digest,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskMergeReadinessEvaluationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskMergeReadinessEvaluationError(
            "exact merge-readiness evaluation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCHEMA",
    "PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_AUTHORITY",
    "PILOT_EXACT_TASK_MERGE_READINESS_EVALUATION_SCOPE",
    "PILOT_EXACT_TASK_MERGE_READINESS_POLICY_SCHEMA",
    "PilotExactTaskMergeReadinessEvaluationError",
    "PilotExactTaskMergeReadinessPolicy",
    "PilotExactTaskMergeReadinessEvaluationReceipt",
    "evaluate_pilot_exact_task_merge_readiness",
]
