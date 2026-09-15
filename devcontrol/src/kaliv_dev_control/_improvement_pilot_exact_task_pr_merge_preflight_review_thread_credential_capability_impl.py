"""ADR-DC-081 preflight-bound GraphQL capability for exact review-thread state.

Consumes one fresh live ADR-DC-080 semantic merge preflight. The source already
proves an APPROVED exact-head review disposition plus exact PR/head/title/body/
author metadata through stable credential-free reads. This boundary binds that
preflight to one host-admin-controlled broker that may execute exactly one fixed
GraphQL query for reviewDecision and reviewThreads. It loads no secret, starts
no subprocess, performs no network I/O, and grants no mutation or merge authority.
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

from . import improvement_pilot_exact_task_pr_merge_preflight as preflight_boundary
from .improvement_pilot_exact_task_pr_merge_preflight import (
    PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY,
    PilotExactTaskPrMergePreflight,
)

PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-merge-preflight-review-thread-credential-capability/v1"
)
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-preflighted-exact-pr-review-thread-graphql-read-broker-only"
)
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_PROTOCOL = (
    "github-preflighted-review-thread-graphql-read-broker-v1"
)
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_OPERATION = (
    "query-preflighted-exact-pull-request-review-thread-state"
)
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_SOURCE = "host-secret-store-only"
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_TRANSPORT = "broker-owned-https-only"
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_ACCOUNT = "Ternedal"
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_MAX_PREFLIGHT_AGE_SECONDS = 15
PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_QUERY = (
    "query ModelRigPreflightedExactPullRequestReviewThreadState($owner:String!,"
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


class PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(ValueError):
    """Preflight review-thread credential capability is stale or unsafe."""


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
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "preflight review-thread capability is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _require_live_merge_preflight(
    value: Any,
) -> tuple[PilotExactTaskPrMergePreflight, Any, Any]:
    if type(value) is not PilotExactTaskPrMergePreflight:
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "exact live ADR-DC-080 merge preflight is required"
        )
    try:
        replayed = PilotExactTaskPrMergePreflight.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "ADR-DC-080 preflight replay validation failed"
        ) from exc
    required_true = (
        "source_review_disposition_verified",
        "source_exact_head_approval_verified",
        "semantic_requirements_replay_verified",
        "semantic_metadata_policy_restored",
        "semantic_metadata_verified",
        "maintainer_can_modify_false_verified",
        "exact_pr_identity_revalidated",
        "exact_head_revalidated",
        "exact_base_revalidated",
        "exact_author_revalidated",
        "open_ready_state_revalidated",
        "requested_reviewer_shape_revalidated",
        "stable_double_observation_verified",
        "credential_free_reads",
        "fixed_origin_reads",
        "redirects_forbidden",
        "response_bounded",
        "fresh_review_disposition_age_verified",
        "metadata_and_review_preflight_passed",
        "fresh_review_reobservation_before_merge_required",
        "required_status_checks_preflight_required",
        "review_threads_preflight_required",
        "branch_policy_preflight_required",
        "fresh_merge_transaction_revalidation_required",
    )
    forced_false = (
        "reviewer_mutation_authorized",
        "review_submission_authorized",
        "review_thread_mutation_authorized",
        "ready_for_review_authorized",
        "label_mutation_authorized",
        "merge_readiness_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    live = preflight_boundary._get_live_pr_merge_preflight_inputs(value)
    disposition = None if live is None else live.get("review_disposition")
    checkpoint = None if live is None else live.get("review_observation_checkpoint")
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY
        or value.preflight_authenticated is not True
        or value.review_disposition != "APPROVED"
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or _LOGIN.fullmatch(value.reviewer_login) is None
        or disposition is None
        or getattr(disposition, "disposition_authenticated", None) is not True
        or disposition.sha256 != value.review_disposition_sha256
        or disposition.review_disposition != "APPROVED"
        or disposition.review_policy_passed is not True
        or disposition.exact_head_approval_verified is not True
        or checkpoint is None
        or getattr(checkpoint, "checkpoint_authenticated", None) is not True
        or checkpoint.sha256 != value.review_observation_checkpoint_sha256
        or checkpoint.checkpoint_key_sha256 != value.checkpoint_key_sha256
        or checkpoint.predicted_commit_sha != value.predicted_commit_sha
        or checkpoint.pull_request_number != value.pull_request_number
        or checkpoint.reviewer_login != value.reviewer_login
        or checkpoint.reviewer_user_id != value.reviewer_user_id
    ):
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "review-thread capability requires one live approved inert ADR-DC-080 preflight"
        )
    return value, disposition, checkpoint


def _require_preflight_window(
    preflight: PilotExactTaskPrMergePreflight,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="materialized_at_utc")
    observed = _utc(preflight.second_observed_at_utc, name="source_preflight_second_observed_at_utc")
    if (
        at < observed
        or (at - observed).total_seconds()
        > PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_MAX_PREFLIGHT_AGE_SECONDS
    ):
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "ADR-DC-080 merge preflight is too old for review-thread capability"
        )


def _descriptor(value: Any) -> Mapping[str, str]:
    expected = {
        "broker_policy_sha256",
        "broker_executable_path",
        "broker_executable_path_sha256",
        "broker_executable_sha256",
        "broker_version",
        "credential_protocol",
        "graphql_operation",
        "secret_source",
        "secret_transport",
        "graphql_endpoint",
        "credential_account",
        "graphql_query_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "preflight review-thread broker descriptor fields mismatch"
        )
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "preflight review-thread broker descriptor contains invalid text"
        )
    for name in (
        "broker_policy_sha256",
        "broker_executable_path_sha256",
        "broker_executable_sha256",
        "graphql_query_sha256",
    ):
        _hex64(result[name], name=name)
    path = Path(result["broker_executable_path"])
    if (
        not path.is_absolute()
        or result["broker_executable_path_sha256"] != _path_sha256(path)
        or _VERSION.fullmatch(result["broker_version"]) is None
        or result["credential_protocol"]
        != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_PROTOCOL
        or result["graphql_operation"]
        != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_OPERATION
        or result["secret_source"]
        != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_SOURCE
        or result["secret_transport"]
        != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_TRANSPORT
        or result["graphql_endpoint"]
        != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_ENDPOINT
        or result["credential_account"]
        != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_ACCOUNT
        or result["graphql_query_sha256"]
        != _sha256_text(PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_QUERY)
    ):
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "preflight review-thread broker descriptor semantics are unsupported"
        )
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrMergePreflight],
        Mapping[str, str],
    ],
] = {}


def _mark_authenticated(
    capability: Any,
    preflight: PilotExactTaskPrMergePreflight,
    descriptor: Mapping[str, str],
) -> None:
    key = id(capability)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        capability.sha256,
        weakref.ref(capability, cleanup),
        weakref.ref(preflight),
        descriptor,
    )


def _get_live_pr_merge_preflight_review_thread_credential_capability_inputs(
    capability: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(capability))
    if entry is None:
        return None
    pid, digest, capability_ref, preflight_ref, descriptor = entry
    preflight = preflight_ref()
    if (
        pid != os.getpid()
        or capability_ref() is not capability
        or preflight is None
        or preflight.preflight_authenticated is not True
        or preflight.sha256 != capability.merge_preflight_sha256
        or preflight.review_disposition != "APPROVED"
        or capability.sha256 != digest
        or descriptor.get("broker_policy_sha256") != capability.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256")
        != capability.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256") != capability.broker_executable_sha256
        or descriptor.get("graphql_operation") != capability.graphql_operation
        or descriptor.get("graphql_query_sha256") != capability.graphql_query_sha256
        or _sha256_text(str(descriptor.get("credential_account", "")))
        != capability.credential_account_sha256
    ):
        return None
    return MappingProxyType(
        {
            "merge_preflight": preflight,
            "credential_broker_descriptor": descriptor,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrMergePreflightReviewThreadCredentialCapability:
    merge_preflight_sha256: str
    review_disposition_sha256: str
    submitted_review_observation_sha256: str
    review_observation_checkpoint_sha256: str
    checkpoint_key_sha256: str
    reviewer_handoff_requirements_sha256: str
    source_reviewer_request_attestation_sha256: str
    reviewer_write_transaction_sha256: str
    reviewer_request_nonce_sha256: str
    semantic_pr_title_sha256: str
    semantic_pr_body_sha256: str
    repository: str
    pull_request_number: int
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    source_preflight_second_observed_at_utc: str
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
    merge_preflight_verified: bool = True
    source_approved_review_verified: bool = True
    semantic_metadata_preflight_verified: bool = True
    exact_pr_identity_verified: bool = True
    exact_head_verified: bool = True
    exact_base_verified: bool = True
    exact_author_verified: bool = True
    stable_source_observation_verified: bool = True
    fresh_preflight_age_verified: bool = True
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
    required_status_checks_still_required: bool = True
    branch_policy_still_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA
    credential_scope: str = "preflighted-exact-pr-review-decision-thread-graphql-read-only-v1"

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY
            or self.credential_scope
            != "preflighted-exact-pr-review-decision-thread-graphql-read-only-v1"
        ):
            raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
                "preflight review-thread capability schema/authority/scope unsupported"
            )
        for name in (
            "merge_preflight_sha256",
            "review_disposition_sha256",
            "submitted_review_observation_sha256",
            "review_observation_checkpoint_sha256",
            "checkpoint_key_sha256",
            "reviewer_handoff_requirements_sha256",
            "source_reviewer_request_attestation_sha256",
            "reviewer_write_transaction_sha256",
            "reviewer_request_nonce_sha256",
            "semantic_pr_title_sha256",
            "semantic_pr_body_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "credential_account_sha256",
            "graphql_query_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        source_at = _utc(
            self.source_preflight_second_observed_at_utc,
            name="source_preflight_second_observed_at_utc",
        )
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if (
            materialized < source_at
            or (materialized - source_at).total_seconds()
            > PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_MAX_PREFLIGHT_AGE_SECONDS
        ):
            raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
                "preflight review-thread capability timing is invalid"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or _LOGIN.fullmatch(self.pull_request_author_login) is None
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol
            != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_PROTOCOL
            or self.graphql_operation
            != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_OPERATION
            or self.secret_source
            != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_SOURCE
            or self.secret_transport
            != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_TRANSPORT
            or self.graphql_endpoint
            != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_ENDPOINT
            or self.credential_account_sha256
            != _sha256_text(PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_ACCOUNT)
            or self.graphql_query_sha256
            != _sha256_text(PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_QUERY)
        ):
            raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
                "preflight review-thread capability exact source/broker binding invalid"
            )
        required_true = (
            "merge_preflight_verified",
            "source_approved_review_verified",
            "semantic_metadata_preflight_verified",
            "exact_pr_identity_verified",
            "exact_head_verified",
            "exact_base_verified",
            "exact_author_verified",
            "stable_source_observation_verified",
            "fresh_preflight_age_verified",
            "review_thread_credential_capability_materialized",
            "read_broker_host_pinned",
            "read_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "review_decision_read_only",
            "review_threads_read_only",
            "graphql_queries_only",
            "graphql_mutations_forbidden",
            "graphql_introspection_forbidden",
            "redirect_following_forbidden",
            "rest_review_read_forbidden",
            "other_repository_reads_forbidden",
            "review_submission_write_forbidden",
            "review_dismissal_write_forbidden",
            "review_thread_mutation_forbidden",
            "reviewer_request_write_forbidden",
            "pull_request_create_forbidden",
            "pull_request_metadata_write_forbidden",
            "ready_for_review_write_forbidden",
            "label_write_forbidden",
            "merge_write_forbidden",
            "repository_contents_write_forbidden",
            "administration_write_forbidden",
            "release_write_forbidden",
            "deployment_write_forbidden",
            "review_thread_state_observation_required",
            "required_status_checks_still_required",
            "branch_policy_still_required",
            "fresh_review_reobservation_still_required",
            "fresh_merge_transaction_revalidation_still_required",
        )
        forced_false = (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "nonce_reusable",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "merge_readiness_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
                "preflight review-thread capability evidence incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
                "preflight review-thread capability retains forbidden authority"
            )

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_merge_preflight_review_thread_credential_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPrMergePreflightReviewThreadCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
                "preflight review-thread credential capability must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
                "preflight review-thread credential capability fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_merge_preflight_review_thread_credential_capability(
    *,
    merge_preflight: PilotExactTaskPrMergePreflight,
    broker_descriptor: Mapping[str, str],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrMergePreflightReviewThreadCredentialCapability:
    source, _disposition, _checkpoint = _require_live_merge_preflight(merge_preflight)
    descriptor = _descriptor(broker_descriptor)
    materialized_at = now_provider()
    _require_preflight_window(source, at_utc=materialized_at)
    result = PilotExactTaskPrMergePreflightReviewThreadCredentialCapability(
        merge_preflight_sha256=source.sha256,
        review_disposition_sha256=source.review_disposition_sha256,
        submitted_review_observation_sha256=source.submitted_review_observation_sha256,
        review_observation_checkpoint_sha256=source.review_observation_checkpoint_sha256,
        checkpoint_key_sha256=source.checkpoint_key_sha256,
        reviewer_handoff_requirements_sha256=source.reviewer_handoff_requirements_sha256,
        source_reviewer_request_attestation_sha256=source.source_reviewer_request_attestation_sha256,
        reviewer_write_transaction_sha256=source.reviewer_write_transaction_sha256,
        reviewer_request_nonce_sha256=source.reviewer_request_nonce_sha256,
        semantic_pr_title_sha256=source.semantic_pr_title_sha256,
        semantic_pr_body_sha256=source.semantic_pr_body_sha256,
        repository=source.repository,
        pull_request_number=source.pull_request_number,
        pull_request_node_id_sha256=source.pull_request_node_id_sha256,
        base_branch=source.base_branch,
        head_branch=source.head_branch,
        predicted_commit_sha=source.predicted_commit_sha,
        reviewer_login=source.reviewer_login,
        reviewer_user_id=source.reviewer_user_id,
        reviewer_user_node_id_sha256=source.reviewer_user_node_id_sha256,
        pull_request_author_login=source.pull_request_author_login,
        pull_request_author_user_id=source.pull_request_author_user_id,
        source_preflight_second_observed_at_utc=source.second_observed_at_utc,
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
        raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
            "preflight review-thread capability lost live ADR-DC-080 provenance"
        )
    return result


def materialize_pilot_exact_task_pr_merge_preflight_review_thread_credential_capability(
    merge_preflight: PilotExactTaskPrMergePreflight,
) -> PilotExactTaskPrMergePreflightReviewThreadCredentialCapability:
    """Installed by the host-pinned production boundary at facade import time."""
    raise PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError(
        "preflight review-thread credential production boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_PROTOCOL",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_OPERATION",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_SOURCE",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_SECRET_TRANSPORT",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_ENDPOINT",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_CREDENTIAL_ACCOUNT",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_MAX_PREFLIGHT_AGE_SECONDS",
    "PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_REVIEW_THREAD_GRAPHQL_QUERY",
    "PilotExactTaskPrMergePreflightReviewThreadCredentialCapabilityError",
    "PilotExactTaskPrMergePreflightReviewThreadCredentialCapability",
    "materialize_pilot_exact_task_pr_merge_preflight_review_thread_credential_capability",
]
