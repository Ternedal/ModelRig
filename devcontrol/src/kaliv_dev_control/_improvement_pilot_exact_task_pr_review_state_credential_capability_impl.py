"""ADR-DC-077 host-pinned read-only credential capability for exact PR review state.

Consumes one exact live ADR-DC-076 post-reviewer-request attestation and binds it
to a separate host-admin-controlled broker that may later perform only bounded
read operations for submitted pull-request reviews and GraphQL review-state /
review-thread evidence. This capability loads no secret, starts no subprocess,
performs no network I/O, and grants no review, thread, merge, or other mutation
authority.
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

from . import improvement_pilot_exact_task_pr_reviewer_request_attestation as attestation_boundary
from .improvement_pilot_exact_task_pr_reviewer_request_attestation import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY,
    PilotExactTaskPrReviewerRequestAttestation,
)

PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-review-state-credential-capability/v1"
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-exact-pr-review-state-read-credential-broker-only"
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL = (
    "github-review-state-read-broker-v1"
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION = "list-pull-request-reviews"
PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION = (
    "query-pull-request-review-state"
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE = "host-secret-store-only"
PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT = "broker-owned-https-only"
PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN = "https://api.github.com"
PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT = "Ternedal"
PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE = (
    "/repos/Ternedal/ModelRig/pulls/{pull_request_number}/reviews"
)
PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY = (
    "query ModelRigExactPullRequestReviewState($owner:String!,$name:String!,"
    "$number:Int!,$threadsCursor:String){repository(owner:$owner,name:$name){"
    "pullRequest(number:$number){id reviewDecision reviewThreads(first:100,"
    "after:$threadsCursor){nodes{id isResolved isOutdated path}pageInfo{"
    "hasNextPage endCursor}}}}}"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PilotExactTaskPrReviewStateCredentialCapabilityError(ValueError):
    """Review-state credential capability is unsafe, substituted, or unbound."""


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
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "review-state credential capability is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(path)))
    ).hexdigest()


def _require_live_attestation(
    value: Any,
) -> PilotExactTaskPrReviewerRequestAttestation:
    if type(value) is not PilotExactTaskPrReviewerRequestAttestation:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "exact live ADR-DC-076 reviewer-request attestation is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestAttestation.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "ADR-DC-076 attestation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "ADR-DC-076 attestation identity mismatch"
        )

    required_true = (
        "reviewer_request_performed_verified",
        "exact_requested_reviewer_verified",
        "team_reviewers_absent_verified",
        "exact_pr_state_verified",
        "stable_double_observation_verified",
        "credential_free_reads",
        "redirects_forbidden",
        "response_bounded",
        "review_state_attestation_required",
    )
    forced_false = (
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
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _LOGIN.fullmatch(value.reviewer_login) is None
        or value.pull_request_author_user_id == value.reviewer_user_id
        or value.pull_request_author_login.lower() == value.reviewer_login.lower()
    ):
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "review-state capability requires one live inert ADR-DC-076 attestation"
        )

    live = attestation_boundary._get_live_pr_reviewer_request_attestation_inputs(value)
    transaction = None if live is None else live.get("reviewer_write_transaction")
    if (
        transaction is None
        or getattr(transaction, "transaction_authenticated", None) is not True
        or transaction.sha256 != value.reviewer_write_transaction_sha256
        or transaction.reviewer_request_nonce_sha256
        != value.reviewer_request_nonce_sha256
        or transaction.pull_request_number != value.pull_request_number
        or transaction.predicted_commit_sha != value.predicted_commit_sha
        or transaction.reviewer_login != value.reviewer_login
        or transaction.reviewer_user_id != value.reviewer_user_id
        or transaction.pull_request_author_login != value.pull_request_author_login
        or transaction.pull_request_author_user_id != value.pull_request_author_user_id
    ):
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "ADR-DC-076 lost exact live ADR-DC-075 provenance"
        )
    return value


def _descriptor(value: Any) -> Mapping[str, str]:
    expected = {
        "broker_policy_sha256",
        "broker_executable_path",
        "broker_executable_path_sha256",
        "broker_executable_sha256",
        "broker_version",
        "credential_protocol",
        "rest_operation",
        "graphql_operation",
        "secret_source",
        "secret_transport",
        "api_origin",
        "graphql_endpoint",
        "credential_account",
        "reviews_path_template",
        "graphql_query_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "review-state broker descriptor fields mismatch"
        )
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "review-state broker descriptor contains invalid text"
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
        != PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL
        or result["rest_operation"]
        != PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION
        or result["graphql_operation"]
        != PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION
        or result["secret_source"] != PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE
        or result["secret_transport"]
        != PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT
        or result["api_origin"] != PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN
        or result["graphql_endpoint"]
        != PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT
        or result["credential_account"]
        != PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT
        or result["reviews_path_template"]
        != PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE
        or result["graphql_query_sha256"]
        != _sha256_text(PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY)
    ):
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "review-state broker descriptor semantics are unsupported"
        )
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerRequestAttestation],
        Mapping[str, str],
    ],
] = {}


def _mark_authenticated(
    capability: Any,
    attestation: PilotExactTaskPrReviewerRequestAttestation,
    descriptor: Mapping[str, str],
) -> None:
    key = id(capability)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        capability.sha256,
        weakref.ref(capability, cleanup),
        weakref.ref(attestation),
        descriptor,
    )


def _get_live_pr_review_state_credential_capability_inputs(
    capability: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(capability))
    if entry is None:
        return None
    pid, digest, capability_ref, attestation_ref, descriptor = entry
    attestation = attestation_ref()
    if (
        pid != os.getpid()
        or capability_ref() is not capability
        or attestation is None
        or attestation.attestation_authenticated is not True
        or attestation.sha256 != capability.reviewer_request_attestation_sha256
        or capability.sha256 != digest
        or descriptor.get("broker_policy_sha256") != capability.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256")
        != capability.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256")
        != capability.broker_executable_sha256
        or descriptor.get("rest_operation") != capability.rest_operation
        or descriptor.get("graphql_operation") != capability.graphql_operation
        or _sha256_text(str(descriptor.get("credential_account", "")))
        != capability.credential_account_sha256
        or _sha256_text(str(descriptor.get("reviews_path_template", "")))
        != capability.reviews_path_template_sha256
        or descriptor.get("graphql_query_sha256") != capability.graphql_query_sha256
    ):
        return None
    return MappingProxyType(
        {
            "reviewer_request_attestation": attestation,
            "credential_broker_descriptor": descriptor,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewStateCredentialCapability:
    reviewer_request_attestation_sha256: str
    reviewer_write_transaction_sha256: str
    transaction_start_sha256: str
    reviewer_write_credential_capability_sha256: str
    reviewer_request_preflight_sha256: str
    reviewer_requestability_precondition_sha256: str
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    requested_updated_at_utc: str
    stable_post_request_response_body_sha256: str
    stable_post_request_response_etag_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    rest_operation: str
    graphql_operation: str
    secret_source: str
    secret_transport: str
    api_origin: str
    graphql_endpoint: str
    credential_account_sha256: str
    reviews_path_template_sha256: str
    graphql_query_sha256: str
    materialized_at_utc: str
    post_reviewer_request_attestation_verified: bool = True
    reviewer_request_performed_verified: bool = True
    exact_requested_reviewer_verified: bool = True
    team_reviewers_absent_verified: bool = True
    exact_pr_state_verified: bool = True
    review_state_credential_capability_materialized: bool = True
    read_broker_host_pinned: bool = True
    read_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    reviews_read_only: bool = True
    review_threads_read_only: bool = True
    review_decision_read_only: bool = True
    graphql_queries_only: bool = True
    graphql_mutations_forbidden: bool = True
    graphql_introspection_forbidden: bool = True
    redirect_following_forbidden: bool = True
    collaborator_permission_read_forbidden: bool = True
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
    review_state_observation_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_SCHEMA
    credential_scope: str = "exact-pr-review-state-read-only-v1"

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_AUTHORITY
            or self.credential_scope != "exact-pr-review-state-read-only-v1"
        ):
            raise PilotExactTaskPrReviewStateCredentialCapabilityError(
                "review-state capability schema/authority/scope unsupported"
            )
        for name in (
            "reviewer_request_attestation_sha256",
            "reviewer_write_transaction_sha256",
            "transaction_start_sha256",
            "reviewer_write_credential_capability_sha256",
            "reviewer_request_preflight_sha256",
            "reviewer_requestability_precondition_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "stable_post_request_response_body_sha256",
            "stable_post_request_response_etag_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "credential_account_sha256",
            "reviews_path_template_sha256",
            "graphql_query_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        observed = _utc(self.requested_updated_at_utc, name="requested_updated_at_utc")
        if materialized < observed:
            raise PilotExactTaskPrReviewStateCredentialCapabilityError(
                "review-state capability predates exact reviewer-request state"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
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
            != PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL
            or self.rest_operation != PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION
            or self.graphql_operation
            != PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION
            or self.secret_source != PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE
            or self.secret_transport
            != PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT
            or self.api_origin != PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN
            or self.graphql_endpoint
            != PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT
            or self.credential_account_sha256
            != _sha256_text(PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT)
            or self.reviews_path_template_sha256
            != _sha256_text(PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE)
            or self.graphql_query_sha256
            != _sha256_text(PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY)
        ):
            raise PilotExactTaskPrReviewStateCredentialCapabilityError(
                "review-state capability exact target/broker binding invalid"
            )

        required_true = (
            "post_reviewer_request_attestation_verified",
            "reviewer_request_performed_verified",
            "exact_requested_reviewer_verified",
            "team_reviewers_absent_verified",
            "exact_pr_state_verified",
            "review_state_credential_capability_materialized",
            "read_broker_host_pinned",
            "read_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "reviews_read_only",
            "review_threads_read_only",
            "review_decision_read_only",
            "graphql_queries_only",
            "graphql_mutations_forbidden",
            "graphql_introspection_forbidden",
            "redirect_following_forbidden",
            "collaborator_permission_read_forbidden",
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
            "review_state_observation_required",
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
            raise PilotExactTaskPrReviewStateCredentialCapabilityError(
                "review-state credential capability evidence incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewStateCredentialCapabilityError(
                "review-state credential capability retains forbidden authority"
            )

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_review_state_credential_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPrReviewStateCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewStateCredentialCapabilityError(
                "review-state credential capability must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewStateCredentialCapabilityError(
                "review-state credential capability fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_review_state_credential_capability(
    *,
    reviewer_request_attestation: PilotExactTaskPrReviewerRequestAttestation,
    broker_descriptor: Mapping[str, str],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewStateCredentialCapability:
    source = _require_live_attestation(reviewer_request_attestation)
    descriptor = _descriptor(broker_descriptor)
    materialized_at = now_provider()
    materialized = _utc(materialized_at, name="materialized_at_utc")
    second_observed = _utc(
        source.second_observed_at_utc,
        name="source_second_observed_at_utc",
    )
    if materialized < second_observed:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "clock moved backwards before review-state capability materialization"
        )

    result = PilotExactTaskPrReviewStateCredentialCapability(
        reviewer_request_attestation_sha256=source.sha256,
        reviewer_write_transaction_sha256=source.reviewer_write_transaction_sha256,
        transaction_start_sha256=source.transaction_start_sha256,
        reviewer_write_credential_capability_sha256=source.reviewer_write_credential_capability_sha256,
        reviewer_request_preflight_sha256=source.reviewer_request_preflight_sha256,
        reviewer_requestability_precondition_sha256=source.reviewer_requestability_precondition_sha256,
        reviewer_request_reservation_sha256=source.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=source.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=source.reviewer_handoff_requirements_sha256,
        reviewer_request_nonce_sha256=source.reviewer_request_nonce_sha256,
        repository=source.repository,
        pull_request_number=source.pull_request_number,
        pull_request_api_url=source.pull_request_api_url,
        pull_request_html_url=source.pull_request_html_url,
        pull_request_node_id_sha256=source.pull_request_node_id_sha256,
        base_branch=source.base_branch,
        head_branch=source.head_branch,
        predicted_commit_sha=source.predicted_commit_sha,
        reviewer_login=source.reviewer_login,
        reviewer_user_id=source.reviewer_user_id,
        reviewer_user_node_id_sha256=source.reviewer_user_node_id_sha256,
        pull_request_author_login=source.pull_request_author_login,
        pull_request_author_user_id=source.pull_request_author_user_id,
        requested_updated_at_utc=source.requested_updated_at_utc,
        stable_post_request_response_body_sha256=source.second_response_body_sha256,
        stable_post_request_response_etag_sha256=source.second_response_etag_sha256,
        broker_policy_sha256=descriptor["broker_policy_sha256"],
        broker_executable_path_sha256=descriptor["broker_executable_path_sha256"],
        broker_executable_sha256=descriptor["broker_executable_sha256"],
        broker_version=descriptor["broker_version"],
        credential_protocol=descriptor["credential_protocol"],
        rest_operation=descriptor["rest_operation"],
        graphql_operation=descriptor["graphql_operation"],
        secret_source=descriptor["secret_source"],
        secret_transport=descriptor["secret_transport"],
        api_origin=descriptor["api_origin"],
        graphql_endpoint=descriptor["graphql_endpoint"],
        credential_account_sha256=_sha256_text(descriptor["credential_account"]),
        reviews_path_template_sha256=_sha256_text(descriptor["reviews_path_template"]),
        graphql_query_sha256=descriptor["graphql_query_sha256"],
        materialized_at_utc=materialized_at,
    )
    _mark_authenticated(result, source, descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrReviewStateCredentialCapabilityError(
            "review-state credential capability lost live ADR-DC-076 provenance"
        )
    return result


def materialize_pilot_exact_task_pr_review_state_credential_capability(
    reviewer_request_attestation: PilotExactTaskPrReviewerRequestAttestation,
) -> PilotExactTaskPrReviewStateCredentialCapability:
    """Installed by the host-pinned production boundary at facade import time."""
    raise PilotExactTaskPrReviewStateCredentialCapabilityError(
        "review-state credential production boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE",
    "PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY",
    "PilotExactTaskPrReviewStateCredentialCapabilityError",
    "PilotExactTaskPrReviewStateCredentialCapability",
    "materialize_pilot_exact_task_pr_review_state_credential_capability",
]
