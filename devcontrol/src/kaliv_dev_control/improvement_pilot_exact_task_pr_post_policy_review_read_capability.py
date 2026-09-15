"""ADR-DC-092 post-policy host-pinned GraphQL review read capability.

Consumes one live ADR-DC-091 review policy and re-attests the exact existing
read-only GraphQL broker after policy synthesis. This boundary does not invoke
the broker or read GitHub; it only materializes a fresh, short-lived capability
for the later reviewDecision/reviewThreads re-observation.
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
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_review_policy as policy_boundary
from .improvement_pilot_exact_task_pr_review_policy import PilotExactTaskPrReviewPolicy
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as capability_boundary
from . import _improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability_production_boundary as production_boundary

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-post-policy-review-read-capability/v1"
AUTHORITY = "host-attested-one-dc-l16-post-policy-review-graphql-read-broker-only"
MAX_SOURCE_AGE_SECONDS = 30
_REPOSITORY = "Ternedal/ModelRig"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPrPostPolicyReviewReadCapabilityError(ValueError):
    pass


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("capability evidence is not canonical JSON") from exc


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError(f"{name} invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError(f"{name} invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError(f"{name} invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError(f"{name} invalid")
    return value


def _effective_policy(value: PilotExactTaskPrReviewPolicy) -> Mapping[str, Any]:
    boolean_fields = (
        "legacy_required_pull_request_reviews_present",
        "legacy_dismiss_stale_reviews",
        "legacy_require_code_owner_reviews",
        "legacy_require_last_push_approval",
        "legacy_required_conversation_resolution",
        "effective_dismiss_stale_reviews",
        "effective_require_code_owner_reviews",
        "effective_require_last_push_approval",
        "effective_required_conversation_resolution",
        "merge_method_policy_present",
    )
    if any(not isinstance(getattr(value, name), bool) for name in boolean_fields):
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("ADR-DC-091 policy booleans invalid")
    if (
        value.synthesis_result != ("SUPPORTED" if value.unsupported_pull_request_rule_count == 0 else "UNSUPPORTED")
        or value.unsupported_pull_request_rule_count > value.applicable_pull_request_rule_count
        or value.effective_required_approving_review_count < value.legacy_required_approving_review_count
        or (value.legacy_dismiss_stale_reviews and not value.effective_dismiss_stale_reviews)
        or (value.legacy_require_code_owner_reviews and not value.effective_require_code_owner_reviews)
        or (value.legacy_require_last_push_approval and not value.effective_require_last_push_approval)
        or (value.legacy_required_conversation_resolution and not value.effective_required_conversation_resolution)
    ):
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("ADR-DC-091 effective policy invariants invalid")
    policy = {
        "required_approving_review_count": value.effective_required_approving_review_count,
        "dismiss_stale_reviews": value.effective_dismiss_stale_reviews,
        "require_code_owner_reviews": value.effective_require_code_owner_reviews,
        "require_last_push_approval": value.effective_require_last_push_approval,
        "required_conversation_resolution": value.effective_required_conversation_resolution,
    }
    digest = hashlib.sha256(_canonical(policy).encode("utf-8")).hexdigest()
    if digest != value.effective_review_policy_sha256:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("ADR-DC-091 effective policy hash mismatch")
    return MappingProxyType(policy)


def _require_live_policy(value: Any) -> Mapping[str, Any]:
    if type(value) is not PilotExactTaskPrReviewPolicy:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("live ADR-DC-091 review policy required")
    try:
        replay = PilotExactTaskPrReviewPolicy.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("ADR-DC-091 replay validation failed") from exc
    live = policy_boundary._get_live_pr_review_policy_inputs(value)
    observation = None if live is None else live.get("review_thread_state_observation")
    observed_live = (
        None if observation is None
        else observation_boundary._get_live_pr_strict_synced_review_thread_state_observation_inputs(observation)
    )
    prior_capability = None if observed_live is None else observed_live.get("review_thread_read_capability")
    prior_live = (
        None if prior_capability is None
        else capability_boundary._get_live_pr_strict_synced_review_thread_read_capability_inputs(prior_capability)
    )
    strict = None if prior_live is None else prior_live.get("strict_base_sync_preflight")
    policy = _effective_policy(value)
    if (
        replay != value
        or replay.sha256 != value.sha256
        or value.policy_authenticated is not True
        or live is None or observation is None or observation.observation_authenticated is not True
        or prior_capability is None or prior_capability.capability_authenticated is not True
        or strict is None or strict.preflight_authenticated is not True
        or value.synthesis_result != "SUPPORTED"
        or value.review_policy_synthesis_completed is not True
        or value.review_policy_evaluation_required is not True
        or value.fresh_review_reobservation_required is not True
        or value.fresh_required_status_reobservation_before_merge_required is not True
        or value.fresh_merge_transaction_revalidation_required is not True
        or value.branch_policy_fully_evaluated is not False
        or value.review_thread_policy_evaluated is not False
        or value.merge_readiness_authorized is not False
        or value.merge_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != _REPOSITORY
        or value.review_thread_state_observation_sha256 != observation.sha256
        or value.review_thread_read_capability_sha256 != prior_capability.sha256
        or value.strict_base_sync_preflight_sha256 != strict.sha256
        or value.repository != observation.repository
        or value.pull_request_number != observation.pull_request_number
        or value.predicted_commit_sha != observation.predicted_commit_sha
        or value.strict_base_tip_sha != observation.strict_base_tip_sha
        or observation.graphql_operation != prior_capability.graphql_operation
        or observation.graphql_query_sha256 != prior_capability.graphql_query_sha256
    ):
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("ADR-DC-091 live provenance invalid")
    return MappingProxyType({
        "review_thread_state_observation": observation,
        "prior_review_read_capability": prior_capability,
        "strict_base_sync_preflight": strict,
        "effective_review_policy": policy,
    })


def _require_source_window(observation: Any, *, materialized_at_utc: str) -> None:
    at = _utc(materialized_at_utc, name="materialized_at_utc")
    source = _utc(observation.second_observed_at_utc, name="ADR-DC-090 second_observed_at_utc")
    if at < source or (at - source).total_seconds() > MAX_SOURCE_AGE_SECONDS:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("ADR-DC-091 source chain is stale")


_live: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], Mapping[str, str]]] = {}


def _get_live_pr_post_policy_review_read_capability_inputs(value: Any) -> Mapping[str, Any] | None:
    row = _live.get(id(value))
    if row is None:
        return None
    pid, digest, ref, policy_ref, descriptor = row
    policy = policy_ref()
    if (
        pid != os.getpid() or ref() is not value or policy is None
        or policy.policy_authenticated is not True
        or policy.sha256 != value.review_policy_sha256
        or value.sha256 != digest
        or descriptor.get("broker_policy_sha256") != value.broker_policy_sha256
        or descriptor.get("broker_executable_sha256") != value.broker_executable_sha256
    ):
        return None
    return MappingProxyType({"review_policy": policy, "broker_descriptor": descriptor})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrPostPolicyReviewReadCapability:
    review_policy_sha256: str
    review_thread_state_observation_sha256: str
    prior_review_read_capability_sha256: str
    strict_base_sync_preflight_sha256: str
    ruleset_applicability_sha256: str
    ruleset_observation_sha256: str
    branch_protection_observation_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    strict_base_tip_sha: str
    effective_review_policy_sha256: str
    graphql_operation: str
    graphql_query_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    secret_source: str
    secret_transport: str
    graphql_endpoint: str
    credential_account_sha256: str
    materialized_at_utc: str
    source_review_policy_verified: bool = True
    source_review_observation_verified: bool = True
    source_review_policy_supported: bool = True
    effective_review_policy_hash_verified: bool = True
    fresh_source_window_verified: bool = True
    post_policy_review_read_capability_materialized: bool = True
    read_broker_host_pinned: bool = True
    read_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    graphql_query_only: bool = True
    graphql_mutations_forbidden: bool = True
    graphql_introspection_forbidden: bool = True
    other_repository_reads_forbidden: bool = True
    fresh_review_reobservation_required: bool = True
    review_policy_evaluation_required: bool = True
    fresh_required_status_reobservation_before_merge_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    branch_policy_fully_evaluated: bool = False
    review_thread_policy_evaluated: bool = False
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    review_thread_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY:
            raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("capability schema/authority invalid")
        for name in (
            "review_policy_sha256", "review_thread_state_observation_sha256",
            "prior_review_read_capability_sha256", "strict_base_sync_preflight_sha256",
            "ruleset_applicability_sha256", "ruleset_observation_sha256",
            "branch_protection_observation_sha256", "effective_review_policy_sha256",
            "graphql_query_sha256", "broker_policy_sha256", "broker_executable_path_sha256",
            "broker_executable_sha256", "credential_account_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(self.strict_base_tip_sha, name="strict_base_tip_sha")
        _utc(self.materialized_at_utc, name="materialized_at_utc")
        if (
            self.repository != _REPOSITORY
            or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or not isinstance(self.graphql_operation, str) or not self.graphql_operation
            or self.credential_protocol != capability_boundary.PROTOCOL
            or self.secret_source != capability_boundary.SECRET_SOURCE
            or self.secret_transport != capability_boundary.SECRET_TRANSPORT
            or self.graphql_endpoint != capability_boundary.GRAPHQL_ENDPOINT
            or self.credential_account_sha256
            != hashlib.sha256(capability_boundary.CREDENTIAL_ACCOUNT.encode("utf-8")).hexdigest()
        ):
            raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("capability target/broker identity invalid")
        required_true = (
            "source_review_policy_verified", "source_review_observation_verified",
            "source_review_policy_supported", "effective_review_policy_hash_verified",
            "fresh_source_window_verified", "post_policy_review_read_capability_materialized",
            "read_broker_host_pinned", "read_broker_binary_verified", "credential_secret_not_loaded",
            "credential_broker_owns_https", "graphql_query_only", "graphql_mutations_forbidden",
            "graphql_introspection_forbidden", "other_repository_reads_forbidden",
            "fresh_review_reobservation_required", "review_policy_evaluation_required",
            "fresh_required_status_reobservation_before_merge_required",
            "fresh_merge_transaction_revalidation_required",
        )
        forced_false = (
            "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "review_thread_mutation_authorized",
            "review_submission_authorized", "merge_readiness_authorized", "merge_authorized",
            "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("capability evidence incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("capability authority widened")

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_post_policy_review_read_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrPostPolicyReviewReadCapability":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("capability fields mismatch")
        return cls(**dict(value))


def _materialize_verified_pilot_exact_task_pr_post_policy_review_read_capability(
    *,
    review_policy: PilotExactTaskPrReviewPolicy,
    broker_descriptor: Mapping[str, str],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrPostPolicyReviewReadCapability:
    live = _require_live_policy(review_policy)
    observation = live["review_thread_state_observation"]
    prior_capability = live["prior_review_read_capability"]
    descriptor = capability_boundary._descriptor(
        broker_descriptor,
        expected_operation=prior_capability.graphql_operation,
        expected_query_sha256=prior_capability.graphql_query_sha256,
    )
    at = now_provider()
    _require_source_window(observation, materialized_at_utc=at)
    result = PilotExactTaskPrPostPolicyReviewReadCapability(
        review_policy.sha256,
        observation.sha256,
        prior_capability.sha256,
        review_policy.strict_base_sync_preflight_sha256,
        review_policy.ruleset_applicability_sha256,
        review_policy.ruleset_observation_sha256,
        review_policy.branch_protection_observation_sha256,
        review_policy.repository,
        review_policy.pull_request_number,
        review_policy.predicted_commit_sha,
        review_policy.strict_base_tip_sha,
        review_policy.effective_review_policy_sha256,
        prior_capability.graphql_operation,
        prior_capability.graphql_query_sha256,
        descriptor["broker_policy_sha256"],
        descriptor["broker_executable_path_sha256"],
        descriptor["broker_executable_sha256"],
        descriptor["broker_version"],
        descriptor["credential_protocol"],
        descriptor["secret_source"],
        descriptor["secret_transport"],
        descriptor["graphql_endpoint"],
        hashlib.sha256(descriptor["credential_account"].encode("utf-8")).hexdigest(),
        at,
    )
    key = id(result)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live.pop(key, None)

    _live[key] = (
        os.getpid(),
        result.sha256,
        weakref.ref(result, cleanup),
        weakref.ref(review_policy),
        descriptor,
    )
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError("capability lost live provenance")
    return result


def materialize_pilot_exact_task_pr_post_policy_review_read_capability(
    review_policy: PilotExactTaskPrReviewPolicy,
) -> PilotExactTaskPrPostPolicyReviewReadCapability:
    live = _require_live_policy(review_policy)
    prior_capability = live["prior_review_read_capability"]
    try:
        descriptor = production_boundary._canonical_broker_descriptor(
            capability_boundary._implementation,
            expected_operation=prior_capability.graphql_operation,
            expected_query_sha256=prior_capability.graphql_query_sha256,
        )
        return _materialize_verified_pilot_exact_task_pr_post_policy_review_read_capability(
            review_policy=review_policy,
            broker_descriptor=descriptor,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPrPostPolicyReviewReadCapabilityError:
        raise
    except Exception as exc:
        raise PilotExactTaskPrPostPolicyReviewReadCapabilityError(
            "host-controlled post-policy review read capability failed closed"
        ) from exc


__all__ = [
    "SCHEMA", "AUTHORITY", "MAX_SOURCE_AGE_SECONDS",
    "PilotExactTaskPrPostPolicyReviewReadCapabilityError",
    "PilotExactTaskPrPostPolicyReviewReadCapability",
    "materialize_pilot_exact_task_pr_post_policy_review_read_capability",
]
