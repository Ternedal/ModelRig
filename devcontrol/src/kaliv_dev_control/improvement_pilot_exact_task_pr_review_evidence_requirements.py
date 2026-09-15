"""ADR-DC-092 exact review-evidence requirements planning.

Consumes one live authenticated ADR-DC-091 review-policy receipt and derives the
minimum additional read-only evidence surfaces needed before that policy can be
evaluated safely. This boundary performs no GitHub/network read, does not infer
approval from GraphQL ``reviewDecision``, and grants no mutation or merge
authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_pr_review_policy as policy_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation_boundary
from .improvement_pilot_exact_task_pr_review_policy import PilotExactTaskPrReviewPolicy
from .improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation import (
    PilotExactTaskPrStrictSyncedReviewThreadStateObservation,
)

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-review-evidence-requirements/v1"
AUTHORITY = "planned-one-dc-l16-exact-pr-review-evidence-requirements-only"
_REPOSITORY = "Ternedal/ModelRig"
_HEX40 = frozenset("0123456789abcdef")
_HEX64 = _HEX40


class PilotExactTaskPrReviewEvidenceRequirementsError(ValueError):
    pass


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewEvidenceRequirementsError("review-evidence requirements are not canonical JSON") from exc


def _require_hex(value: Any, *, length: int, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(ch not in _HEX64 for ch in value)
        or value == "0" * length
    ):
        raise PilotExactTaskPrReviewEvidenceRequirementsError(f"{name} invalid")
    return value


def _requirements_from_policy(value: Any) -> Mapping[str, Any]:
    result = getattr(value, "synthesis_result", None)
    if result not in {"SUPPORTED", "UNSUPPORTED"}:
        raise PilotExactTaskPrReviewEvidenceRequirementsError("review-policy synthesis result invalid")

    count = getattr(value, "effective_required_approving_review_count", None)
    dismiss = getattr(value, "effective_dismiss_stale_reviews", None)
    codeowners = getattr(value, "effective_require_code_owner_reviews", None)
    last_push = getattr(value, "effective_require_last_push_approval", None)
    conversations = getattr(value, "effective_required_conversation_resolution", None)
    if (
        isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 10
        or any(not isinstance(item, bool) for item in (dismiss, codeowners, last_push, conversations))
    ):
        raise PilotExactTaskPrReviewEvidenceRequirementsError("effective review-policy fields invalid")

    if result == "UNSUPPORTED":
        return MappingProxyType({
            "requirements_result": "UNSUPPORTED",
            "exact_head_submitted_review_inventory_required": True,
            "approval_count_evidence_required": True,
            "stale_review_freshness_evidence_required": True,
            "code_owner_change_set_evidence_required": True,
            "code_owner_identity_evidence_required": True,
            "latest_push_actor_evidence_required": True,
            "conversation_resolution_evidence_required": True,
            "exact_head_commit_binding_required": True,
            "reviewer_identity_binding_required": True,
            "manual_or_new_policy_parser_required": True,
        })

    submitted = bool(count > 0 or dismiss or codeowners or last_push)
    return MappingProxyType({
        "requirements_result": "SUPPORTED",
        "exact_head_submitted_review_inventory_required": submitted,
        "approval_count_evidence_required": count > 0,
        "stale_review_freshness_evidence_required": bool(dismiss),
        "code_owner_change_set_evidence_required": bool(codeowners),
        "code_owner_identity_evidence_required": bool(codeowners),
        "latest_push_actor_evidence_required": bool(last_push),
        "conversation_resolution_evidence_required": bool(conversations),
        "exact_head_commit_binding_required": submitted,
        "reviewer_identity_binding_required": submitted,
        "manual_or_new_policy_parser_required": False,
    })


def _require_live_policy(value: Any) -> tuple[PilotExactTaskPrReviewPolicy, PilotExactTaskPrStrictSyncedReviewThreadStateObservation, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskPrReviewPolicy:
        raise PilotExactTaskPrReviewEvidenceRequirementsError("live ADR-DC-091 review policy required")
    try:
        replay = PilotExactTaskPrReviewPolicy.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewEvidenceRequirementsError("ADR-DC-091 replay validation failed") from exc
    live = policy_boundary._get_live_pr_review_policy_inputs(value)
    observation = None if live is None else live.get("review_thread_state_observation")
    effective_policy = None if live is None else live.get("effective_review_policy")
    if (
        replay != value or replay.sha256 != value.sha256 or value.policy_authenticated is not True
        or live is None or type(observation) is not PilotExactTaskPrStrictSyncedReviewThreadStateObservation
        or observation.observation_authenticated is not True
        or observation_boundary._get_live_pr_strict_synced_review_thread_state_observation_inputs(observation) is None
        or not isinstance(effective_policy, Mapping)
        or value.review_thread_state_observation_sha256 != observation.sha256
        or value.repository != _REPOSITORY or observation.repository != value.repository
        or observation.pull_request_number != value.pull_request_number
        or observation.predicted_commit_sha != value.predicted_commit_sha
        or observation.strict_base_tip_sha != value.strict_base_tip_sha
        or observation.review_thread_state_observation_completed is not True
        or observation.review_thread_inventory_complete is not True
        or observation.stable_double_observation_verified is not True
        or value.review_policy_synthesis_completed is not True
        or value.review_policy_evaluation_required is not True
        or value.branch_policy_fully_evaluated is not False
        or value.merge_readiness_authorized is not False
        or value.merge_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrReviewEvidenceRequirementsError("ADR-DC-092 source provenance invalid")
    canonical_policy = {
        "required_approving_review_count": value.effective_required_approving_review_count,
        "dismiss_stale_reviews": value.effective_dismiss_stale_reviews,
        "require_code_owner_reviews": value.effective_require_code_owner_reviews,
        "require_last_push_approval": value.effective_require_last_push_approval,
        "required_conversation_resolution": value.effective_required_conversation_resolution,
    }
    if (
        dict(effective_policy) != canonical_policy
        or hashlib.sha256(_canonical(canonical_policy).encode("utf-8")).hexdigest() != value.effective_review_policy_sha256
    ):
        raise PilotExactTaskPrReviewEvidenceRequirementsError("effective ADR-DC-091 policy digest drifted")
    return value, observation, MappingProxyType(canonical_policy)


_live: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], Mapping[str, Any]]] = {}


def _get_live_pr_review_evidence_requirements_inputs(value: Any) -> Mapping[str, Any] | None:
    row = _live.get(id(value))
    if row is None:
        return None
    pid, digest, ref, policy_ref, requirements = row
    policy = policy_ref()
    if (
        pid != os.getpid() or ref() is not value or policy is None
        or policy.policy_authenticated is not True
        or policy.sha256 != value.review_policy_sha256
        or value.sha256 != digest
        or hashlib.sha256(_canonical(dict(requirements)).encode("utf-8")).hexdigest() != value.evidence_requirements_sha256
    ):
        return None
    policy_live = policy_boundary._get_live_pr_review_policy_inputs(policy)
    observation = None if policy_live is None else policy_live.get("review_thread_state_observation")
    if observation is None or observation.observation_authenticated is not True:
        return None
    return MappingProxyType({
        "review_policy": policy,
        "review_thread_state_observation": observation,
        "evidence_requirements": requirements,
    })


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewEvidenceRequirements:
    review_policy_sha256: str
    review_thread_state_observation_sha256: str
    review_thread_read_capability_sha256: str
    strict_base_sync_preflight_sha256: str
    ruleset_applicability_sha256: str
    ruleset_observation_sha256: str
    branch_protection_observation_sha256: str
    effective_review_policy_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    strict_base_tip_sha: str
    review_threads_inventory_sha256: str
    github_review_decision: str
    observed_review_thread_count: int
    observed_unresolved_review_thread_count: int
    policy_required_approving_review_count: int
    policy_dismiss_stale_reviews: bool
    policy_require_code_owner_reviews: bool
    policy_require_last_push_approval: bool
    policy_required_conversation_resolution: bool
    policy_synthesis_result: str
    requirements_result: str
    evidence_requirements_sha256: str
    exact_head_submitted_review_inventory_required: bool
    approval_count_evidence_required: bool
    stale_review_freshness_evidence_required: bool
    code_owner_change_set_evidence_required: bool
    code_owner_identity_evidence_required: bool
    latest_push_actor_evidence_required: bool
    conversation_resolution_evidence_required: bool
    conversation_resolution_evidence_available: bool
    exact_head_commit_binding_required: bool
    reviewer_identity_binding_required: bool
    graphql_review_decision_summary_only: bool = True
    graphql_review_decision_sufficient_for_pass: bool = False
    manual_or_new_policy_parser_required: bool = False
    source_review_policy_verified: bool = True
    source_review_thread_observation_verified: bool = True
    requirements_derivation_completed: bool = True
    review_evidence_evaluation_required: bool = True
    granular_submitted_review_observation_may_be_required: bool = True
    merge_method_policy_still_required: bool = True
    fresh_required_status_reobservation_before_merge_required: bool = True
    fresh_review_reobservation_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    branch_policy_fully_evaluated: bool = False
    review_thread_policy_evaluated: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY:
            raise PilotExactTaskPrReviewEvidenceRequirementsError("requirements schema/authority invalid")
        if self.policy_synthesis_result not in {"SUPPORTED", "UNSUPPORTED"} or self.requirements_result not in {"SUPPORTED", "UNSUPPORTED"}:
            raise PilotExactTaskPrReviewEvidenceRequirementsError("requirements result invalid")
        for name in (
            "review_policy_sha256", "review_thread_state_observation_sha256", "review_thread_read_capability_sha256",
            "strict_base_sync_preflight_sha256", "ruleset_applicability_sha256", "ruleset_observation_sha256",
            "branch_protection_observation_sha256", "effective_review_policy_sha256",
            "review_threads_inventory_sha256", "evidence_requirements_sha256",
        ):
            _require_hex(getattr(self, name), length=64, name=name)
        for name in ("predicted_commit_sha", "strict_base_tip_sha"):
            _require_hex(getattr(self, name), length=40, name=name)
        if self.repository != _REPOSITORY or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1:
            raise PilotExactTaskPrReviewEvidenceRequirementsError("requirements target invalid")
        for name, maximum in (
            ("observed_review_thread_count", 1000),
            ("observed_unresolved_review_thread_count", 1000),
            ("policy_required_approving_review_count", 10),
        ):
            item = getattr(self, name)
            if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= maximum:
                raise PilotExactTaskPrReviewEvidenceRequirementsError(f"{name} invalid")
        if self.observed_unresolved_review_thread_count > self.observed_review_thread_count:
            raise PilotExactTaskPrReviewEvidenceRequirementsError("unresolved thread count exceeds total")
        bool_fields = (
            "policy_dismiss_stale_reviews", "policy_require_code_owner_reviews", "policy_require_last_push_approval",
            "policy_required_conversation_resolution", "exact_head_submitted_review_inventory_required",
            "approval_count_evidence_required", "stale_review_freshness_evidence_required",
            "code_owner_change_set_evidence_required", "code_owner_identity_evidence_required",
            "latest_push_actor_evidence_required", "conversation_resolution_evidence_required",
            "conversation_resolution_evidence_available", "exact_head_commit_binding_required",
            "reviewer_identity_binding_required", "graphql_review_decision_summary_only",
            "graphql_review_decision_sufficient_for_pass", "manual_or_new_policy_parser_required",
            "source_review_policy_verified", "source_review_thread_observation_verified",
            "requirements_derivation_completed", "review_evidence_evaluation_required",
            "granular_submitted_review_observation_may_be_required", "merge_method_policy_still_required",
            "fresh_required_status_reobservation_before_merge_required", "fresh_review_reobservation_required",
            "fresh_merge_transaction_revalidation_required", "branch_policy_fully_evaluated",
            "review_thread_policy_evaluated", "review_submission_authorized", "review_thread_mutation_authorized",
            "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized",
            "production_activation_authorized",
        )
        if any(type(getattr(self, name)) is not bool for name in bool_fields):
            raise PilotExactTaskPrReviewEvidenceRequirementsError("requirements booleans must be exact bools")
        required_true = (
            "source_review_policy_verified", "source_review_thread_observation_verified",
            "requirements_derivation_completed", "review_evidence_evaluation_required",
            "granular_submitted_review_observation_may_be_required", "merge_method_policy_still_required",
            "fresh_required_status_reobservation_before_merge_required", "fresh_review_reobservation_required",
            "fresh_merge_transaction_revalidation_required", "graphql_review_decision_summary_only",
            "conversation_resolution_evidence_available",
        )
        required_false = (
            "graphql_review_decision_sufficient_for_pass", "branch_policy_fully_evaluated",
            "review_thread_policy_evaluated", "review_submission_authorized", "review_thread_mutation_authorized",
            "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true) or any(getattr(self, name) is not False for name in required_false):
            raise PilotExactTaskPrReviewEvidenceRequirementsError("requirements widened authority or weakened evidence gates")
        if self.policy_synthesis_result != self.requirements_result:
            raise PilotExactTaskPrReviewEvidenceRequirementsError("requirements result must follow policy support")
        effective_policy = {
            "required_approving_review_count": self.policy_required_approving_review_count,
            "dismiss_stale_reviews": self.policy_dismiss_stale_reviews,
            "require_code_owner_reviews": self.policy_require_code_owner_reviews,
            "require_last_push_approval": self.policy_require_last_push_approval,
            "required_conversation_resolution": self.policy_required_conversation_resolution,
        }
        if hashlib.sha256(_canonical(effective_policy).encode("utf-8")).hexdigest() != self.effective_review_policy_sha256:
            raise PilotExactTaskPrReviewEvidenceRequirementsError("effective review policy digest mismatch")
        plan = {
            "requirements_result": self.requirements_result,
            "exact_head_submitted_review_inventory_required": self.exact_head_submitted_review_inventory_required,
            "approval_count_evidence_required": self.approval_count_evidence_required,
            "stale_review_freshness_evidence_required": self.stale_review_freshness_evidence_required,
            "code_owner_change_set_evidence_required": self.code_owner_change_set_evidence_required,
            "code_owner_identity_evidence_required": self.code_owner_identity_evidence_required,
            "latest_push_actor_evidence_required": self.latest_push_actor_evidence_required,
            "conversation_resolution_evidence_required": self.conversation_resolution_evidence_required,
            "exact_head_commit_binding_required": self.exact_head_commit_binding_required,
            "reviewer_identity_binding_required": self.reviewer_identity_binding_required,
            "manual_or_new_policy_parser_required": self.manual_or_new_policy_parser_required,
        }
        if hashlib.sha256(_canonical(plan).encode("utf-8")).hexdigest() != self.evidence_requirements_sha256:
            raise PilotExactTaskPrReviewEvidenceRequirementsError("evidence requirements digest mismatch")
        submitted_expected = bool(
            self.policy_required_approving_review_count > 0
            or self.policy_dismiss_stale_reviews
            or self.policy_require_code_owner_reviews
            or self.policy_require_last_push_approval
        )
        if self.requirements_result == "SUPPORTED":
            if (
                self.manual_or_new_policy_parser_required is not False
                or self.exact_head_submitted_review_inventory_required is not submitted_expected
                or self.approval_count_evidence_required is not (self.policy_required_approving_review_count > 0)
                or self.stale_review_freshness_evidence_required is not self.policy_dismiss_stale_reviews
                or self.code_owner_change_set_evidence_required is not self.policy_require_code_owner_reviews
                or self.code_owner_identity_evidence_required is not self.policy_require_code_owner_reviews
                or self.latest_push_actor_evidence_required is not self.policy_require_last_push_approval
                or self.conversation_resolution_evidence_required is not self.policy_required_conversation_resolution
                or self.exact_head_commit_binding_required is not submitted_expected
                or self.reviewer_identity_binding_required is not submitted_expected
            ):
                raise PilotExactTaskPrReviewEvidenceRequirementsError("supported evidence plan does not match policy")
        elif not all((
            self.exact_head_submitted_review_inventory_required,
            self.approval_count_evidence_required,
            self.stale_review_freshness_evidence_required,
            self.code_owner_change_set_evidence_required,
            self.code_owner_identity_evidence_required,
            self.latest_push_actor_evidence_required,
            self.conversation_resolution_evidence_required,
            self.exact_head_commit_binding_required,
            self.reviewer_identity_binding_required,
            self.manual_or_new_policy_parser_required,
        )):
            raise PilotExactTaskPrReviewEvidenceRequirementsError("unsupported policy must fail closed on all review evidence")

    @property
    def requirements_authenticated(self) -> bool:
        return _get_live_pr_review_evidence_requirements_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewEvidenceRequirements":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrReviewEvidenceRequirementsError("requirements fields mismatch")
        return cls(**dict(value))


def plan_pilot_exact_task_pr_review_evidence_requirements(
    review_policy: PilotExactTaskPrReviewPolicy,
) -> PilotExactTaskPrReviewEvidenceRequirements:
    checked, observation, _effective_policy = _require_live_policy(review_policy)
    requirements = _requirements_from_policy(checked)
    serialized_requirements = dict(requirements)
    requirements_sha = hashlib.sha256(_canonical(serialized_requirements).encode("utf-8")).hexdigest()
    result = PilotExactTaskPrReviewEvidenceRequirements(
        checked.sha256,
        checked.review_thread_state_observation_sha256,
        checked.review_thread_read_capability_sha256,
        checked.strict_base_sync_preflight_sha256,
        checked.ruleset_applicability_sha256,
        checked.ruleset_observation_sha256,
        checked.branch_protection_observation_sha256,
        checked.effective_review_policy_sha256,
        checked.repository,
        checked.pull_request_number,
        checked.predicted_commit_sha,
        checked.strict_base_tip_sha,
        observation.review_threads_inventory_sha256,
        observation.github_review_decision,
        observation.review_thread_count,
        observation.unresolved_review_thread_count,
        checked.effective_required_approving_review_count,
        checked.effective_dismiss_stale_reviews,
        checked.effective_require_code_owner_reviews,
        checked.effective_require_last_push_approval,
        checked.effective_required_conversation_resolution,
        checked.synthesis_result,
        str(requirements["requirements_result"]),
        requirements_sha,
        bool(requirements["exact_head_submitted_review_inventory_required"]),
        bool(requirements["approval_count_evidence_required"]),
        bool(requirements["stale_review_freshness_evidence_required"]),
        bool(requirements["code_owner_change_set_evidence_required"]),
        bool(requirements["code_owner_identity_evidence_required"]),
        bool(requirements["latest_push_actor_evidence_required"]),
        bool(requirements["conversation_resolution_evidence_required"]),
        observation.review_thread_inventory_complete is True and observation.stable_double_observation_verified is True,
        bool(requirements["exact_head_commit_binding_required"]),
        bool(requirements["reviewer_identity_binding_required"]),
        manual_or_new_policy_parser_required=bool(requirements["manual_or_new_policy_parser_required"]),
    )
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live.pop(key, None)
    _live[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(checked), MappingProxyType(serialized_requirements))
    if result.requirements_authenticated is not True:
        raise PilotExactTaskPrReviewEvidenceRequirementsError("review-evidence requirements lost live provenance")
    return result


__all__ = [
    "SCHEMA", "AUTHORITY", "PilotExactTaskPrReviewEvidenceRequirementsError",
    "PilotExactTaskPrReviewEvidenceRequirements", "plan_pilot_exact_task_pr_review_evidence_requirements",
]
