"""ADR-DC-091 synthesize exact review policy from live legacy/ruleset provenance."""
from __future__ import annotations

import hashlib
import json
import os
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync_boundary
from . import improvement_pilot_exact_task_pr_ruleset_applicability as applicability_boundary
from . import improvement_pilot_exact_task_pr_ruleset_observation as ruleset_boundary
from .improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation import (
    PilotExactTaskPrStrictSyncedReviewThreadStateObservation,
)

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-review-policy/v1"
AUTHORITY = "synthesized-one-dc-l16-exact-pr-review-policy-only"
_REPOSITORY = "Ternedal/ModelRig"
_ALLOWED_MERGE_METHODS = frozenset({"merge", "squash", "rebase"})
_CORE_PULL_REQUEST_KEYS = {
    "required_approving_review_count",
    "dismiss_stale_reviews_on_push",
    "require_code_owner_review",
    "require_last_push_approval",
    "required_review_thread_resolution",
}
_OPTIONAL_PULL_REQUEST_KEYS = {"allowed_merge_methods", "dismissal_restriction", "required_reviewers"}


class PilotExactTaskPrReviewPolicyError(ValueError):
    pass


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewPolicyError("review policy is not canonical JSON") from exc


def _parse_pull_request_rule(rule: Any) -> Mapping[str, Any] | None:
    if not isinstance(rule, Mapping) or set(rule) != {"type", "parameters"} or rule.get("type") != "pull_request":
        return None
    params = rule.get("parameters")
    if not isinstance(params, Mapping):
        return MappingProxyType({"supported": False, "reason": "parameters"})
    keys = set(params)
    if not _CORE_PULL_REQUEST_KEYS.issubset(keys) or keys - (_CORE_PULL_REQUEST_KEYS | _OPTIONAL_PULL_REQUEST_KEYS):
        return MappingProxyType({"supported": False, "reason": "shape"})
    count = params.get("required_approving_review_count")
    booleans = (
        params.get("dismiss_stale_reviews_on_push"),
        params.get("require_code_owner_review"),
        params.get("require_last_push_approval"),
        params.get("required_review_thread_resolution"),
    )
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 10 or any(not isinstance(v, bool) for v in booleans):
        return MappingProxyType({"supported": False, "reason": "core-values"})
    methods = params.get("allowed_merge_methods")
    if methods is not None:
        if (
            not isinstance(methods, list) or not methods
            or any(not isinstance(v, str) or v not in _ALLOWED_MERGE_METHODS for v in methods)
            or len(set(methods)) != len(methods)
        ):
            return MappingProxyType({"supported": False, "reason": "merge-methods"})
    restriction = params.get("dismissal_restriction")
    if restriction not in (None, {}, []):
        return MappingProxyType({"supported": False, "reason": "dismissal-restriction"})
    required_reviewers = params.get("required_reviewers")
    if required_reviewers not in (None, []):
        return MappingProxyType({"supported": False, "reason": "required-reviewers"})
    return MappingProxyType({
        "supported": True,
        "required_approving_review_count": count,
        "dismiss_stale_reviews": bool(params["dismiss_stale_reviews_on_push"]),
        "require_code_owner_reviews": bool(params["require_code_owner_review"]),
        "require_last_push_approval": bool(params["require_last_push_approval"]),
        "required_conversation_resolution": bool(params["required_review_thread_resolution"]),
        "merge_method_policy_present": methods is not None,
    })


def _require_live_sources(value: Any) -> Mapping[str, Any]:
    if type(value) is not PilotExactTaskPrStrictSyncedReviewThreadStateObservation:
        raise PilotExactTaskPrReviewPolicyError("live ADR-DC-090 observation required")
    replay = PilotExactTaskPrStrictSyncedReviewThreadStateObservation.from_mapping(value.to_dict())
    observed_live = observation_boundary._get_live_pr_strict_synced_review_thread_state_observation_inputs(value)
    capability = None if observed_live is None else observed_live.get("review_thread_read_capability")
    cap_live = None if capability is None else capability_boundary._get_live_pr_strict_synced_review_thread_read_capability_inputs(capability)
    strict = None if cap_live is None else cap_live.get("strict_base_sync_preflight")
    strict_live = None if strict is None else sync_boundary._get_live_pr_strict_base_sync_preflight_inputs(strict)
    app = None if strict_live is None else strict_live.get("ruleset_applicability")
    app_live = None if app is None else applicability_boundary._get_live_pr_ruleset_applicability_inputs(app)
    ruleset_observation = None if app_live is None else app_live.get("ruleset_observation")
    ruleset_live = None if ruleset_observation is None else ruleset_boundary._get_live_pr_ruleset_observation_inputs(ruleset_observation)
    branch = None if ruleset_live is None else ruleset_live.get("branch_protection_observation")
    rulesets = () if ruleset_live is None else tuple(ruleset_live.get("rulesets", ()))
    if (
        replay != value or replay.sha256 != value.sha256 or value.observation_authenticated is not True
        or capability is None or capability.capability_authenticated is not True
        or strict is None or strict.preflight_authenticated is not True
        or app is None or app.applicability_authenticated is not True or app.applicability_result != "SUPPORTED"
        or app.unsupported_active_ruleset_count != 0
        or ruleset_observation is None or ruleset_observation.observation_authenticated is not True
        or branch is None or branch.observation_authenticated is not True
        or value.review_thread_read_capability_sha256 != capability.sha256
        or value.strict_base_sync_preflight_sha256 != strict.sha256
        or value.ruleset_applicability_sha256 != app.sha256
        or value.ruleset_observation_sha256 != ruleset_observation.sha256
        or value.repository != _REPOSITORY
        or value.repository != branch.repository or value.pull_request_number != branch.pull_request_number
        or value.predicted_commit_sha != branch.predicted_commit_sha
        or value.source_status_checks_passed is not True or value.source_strict_base_sync_passed is not True
        or value.review_thread_state_observation_completed is not True
        or value.review_thread_policy_evaluation_required is not True
        or value.merge_authorized is not False
    ):
        raise PilotExactTaskPrReviewPolicyError("ADR-DC-091 source provenance invalid")
    return MappingProxyType({
        "observation": value, "capability": capability, "strict": strict, "ruleset_applicability": app,
        "ruleset_observation": ruleset_observation, "branch_protection_observation": branch,
        "rulesets": rulesets,
    })


def _synthesize(source: Mapping[str, Any]) -> Mapping[str, Any]:
    branch = source["branch_protection_observation"]
    app = source["ruleset_applicability"]
    rulesets = source["rulesets"]
    required_count = int(branch.required_approving_review_count) if branch.required_pull_request_reviews_present else 0
    dismiss_stale = bool(branch.dismiss_stale_reviews) if branch.required_pull_request_reviews_present else False
    codeowners = bool(branch.require_code_owner_reviews) if branch.required_pull_request_reviews_present else False
    last_push = bool(branch.require_last_push_approval) if branch.required_pull_request_reviews_present else False
    conversations = bool(branch.required_conversation_resolution_enabled)
    applicable_pull_request_rules = 0
    unsupported = 0
    merge_method_policy_present = False
    for detail in rulesets:
        if str(detail.get("enforcement", "")).lower() != "active":
            continue
        applies = applicability_boundary._applies(detail)
        if applies is not True:
            continue
        rules = detail.get("rules")
        if not isinstance(rules, list):
            raise PilotExactTaskPrReviewPolicyError("applicable ruleset rules unavailable")
        for rule in rules:
            if not isinstance(rule, Mapping) or rule.get("type") != "pull_request":
                continue
            applicable_pull_request_rules += 1
            parsed = _parse_pull_request_rule(rule)
            if parsed is None or parsed.get("supported") is not True:
                unsupported += 1
                continue
            required_count = max(required_count, int(parsed["required_approving_review_count"]))
            dismiss_stale = dismiss_stale or bool(parsed["dismiss_stale_reviews"])
            codeowners = codeowners or bool(parsed["require_code_owner_reviews"])
            last_push = last_push or bool(parsed["require_last_push_approval"])
            conversations = conversations or bool(parsed["required_conversation_resolution"])
            merge_method_policy_present = merge_method_policy_present or bool(parsed["merge_method_policy_present"])
    policy = {
        "required_approving_review_count": required_count,
        "dismiss_stale_reviews": dismiss_stale,
        "require_code_owner_reviews": codeowners,
        "require_last_push_approval": last_push,
        "required_conversation_resolution": conversations,
    }
    return MappingProxyType({
        "synthesis_result": "UNSUPPORTED" if unsupported else "SUPPORTED",
        "policy": MappingProxyType(policy),
        "applicable_pull_request_rule_count": applicable_pull_request_rules,
        "unsupported_pull_request_rule_count": unsupported,
        "merge_method_policy_present": merge_method_policy_present,
        "applicable_active_ruleset_count": app.applicable_active_ruleset_count,
    })


_live: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], Mapping[str, Any]]] = {}


def _get_live_pr_review_policy_inputs(value: Any) -> Mapping[str, Any] | None:
    row = _live.get(id(value))
    if row is None:
        return None
    pid, digest, ref, observation_ref, policy = row
    observation = observation_ref()
    if (
        pid != os.getpid() or ref() is not value or observation is None
        or observation.observation_authenticated is not True
        or observation.sha256 != value.review_thread_state_observation_sha256
        or value.sha256 != digest
        or hashlib.sha256(_canonical(dict(policy)).encode("utf-8")).hexdigest() != value.effective_review_policy_sha256
    ):
        return None
    return MappingProxyType({"review_thread_state_observation": observation, "effective_review_policy": policy})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewPolicy:
    review_thread_state_observation_sha256: str
    review_thread_read_capability_sha256: str
    strict_base_sync_preflight_sha256: str
    ruleset_applicability_sha256: str
    ruleset_observation_sha256: str
    branch_protection_observation_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    strict_base_tip_sha: str
    ruleset_inventory_sha256: str
    normalized_legacy_protection_sha256: str
    applicable_active_ruleset_count: int
    applicable_pull_request_rule_count: int
    unsupported_pull_request_rule_count: int
    legacy_required_pull_request_reviews_present: bool
    legacy_required_approving_review_count: int
    legacy_dismiss_stale_reviews: bool
    legacy_require_code_owner_reviews: bool
    legacy_require_last_push_approval: bool
    legacy_required_conversation_resolution: bool
    effective_required_approving_review_count: int
    effective_dismiss_stale_reviews: bool
    effective_require_code_owner_reviews: bool
    effective_require_last_push_approval: bool
    effective_required_conversation_resolution: bool
    merge_method_policy_present: bool
    effective_review_policy_sha256: str
    synthesis_result: str
    source_review_thread_observation_verified: bool = True
    source_branch_policy_sources_verified: bool = True
    most_restrictive_layering_applied: bool = True
    unsupported_review_policy_fails_closed: bool = True
    review_policy_synthesis_completed: bool = True
    review_policy_evaluation_required: bool = True
    merge_method_policy_still_required: bool = True
    fresh_required_status_reobservation_before_merge_required: bool = True
    fresh_review_reobservation_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    branch_policy_fully_evaluated: bool = False
    review_thread_policy_evaluated: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    schema: str = SCHEMA

    def __post_init__(self):
        if self.schema != SCHEMA or self.authority != AUTHORITY or self.synthesis_result not in {"SUPPORTED", "UNSUPPORTED"}:
            raise PilotExactTaskPrReviewPolicyError("review policy receipt invalid")
        for name in (
            "review_thread_state_observation_sha256", "review_thread_read_capability_sha256",
            "strict_base_sync_preflight_sha256", "ruleset_applicability_sha256", "ruleset_observation_sha256",
            "branch_protection_observation_sha256", "ruleset_inventory_sha256",
            "normalized_legacy_protection_sha256", "effective_review_policy_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value) or value == "0" * 64:
                raise PilotExactTaskPrReviewPolicyError(f"{name} invalid")
        for name in ("predicted_commit_sha", "strict_base_tip_sha"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value) or value == "0" * 40:
                raise PilotExactTaskPrReviewPolicyError(f"{name} invalid")
        if self.repository != _REPOSITORY or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1:
            raise PilotExactTaskPrReviewPolicyError("review policy target invalid")
        for name in (
            "applicable_active_ruleset_count", "applicable_pull_request_rule_count", "unsupported_pull_request_rule_count",
            "legacy_required_approving_review_count", "effective_required_approving_review_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PilotExactTaskPrReviewPolicyError(f"{name} invalid")
        if self.legacy_required_approving_review_count > 6 or self.effective_required_approving_review_count > 10:
            raise PilotExactTaskPrReviewPolicyError("approval count invalid")
        if self.synthesis_result == "SUPPORTED" and self.unsupported_pull_request_rule_count != 0:
            raise PilotExactTaskPrReviewPolicyError("supported policy contains unsupported rule")
        required_true = (
            "source_review_thread_observation_verified", "source_branch_policy_sources_verified",
            "most_restrictive_layering_applied", "unsupported_review_policy_fails_closed",
            "review_policy_synthesis_completed", "review_policy_evaluation_required",
            "merge_method_policy_still_required", "fresh_required_status_reobservation_before_merge_required",
            "fresh_review_reobservation_required", "fresh_merge_transaction_revalidation_required",
        )
        forced_false = (
            "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "merge_readiness_authorized", "merge_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true) or any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewPolicyError("review policy widened authority")

    @property
    def policy_authenticated(self) -> bool:
        return _get_live_pr_review_policy_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self):
        return _canonical(self.to_dict())

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrReviewPolicyError("fields mismatch")
        return cls(**dict(value))


def synthesize_pilot_exact_task_pr_review_policy(
    review_thread_state_observation: PilotExactTaskPrStrictSyncedReviewThreadStateObservation,
) -> PilotExactTaskPrReviewPolicy:
    source = _require_live_sources(review_thread_state_observation)
    synthesized = _synthesize(source)
    branch = source["branch_protection_observation"]
    ruleset_observation = source["ruleset_observation"]
    app = source["ruleset_applicability"]
    policy = synthesized["policy"]
    policy_sha = hashlib.sha256(_canonical(dict(policy)).encode("utf-8")).hexdigest()
    result = PilotExactTaskPrReviewPolicy(
        review_thread_state_observation.sha256,
        review_thread_state_observation.review_thread_read_capability_sha256,
        review_thread_state_observation.strict_base_sync_preflight_sha256,
        app.sha256,
        ruleset_observation.sha256,
        branch.sha256,
        review_thread_state_observation.repository,
        review_thread_state_observation.pull_request_number,
        review_thread_state_observation.predicted_commit_sha,
        review_thread_state_observation.strict_base_tip_sha,
        ruleset_observation.ruleset_inventory_sha256,
        branch.normalized_protection_sha256,
        synthesized["applicable_active_ruleset_count"],
        synthesized["applicable_pull_request_rule_count"],
        synthesized["unsupported_pull_request_rule_count"],
        branch.required_pull_request_reviews_present,
        branch.required_approving_review_count,
        branch.dismiss_stale_reviews,
        branch.require_code_owner_reviews,
        branch.require_last_push_approval,
        branch.required_conversation_resolution_enabled,
        policy["required_approving_review_count"],
        policy["dismiss_stale_reviews"],
        policy["require_code_owner_reviews"],
        policy["require_last_push_approval"],
        policy["required_conversation_resolution"],
        synthesized["merge_method_policy_present"],
        policy_sha,
        synthesized["synthesis_result"],
    )
    key = id(result)
    def cleanup(_):
        _live.pop(key, None)
    _live[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(review_thread_state_observation), policy)
    if result.policy_authenticated is not True:
        raise PilotExactTaskPrReviewPolicyError("review policy lost live provenance")
    return result


__all__ = [
    "SCHEMA", "AUTHORITY", "PilotExactTaskPrReviewPolicyError", "PilotExactTaskPrReviewPolicy",
    "synthesize_pilot_exact_task_pr_review_policy",
]
