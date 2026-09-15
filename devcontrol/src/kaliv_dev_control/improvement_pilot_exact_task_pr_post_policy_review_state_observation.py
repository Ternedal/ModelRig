"""ADR-DC-093 fresh post-policy reviewDecision + review-thread reobservation.

Consumes one fresh live ADR-DC-092 capability and performs a new bounded double
observation through the already pinned ADR-DC-089 GraphQL read broker. The
wire read mechanics are deliberately reused from qualified ADR-DC-090; this
boundary adds post-policy provenance and freshness, not new broker authority.
"""
from __future__ import annotations

import hashlib
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_post_policy_review_read_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_review_policy as policy_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as prior_observation_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as prior_capability_boundary
from .improvement_pilot_exact_task_pr_post_policy_review_read_capability import (
    PilotExactTaskPrPostPolicyReviewReadCapability,
)

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-post-policy-review-state-observation/v1"
AUTHORITY = "observed-one-dc-l16-post-policy-review-decision-thread-state-only"
OBSERVATION_SCOPE = "brokered-stable-post-policy-review-decision-thread-read-only-v1"
MAX_CAPABILITY_AGE_SECONDS = 10
MAX_OBSERVATION_WINDOW_SECONDS = 30
_REPOSITORY = "Ternedal/ModelRig"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REVIEW_DECISIONS = frozenset({"NONE", "APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"})


class PilotExactTaskPrPostPolicyReviewStateObservationError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return prior_observation_boundary._canonical(value)


def _canonical_bytes(value: Any) -> bytes:
    return prior_observation_boundary._canonical_bytes(value)


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError(f"{name} invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError(f"{name} invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError(f"{name} invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError(f"{name} invalid")
    return value


def _require_live_capability(value: Any) -> tuple[
    PilotExactTaskPrPostPolicyReviewReadCapability, Any, Any, Mapping[str, str]
]:
    if type(value) is not PilotExactTaskPrPostPolicyReviewReadCapability:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("live ADR-DC-092 capability required")
    try:
        replay = PilotExactTaskPrPostPolicyReviewReadCapability.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("ADR-DC-092 replay validation failed") from exc
    live = capability_boundary._get_live_pr_post_policy_review_read_capability_inputs(value)
    review_policy = None if live is None else live.get("review_policy")
    descriptor = None if live is None else live.get("broker_descriptor")
    policy_live = (
        None if review_policy is None
        else policy_boundary._get_live_pr_review_policy_inputs(review_policy)
    )
    prior_observation = None if policy_live is None else policy_live.get("review_thread_state_observation")
    observed_live = (
        None if prior_observation is None
        else prior_observation_boundary._get_live_pr_strict_synced_review_thread_state_observation_inputs(prior_observation)
    )
    prior_capability = None if observed_live is None else observed_live.get("review_thread_read_capability")
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
    if (
        replay != value or replay.sha256 != value.sha256 or value.capability_authenticated is not True
        or live is None or review_policy is None or review_policy.policy_authenticated is not True
        or descriptor is None or prior_observation is None or prior_observation.observation_authenticated is not True
        or prior_capability is None or prior_capability.capability_authenticated is not True
        or value.review_policy_sha256 != review_policy.sha256
        or value.review_thread_state_observation_sha256 != prior_observation.sha256
        or value.prior_review_read_capability_sha256 != prior_capability.sha256
        or value.effective_review_policy_sha256 != review_policy.effective_review_policy_sha256
        or value.repository != _REPOSITORY
        or value.repository != prior_observation.repository
        or value.pull_request_number != prior_observation.pull_request_number
        or value.predicted_commit_sha != prior_observation.predicted_commit_sha
        or value.strict_base_tip_sha != prior_observation.strict_base_tip_sha
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("ADR-DC-092 provenance/authority invalid")
    checked = prior_capability_boundary._descriptor(
        descriptor,
        expected_operation=value.graphql_operation,
        expected_query_sha256=value.graphql_query_sha256,
    )
    if (
        checked["broker_policy_sha256"] != value.broker_policy_sha256
        or checked["broker_executable_path_sha256"] != value.broker_executable_path_sha256
        or checked["broker_executable_sha256"] != value.broker_executable_sha256
        or checked["credential_protocol"] != value.credential_protocol
        or checked["graphql_operation"] != value.graphql_operation
        or checked["graphql_query_sha256"] != value.graphql_query_sha256
    ):
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("ADR-DC-092 broker descriptor drifted")
    return value, review_policy, prior_observation, checked


def _require_capability_window(
    capability: PilotExactTaskPrPostPolicyReviewReadCapability, *, at_utc: str
) -> None:
    at = _utc(at_utc, name="observation start")
    materialized = _utc(capability.materialized_at_utc, name="ADR-DC-092 materialized_at_utc")
    if at < materialized or (at - materialized).total_seconds() > MAX_CAPABILITY_AGE_SECONDS:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("ADR-DC-092 capability is stale")


_live: dict[int, tuple[
    int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], tuple[Mapping[str, Any], ...]
]] = {}


def _mark_authenticated(
    result: Any,
    capability: PilotExactTaskPrPostPolicyReviewReadCapability,
    thread_rows: tuple[Mapping[str, Any], ...],
) -> None:
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live.pop(key, None)
    _live[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(capability), thread_rows)


def _get_live_pr_post_policy_review_state_observation_inputs(result: Any) -> Mapping[str, Any] | None:
    row = _live.get(id(result))
    if row is None:
        return None
    pid, digest, ref, capability_ref, rows = row
    capability = capability_ref()
    if (
        pid != os.getpid() or ref() is not result or capability is None
        or capability.capability_authenticated is not True
        or capability.sha256 != result.post_policy_review_read_capability_sha256
        or hashlib.sha256(_canonical_bytes([dict(item) for item in rows])).hexdigest()
        != result.review_threads_inventory_sha256
        or result.sha256 != digest
    ):
        return None
    return MappingProxyType({"post_policy_review_read_capability": capability, "review_threads": rows})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrPostPolicyReviewStateObservation:
    post_policy_review_read_capability_sha256: str
    review_policy_sha256: str
    prior_review_thread_state_observation_sha256: str
    prior_review_read_capability_sha256: str
    strict_base_sync_preflight_sha256: str
    ruleset_applicability_sha256: str
    ruleset_observation_sha256: str
    branch_protection_observation_sha256: str
    effective_review_policy_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    strict_base_tip_sha: str
    graphql_operation: str
    graphql_query_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    credential_protocol: str
    pull_request_node_id_sha256: str
    head_ref_name: str
    first_review_threads_inventory_sha256: str
    second_review_threads_inventory_sha256: str
    review_threads_inventory_sha256: str
    first_broker_evidence_sha256: str
    second_broker_evidence_sha256: str
    github_review_decision: str
    review_thread_count: int
    unresolved_review_thread_count: int
    unresolved_outdated_review_thread_count: int
    review_thread_page_count: int
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_capability_verified: bool = True
    source_review_policy_verified: bool = True
    source_prior_observation_verified: bool = True
    source_strict_sync_verified: bool = True
    fresh_capability_age_verified: bool = True
    broker_binary_reverified: bool = True
    graphql_fixed_query_verified: bool = True
    exact_repository_pr_head_revalidated: bool = True
    review_decision_observed: bool = True
    review_threads_observed: bool = True
    review_thread_inventory_complete: bool = True
    stable_double_observation_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    bounded_broker_process: bool = True
    broker_stderr_empty: bool = True
    pagination_bounded: bool = True
    fresh_review_reobservation_completed: bool = True
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
    observation_scope: str = OBSERVATION_SCOPE
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY or self.observation_scope != OBSERVATION_SCOPE:
            raise PilotExactTaskPrPostPolicyReviewStateObservationError("schema/authority/scope invalid")
        for name in (
            "post_policy_review_read_capability_sha256", "review_policy_sha256",
            "prior_review_thread_state_observation_sha256", "prior_review_read_capability_sha256",
            "strict_base_sync_preflight_sha256", "ruleset_applicability_sha256",
            "ruleset_observation_sha256", "branch_protection_observation_sha256",
            "effective_review_policy_sha256", "graphql_query_sha256", "broker_policy_sha256",
            "broker_executable_path_sha256", "broker_executable_sha256", "pull_request_node_id_sha256",
            "first_review_threads_inventory_sha256", "second_review_threads_inventory_sha256",
            "review_threads_inventory_sha256", "first_broker_evidence_sha256", "second_broker_evidence_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("predicted_commit_sha", "strict_base_tip_sha"):
            _hex40(getattr(self, name), name=name)
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if second < first or (second - first).total_seconds() > MAX_OBSERVATION_WINDOW_SECONDS:
            raise PilotExactTaskPrPostPolicyReviewStateObservationError("observation window invalid")
        if (
            self.repository != _REPOSITORY
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or not isinstance(self.graphql_operation, str) or not self.graphql_operation
            or not isinstance(self.credential_protocol, str) or not self.credential_protocol
            or not isinstance(self.head_ref_name, str) or not self.head_ref_name
            or len(self.head_ref_name.encode("utf-8")) > 512
            or self.github_review_decision not in _REVIEW_DECISIONS
        ):
            raise PilotExactTaskPrPostPolicyReviewStateObservationError("target/observed identity invalid")
        for name in (
            "review_thread_count", "unresolved_review_thread_count",
            "unresolved_outdated_review_thread_count", "review_thread_page_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PilotExactTaskPrPostPolicyReviewStateObservationError(f"{name} invalid")
        if (
            self.review_thread_page_count < 1 or self.review_thread_page_count > 10
            or self.unresolved_review_thread_count > self.review_thread_count
            or self.unresolved_outdated_review_thread_count > self.unresolved_review_thread_count
            or self.first_review_threads_inventory_sha256 != self.second_review_threads_inventory_sha256
            or self.review_threads_inventory_sha256 != self.first_review_threads_inventory_sha256
        ):
            raise PilotExactTaskPrPostPolicyReviewStateObservationError("inventory/count evidence invalid")
        required_true = (
            "source_capability_verified", "source_review_policy_verified", "source_prior_observation_verified",
            "source_strict_sync_verified", "fresh_capability_age_verified", "broker_binary_reverified",
            "graphql_fixed_query_verified", "exact_repository_pr_head_revalidated", "review_decision_observed",
            "review_threads_observed", "review_thread_inventory_complete", "stable_double_observation_verified",
            "credential_secret_not_loaded", "credential_broker_owns_https", "bounded_broker_process",
            "broker_stderr_empty", "pagination_bounded", "fresh_review_reobservation_completed",
            "review_policy_evaluation_required", "fresh_required_status_reobservation_before_merge_required",
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
            raise PilotExactTaskPrPostPolicyReviewStateObservationError("observation evidence incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrPostPolicyReviewStateObservationError("observation authority widened")

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_post_policy_review_state_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrPostPolicyReviewStateObservation":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrPostPolicyReviewStateObservationError("fields mismatch")
        return cls(**dict(value))


def _observe_verified_pilot_exact_task_pr_post_policy_review_state(
    *,
    post_policy_review_read_capability: PilotExactTaskPrPostPolicyReviewReadCapability,
    subprocess_runner: Callable[..., Any],
    now_provider: Callable[[], str],
    require_host_control: bool,
) -> PilotExactTaskPrPostPolicyReviewStateObservation:
    capability, review_policy, prior_observation, descriptor = _require_live_capability(
        post_policy_review_read_capability
    )
    first_at = now_provider()
    _require_capability_window(capability, at_utc=first_at)
    try:
        first = prior_observation_boundary._snapshot(
            capability=capability, descriptor=descriptor, subprocess_runner=subprocess_runner,
            require_host_control=require_host_control,
        )
        second = prior_observation_boundary._snapshot(
            capability=capability, descriptor=descriptor, subprocess_runner=subprocess_runner,
            require_host_control=require_host_control,
        )
    except prior_observation_boundary.PilotExactTaskPrStrictSyncedReviewThreadStateObservationError as exc:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("post-policy broker observation failed closed") from exc
    second_at = now_provider()
    first_dt = _utc(first_at, name="first_observed_at_utc")
    second_dt = _utc(second_at, name="second_observed_at_utc")
    if second_dt < first_dt or (second_dt - first_dt).total_seconds() > MAX_OBSERVATION_WINDOW_SECONDS:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("observation clock/window invalid")
    stable_keys = (
        "pull_request_node_id_sha256", "head_ref_name", "review_decision", "thread_inventory_sha256",
        "thread_count", "unresolved_thread_count", "unresolved_outdated_thread_count", "thread_page_count",
    )
    if any(first[name] != second[name] for name in stable_keys):
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("double observation drifted")
    result = PilotExactTaskPrPostPolicyReviewStateObservation(
        capability.sha256,
        review_policy.sha256,
        prior_observation.sha256,
        capability.prior_review_read_capability_sha256,
        capability.strict_base_sync_preflight_sha256,
        capability.ruleset_applicability_sha256,
        capability.ruleset_observation_sha256,
        capability.branch_protection_observation_sha256,
        capability.effective_review_policy_sha256,
        capability.repository,
        capability.pull_request_number,
        capability.predicted_commit_sha,
        capability.strict_base_tip_sha,
        capability.graphql_operation,
        capability.graphql_query_sha256,
        capability.broker_policy_sha256,
        capability.broker_executable_path_sha256,
        capability.broker_executable_sha256,
        capability.credential_protocol,
        first["pull_request_node_id_sha256"],
        first["head_ref_name"],
        first["thread_inventory_sha256"],
        second["thread_inventory_sha256"],
        first["thread_inventory_sha256"],
        first["broker_evidence_sha256"],
        second["broker_evidence_sha256"],
        first["review_decision"],
        first["thread_count"],
        first["unresolved_thread_count"],
        first["unresolved_outdated_thread_count"],
        first["thread_page_count"],
        first_at,
        second_at,
    )
    _mark_authenticated(result, capability, first["thread_rows"])
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrPostPolicyReviewStateObservationError("observation lost live provenance")
    return result


def observe_pilot_exact_task_pr_post_policy_review_state(
    post_policy_review_read_capability: PilotExactTaskPrPostPolicyReviewReadCapability,
) -> PilotExactTaskPrPostPolicyReviewStateObservation:
    return _observe_verified_pilot_exact_task_pr_post_policy_review_state(
        post_policy_review_read_capability=post_policy_review_read_capability,
        subprocess_runner=prior_observation_boundary.run_bounded_subprocess,
        now_provider=_now_utc_seconds,
        require_host_control=True,
    )


__all__ = [
    "SCHEMA", "AUTHORITY", "OBSERVATION_SCOPE",
    "PilotExactTaskPrPostPolicyReviewStateObservationError",
    "PilotExactTaskPrPostPolicyReviewStateObservation",
    "observe_pilot_exact_task_pr_post_policy_review_state",
]
