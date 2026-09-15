"""ADR-DC-084 branch-policy-bound GraphQL review-thread read capability.

Consumes one fresh live ADR-DC-083 repository/inherited ruleset observation.
The source retains live legacy branch-protection and exact-head status evidence.
This boundary materializes only one host-pinned GraphQL read capability for
reviewDecision + reviewThreads; it evaluates no status/ruleset/thread policy
and grants no merge or mutation authority.
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

from . import improvement_pilot_exact_task_pr_ruleset_observation as ruleset_boundary
from . import improvement_pilot_exact_task_pr_branch_protection_observation as branch_boundary
from . import improvement_pilot_exact_task_pr_status_check_observation as status_boundary
from .improvement_pilot_exact_task_pr_ruleset_observation import (
    PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_AUTHORITY,
    PilotExactTaskPrRulesetObservation,
)

PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-branch-bound-review-thread-credential-capability/v1"
)
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-branch-policy-sources-bound-exact-pr-review-thread-graphql-read-broker-only"
)
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_PROTOCOL = (
    "github-branch-bound-review-thread-graphql-read-broker-v1"
)
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_OPERATION = (
    "query-branch-bound-exact-pull-request-review-thread-state"
)
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_SOURCE = "host-secret-store-only"
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_TRANSPORT = "broker-owned-https-only"
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_ACCOUNT = "Ternedal"
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_MAX_OBSERVATION_AGE_SECONDS = 15
PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_QUERY = (
    "query ModelRigBranchBoundExactPullRequestReviewThreadState($owner:String!,"
    "$name:String!,$number:Int!,$threadsCursor:String){repository(owner:$owner,"
    "name:$name){pullRequest(number:$number){id number state isDraft baseRefName "
    "headRefName headRefOid reviewDecision reviewThreads(first:100,after:"
    "$threadsCursor){nodes{id isResolved isOutdated path}pageInfo{hasNextPage "
    "endCursor}}}}}"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(ValueError):
    """Branch-bound review-thread credential capability is stale or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "branch-bound review-thread capability is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _require_live_ruleset_observation(value: Any) -> Mapping[str, Any]:
    if type(value) is not PilotExactTaskPrRulesetObservation:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "exact live ADR-DC-083 ruleset observation is required"
        )
    try:
        replayed = PilotExactTaskPrRulesetObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "ADR-DC-083 ruleset replay validation failed"
        ) from exc
    live_ruleset = ruleset_boundary._get_live_pr_ruleset_observation_inputs(value)
    branch = None if live_ruleset is None else live_ruleset.get("branch_protection_observation")
    rulesets = () if live_ruleset is None else tuple(live_ruleset.get("rulesets", ()))
    live_branch = None if branch is None else branch_boundary._get_live_pr_branch_protection_observation_inputs(branch)
    status = None if live_branch is None else live_branch.get("status_check_observation")
    contexts = () if live_branch is None else tuple(live_branch.get("required_status_contexts", ()))
    checks = () if live_branch is None else tuple(live_branch.get("required_status_checks", ()))
    live_status = None if status is None else status_boundary._get_live_pr_status_check_observation_inputs(status)
    preflight = None if live_status is None else live_status.get("merge_preflight")
    check_rows = () if live_status is None else tuple(live_status.get("check_runs", ()))
    legacy_rows = () if live_status is None else tuple(live_status.get("legacy_statuses", ()))
    forced_false = (
        "required_status_checks_evaluated", "branch_policy_fully_evaluated", "status_policy_evaluated",
        "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized",
        "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized",
        "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or live_ruleset is None
        or branch is None
        or getattr(branch, "observation_authenticated", None) is not True
        or status is None
        or getattr(status, "observation_authenticated", None) is not True
        or preflight is None
        or getattr(preflight, "preflight_authenticated", None) is not True
        or value.branch_policy_sources_observed is not True
        or value.ruleset_policy_evaluation_required is not True
        or value.review_threads_preflight_required is not True
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or branch.sha256 != value.branch_protection_observation_sha256
        or status.sha256 != value.status_check_observation_sha256
        or preflight.sha256 != value.merge_preflight_sha256
        or preflight.review_disposition != "APPROVED"
        or preflight.predicted_commit_sha != value.predicted_commit_sha
        or preflight.pull_request_number != value.pull_request_number
        or len(rulesets) != value.ruleset_count
        or len(check_rows) != status.check_run_count
        or len(legacy_rows) != status.legacy_status_count
    ):
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "review-thread capability requires one live policy-neutral ADR-DC-083 source chain"
        )
    return MappingProxyType({
        "ruleset_observation": value,
        "branch_protection_observation": branch,
        "status_check_observation": status,
        "merge_preflight": preflight,
        "rulesets": rulesets,
        "required_status_contexts": contexts,
        "required_status_checks": checks,
        "check_runs": check_rows,
        "legacy_statuses": legacy_rows,
    })


def _require_observation_window(observation: PilotExactTaskPrRulesetObservation, *, at_utc: str) -> None:
    at = _utc(at_utc, name="materialized_at_utc")
    observed = _utc(observation.second_observed_at_utc, name="source_ruleset_second_observed_at_utc")
    if at < observed or (at - observed).total_seconds() > PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_MAX_OBSERVATION_AGE_SECONDS:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "ADR-DC-083 ruleset observation is too old for review-thread capability"
        )


def _descriptor(value: Any) -> Mapping[str, str]:
    expected = {
        "broker_policy_sha256", "broker_executable_path", "broker_executable_path_sha256",
        "broker_executable_sha256", "broker_version", "credential_protocol",
        "graphql_operation", "secret_source", "secret_transport", "graphql_endpoint",
        "credential_account", "graphql_query_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "branch-bound review-thread broker descriptor fields mismatch"
        )
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "branch-bound review-thread broker descriptor contains invalid text"
        )
    for name in ("broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256", "graphql_query_sha256"):
        _hex64(result[name], name=name)
    path = Path(result["broker_executable_path"])
    if (
        not path.is_absolute()
        or result["broker_executable_path_sha256"] != _path_sha256(path)
        or _VERSION.fullmatch(result["broker_version"]) is None
        or result["credential_protocol"] != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_PROTOCOL
        or result["graphql_operation"] != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_OPERATION
        or result["secret_source"] != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_SOURCE
        or result["secret_transport"] != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_TRANSPORT
        or result["graphql_endpoint"] != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_ENDPOINT
        or result["credential_account"] != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_ACCOUNT
        or result["graphql_query_sha256"] != _sha256_text(PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_QUERY)
    ):
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "branch-bound review-thread broker descriptor semantics are unsupported"
        )
    return MappingProxyType(result)


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrRulesetObservation], Mapping[str, str]]] = {}


def _mark_authenticated(capability: Any, observation: PilotExactTaskPrRulesetObservation, descriptor: Mapping[str, str]) -> None:
    key = id(capability)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), capability.sha256, weakref.ref(capability, cleanup), weakref.ref(observation), descriptor)


def _get_live_pr_branch_bound_review_thread_credential_capability_inputs(capability: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(capability))
    if entry is None:
        return None
    pid, digest, capability_ref, observation_ref, descriptor = entry
    observation = observation_ref()
    if (
        pid != os.getpid()
        or capability_ref() is not capability
        or observation is None
        or observation.observation_authenticated is not True
        or observation.sha256 != capability.ruleset_observation_sha256
        or capability.sha256 != digest
        or descriptor.get("broker_policy_sha256") != capability.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256") != capability.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256") != capability.broker_executable_sha256
        or descriptor.get("graphql_operation") != capability.graphql_operation
        or descriptor.get("graphql_query_sha256") != capability.graphql_query_sha256
    ):
        return None
    return MappingProxyType({"ruleset_observation": observation, "credential_broker_descriptor": descriptor})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrBranchBoundReviewThreadCredentialCapability:
    ruleset_observation_sha256: str
    branch_protection_observation_sha256: str
    status_check_observation_sha256: str
    merge_preflight_sha256: str
    review_disposition_sha256: str
    submitted_review_observation_sha256: str
    review_observation_checkpoint_sha256: str
    reviewer_handoff_requirements_sha256: str
    repository: str
    pull_request_number: int
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    base_branch_tip_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    semantic_pr_title_sha256: str
    semantic_pr_body_sha256: str
    check_runs_inventory_sha256: str
    legacy_statuses_inventory_sha256: str
    status_combined_evidence_sha256: str
    check_run_count: int
    legacy_status_count: int
    required_status_policy_sha256: str
    normalized_protection_sha256: str
    required_status_context_count: int
    required_status_check_count: int
    legacy_branch_protection_present: bool
    base_branch_protected: bool
    ruleset_inventory_sha256: str
    ruleset_combined_evidence_sha256: str
    ruleset_count: int
    active_ruleset_count: int
    evaluate_ruleset_count: int
    disabled_ruleset_count: int
    other_enforcement_ruleset_count: int
    source_ruleset_second_observed_at_utc: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    graphql_operation: str
    secret_source: str
    secret_transport: str
    graphql_endpoint: str
    credential_account_sha256: str
    graphql_query_sha256: str
    materialized_at_utc: str
    ruleset_observation_verified: bool = True
    branch_protection_observation_verified: bool = True
    status_check_observation_verified: bool = True
    source_merge_preflight_verified: bool = True
    source_approved_review_verified: bool = True
    source_exact_head_status_inventory_verified: bool = True
    source_legacy_branch_protection_verified: bool = True
    source_repository_rulesets_verified: bool = True
    source_inherited_rulesets_verified: bool = True
    source_branch_policy_sources_observed: bool = True
    source_status_policy_not_evaluated: bool = True
    source_required_status_checks_not_evaluated: bool = True
    source_ruleset_policy_not_evaluated: bool = True
    fresh_ruleset_observation_age_verified: bool = True
    review_thread_credential_capability_materialized: bool = True
    read_broker_host_pinned: bool = True
    read_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    review_decision_read_only: bool = True
    review_threads_read_only: bool = True
    graphql_queries_only: bool = True
    graphql_mutations_forbidden: bool = True
    graphql_introspection_forbidden: bool = True
    redirect_following_forbidden: bool = True
    rest_review_read_forbidden: bool = True
    other_repository_reads_forbidden: bool = True
    review_submission_write_forbidden: bool = True
    review_dismissal_write_forbidden: bool = True
    review_thread_mutation_forbidden: bool = True
    reviewer_request_write_forbidden: bool = True
    pull_request_create_forbidden: bool = True
    pull_request_metadata_write_forbidden: bool = True
    ready_for_review_write_forbidden: bool = True
    label_write_forbidden: bool = True
    merge_write_forbidden: bool = True
    repository_contents_write_forbidden: bool = True
    administration_write_forbidden: bool = True
    release_write_forbidden: bool = True
    deployment_write_forbidden: bool = True
    review_thread_state_observation_required: bool = True
    required_status_checks_evaluation_still_required: bool = True
    ruleset_policy_evaluation_still_required: bool = True
    branch_policy_fully_evaluated: bool = False
    fresh_review_reobservation_still_required: bool = True
    fresh_merge_transaction_revalidation_still_required: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    nonce_reusable: bool = False
    reviewer_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA
    credential_scope: str = "branch-policy-sources-bound-exact-pr-review-decision-thread-graphql-read-only-v1"

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY
            or self.credential_scope != "branch-policy-sources-bound-exact-pr-review-decision-thread-graphql-read-only-v1"
        ):
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
                "branch-bound review-thread capability schema/authority/scope unsupported"
            )
        for name in (
            "ruleset_observation_sha256", "branch_protection_observation_sha256", "status_check_observation_sha256",
            "merge_preflight_sha256", "review_disposition_sha256", "submitted_review_observation_sha256", "review_observation_checkpoint_sha256",
            "reviewer_handoff_requirements_sha256", "pull_request_node_id_sha256", "reviewer_user_node_id_sha256",
            "semantic_pr_title_sha256", "semantic_pr_body_sha256", "check_runs_inventory_sha256",
            "legacy_statuses_inventory_sha256", "status_combined_evidence_sha256", "required_status_policy_sha256",
            "normalized_protection_sha256", "ruleset_inventory_sha256", "ruleset_combined_evidence_sha256",
            "broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256",
            "credential_account_sha256", "graphql_query_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(self.base_branch_tip_sha, name="base_branch_tip_sha")
        source_at = _utc(self.source_ruleset_second_observed_at_utc, name="source_ruleset_second_observed_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if materialized < source_at or (materialized - source_at).total_seconds() > PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_MAX_OBSERVATION_AGE_SECONDS:
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
                "branch-bound review-thread capability timing is invalid"
            )
        counts = (
            self.check_run_count, self.legacy_status_count, self.required_status_context_count,
            self.required_status_check_count, self.ruleset_count, self.active_ruleset_count,
            self.evaluate_ruleset_count, self.disabled_ruleset_count, self.other_enforcement_ruleset_count,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError("capability counts are invalid")
        if self.active_ruleset_count + self.evaluate_ruleset_count + self.disabled_ruleset_count + self.other_enforcement_ruleset_count != self.ruleset_count:
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError("ruleset counts are inconsistent")
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool) or not isinstance(self.reviewer_user_id, int) or self.reviewer_user_id < 1
            or _LOGIN.fullmatch(self.pull_request_author_login) is None
            or isinstance(self.pull_request_author_user_id, bool) or not isinstance(self.pull_request_author_user_id, int) or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_PROTOCOL
            or self.graphql_operation != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_OPERATION
            or self.secret_source != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_SOURCE
            or self.secret_transport != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_TRANSPORT
            or self.graphql_endpoint != PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_ENDPOINT
            or self.credential_account_sha256 != _sha256_text(PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_ACCOUNT)
            or self.graphql_query_sha256 != _sha256_text(PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_QUERY)
        ):
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
                "branch-bound review-thread capability exact binding is invalid"
            )
        required_true = (
            "ruleset_observation_verified", "branch_protection_observation_verified", "status_check_observation_verified",
            "source_merge_preflight_verified", "source_approved_review_verified", "source_exact_head_status_inventory_verified",
            "source_legacy_branch_protection_verified", "source_repository_rulesets_verified", "source_inherited_rulesets_verified",
            "source_branch_policy_sources_observed", "source_status_policy_not_evaluated",
            "source_required_status_checks_not_evaluated", "source_ruleset_policy_not_evaluated",
            "fresh_ruleset_observation_age_verified", "review_thread_credential_capability_materialized",
            "read_broker_host_pinned", "read_broker_binary_verified", "credential_secret_not_loaded",
            "credential_broker_owns_https", "review_decision_read_only", "review_threads_read_only",
            "graphql_queries_only", "graphql_mutations_forbidden", "graphql_introspection_forbidden",
            "redirect_following_forbidden", "rest_review_read_forbidden", "other_repository_reads_forbidden",
            "review_submission_write_forbidden", "review_dismissal_write_forbidden", "review_thread_mutation_forbidden",
            "reviewer_request_write_forbidden", "pull_request_create_forbidden", "pull_request_metadata_write_forbidden",
            "ready_for_review_write_forbidden", "label_write_forbidden", "merge_write_forbidden",
            "repository_contents_write_forbidden", "administration_write_forbidden", "release_write_forbidden",
            "deployment_write_forbidden", "review_thread_state_observation_required",
            "required_status_checks_evaluation_still_required", "ruleset_policy_evaluation_still_required",
            "fresh_review_reobservation_still_required", "fresh_merge_transaction_revalidation_still_required",
        )
        forced_false = (
            "branch_policy_fully_evaluated", "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "nonce_reusable", "reviewer_mutation_authorized",
            "review_submission_authorized", "review_thread_mutation_authorized", "merge_readiness_authorized",
            "label_mutation_authorized", "merge_authorized", "release_authorized", "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
                "branch-bound review-thread capability evidence incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
                "branch-bound review-thread capability retains forbidden authority"
            )

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_branch_bound_review_thread_credential_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrBranchBoundReviewThreadCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
                "branch-bound review-thread capability must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
                "branch-bound review-thread capability fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_branch_bound_review_thread_credential_capability(
    *,
    ruleset_observation: PilotExactTaskPrRulesetObservation,
    broker_descriptor: Mapping[str, str],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrBranchBoundReviewThreadCredentialCapability:
    live = _require_live_ruleset_observation(ruleset_observation)
    source = live["ruleset_observation"]
    branch = live["branch_protection_observation"]
    status = live["status_check_observation"]
    preflight = live["merge_preflight"]
    descriptor = _descriptor(broker_descriptor)
    materialized_at = now_provider()
    _require_observation_window(source, at_utc=materialized_at)
    result = PilotExactTaskPrBranchBoundReviewThreadCredentialCapability(
        ruleset_observation_sha256=source.sha256,
        branch_protection_observation_sha256=source.branch_protection_observation_sha256,
        status_check_observation_sha256=source.status_check_observation_sha256,
        merge_preflight_sha256=source.merge_preflight_sha256,
        review_disposition_sha256=source.review_disposition_sha256,
        submitted_review_observation_sha256=preflight.submitted_review_observation_sha256,
        review_observation_checkpoint_sha256=branch.review_observation_checkpoint_sha256,
        reviewer_handoff_requirements_sha256=preflight.reviewer_handoff_requirements_sha256,
        repository=source.repository,
        pull_request_number=source.pull_request_number,
        pull_request_node_id_sha256=preflight.pull_request_node_id_sha256,
        base_branch=source.base_branch,
        head_branch=source.head_branch,
        predicted_commit_sha=source.predicted_commit_sha,
        base_branch_tip_sha=source.base_branch_tip_sha,
        reviewer_login=preflight.reviewer_login,
        reviewer_user_id=preflight.reviewer_user_id,
        reviewer_user_node_id_sha256=preflight.reviewer_user_node_id_sha256,
        pull_request_author_login=preflight.pull_request_author_login,
        pull_request_author_user_id=preflight.pull_request_author_user_id,
        semantic_pr_title_sha256=preflight.semantic_pr_title_sha256,
        semantic_pr_body_sha256=preflight.semantic_pr_body_sha256,
        check_runs_inventory_sha256=status.check_runs_inventory_sha256,
        legacy_statuses_inventory_sha256=status.legacy_statuses_inventory_sha256,
        status_combined_evidence_sha256=status.second_combined_evidence_sha256,
        check_run_count=status.check_run_count,
        legacy_status_count=status.legacy_status_count,
        required_status_policy_sha256=branch.required_status_policy_sha256,
        normalized_protection_sha256=branch.normalized_protection_sha256,
        required_status_context_count=branch.required_status_context_count,
        required_status_check_count=branch.required_status_check_count,
        legacy_branch_protection_present=branch.legacy_branch_protection_present,
        base_branch_protected=branch.base_branch_protected,
        ruleset_inventory_sha256=source.ruleset_inventory_sha256,
        ruleset_combined_evidence_sha256=source.second_combined_evidence_sha256,
        ruleset_count=source.ruleset_count,
        active_ruleset_count=source.active_ruleset_count,
        evaluate_ruleset_count=source.evaluate_ruleset_count,
        disabled_ruleset_count=source.disabled_ruleset_count,
        other_enforcement_ruleset_count=source.other_enforcement_ruleset_count,
        source_ruleset_second_observed_at_utc=source.second_observed_at_utc,
        broker_policy_sha256=descriptor["broker_policy_sha256"],
        broker_executable_path_sha256=descriptor["broker_executable_path_sha256"],
        broker_executable_sha256=descriptor["broker_executable_sha256"],
        broker_version=descriptor["broker_version"],
        credential_protocol=descriptor["credential_protocol"],
        graphql_operation=descriptor["graphql_operation"],
        secret_source=descriptor["secret_source"],
        secret_transport=descriptor["secret_transport"],
        graphql_endpoint=descriptor["graphql_endpoint"],
        credential_account_sha256=_sha256_text(descriptor["credential_account"]),
        graphql_query_sha256=descriptor["graphql_query_sha256"],
        materialized_at_utc=materialized_at,
    )
    _mark_authenticated(result, source, descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
            "branch-bound review-thread capability lost live ADR-DC-083 provenance"
        )
    return result


def materialize_pilot_exact_task_pr_branch_bound_review_thread_credential_capability(
    ruleset_observation: PilotExactTaskPrRulesetObservation,
) -> PilotExactTaskPrBranchBoundReviewThreadCredentialCapability:
    """Installed by the host-pinned production boundary at facade import time."""
    raise PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError(
        "branch-bound review-thread credential production boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_PROTOCOL",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_OPERATION",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_SOURCE",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_TRANSPORT",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_ENDPOINT",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_ACCOUNT",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_MAX_OBSERVATION_AGE_SECONDS",
    "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_QUERY",
    "PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError",
    "PilotExactTaskPrBranchBoundReviewThreadCredentialCapability",
    "materialize_pilot_exact_task_pr_branch_bound_review_thread_credential_capability",
]
