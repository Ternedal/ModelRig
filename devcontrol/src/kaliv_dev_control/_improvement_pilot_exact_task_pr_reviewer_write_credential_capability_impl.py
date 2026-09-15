"""ADR-DC-074 host-pinned write-only capability for one reviewer request.

Consumes one exact live ADR-DC-073 reviewer-request preflight and binds it to a
separate host-admin-controlled broker that may perform only the exact
single-individual-reviewer request operation in a later transaction boundary.
This capability loads no secret, starts no subprocess, performs no network I/O,
and grants no mutation authority by itself.
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

from . import improvement_pilot_exact_task_pr_reviewer_request_preflight as preflight_boundary
from .improvement_pilot_exact_task_pr_reviewer_request_preflight import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_AUTHORITY,
    PilotExactTaskPrReviewerRequestPreflight,
)

PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-write-credential-capability/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-exact-pr-reviewer-write-credential-broker-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_PROTOCOL = (
    "github-rest-reviewer-write-broker-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION = (
    "request-pull-request-reviewer"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_SECRET_SOURCE = (
    "host-secret-store-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_SECRET_TRANSPORT = (
    "broker-owned-https-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_API_ORIGIN = "https://api.github.com"
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_ACCOUNT = "Ternedal"
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_REQUEST_PATH_TEMPLATE = (
    "/repos/Ternedal/ModelRig/pulls/{pull_request_number}/requested_reviewers"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_MAX_PREFLIGHT_AGE_SECONDS = 15

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ALLOWED_PERMISSIONS = frozenset({"read", "write", "admin"})


class PilotExactTaskPrReviewerWriteCredentialCapabilityError(ValueError):
    """Reviewer-write credential capability is stale, unsafe, or unbound."""


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
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "reviewer-write capability is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_preflight(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerRequestPreflight, Any]:
    if type(value) is not PilotExactTaskPrReviewerRequestPreflight:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "exact ADR-DC-073 reviewer-request preflight is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestPreflight.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "ADR-DC-073 preflight replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "ADR-DC-073 preflight identity mismatch"
        )

    required_true = (
        "reviewer_request_authorization_consumed",
        "reviewer_request_slot_reserved",
        "reviewer_identity_verified",
        "reviewer_requestability_precondition_verified",
        "fresh_exact_pr_state_revalidated",
        "no_requested_reviewers_verified",
        "reviewer_not_pr_author_verified",
        "credential_free_pr_read",
        "redirects_forbidden",
        "response_bounded",
        "reviewer_write_credential_capability_required",
        "one_shot_reviewer_request_transaction_required",
        "post_request_readback_verification_required",
        "team_reviewers_forbidden",
    )
    forced_false = (
        "reviewer_mutation_authorized",
        "reviewer_request_performed",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PREFLIGHT_AUTHORITY
        or value.observation_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or value.repository_permission not in _ALLOWED_PERMISSIONS
        or value.pull_request_author_user_id == value.reviewer_user_id
        or value.pull_request_author_login.lower() == value.reviewer_login.lower()
    ):
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "write capability requires one live inert ADR-DC-073 preflight"
        )

    live = preflight_boundary._get_live_pr_reviewer_request_preflight_inputs(value)
    precondition = (
        None if live is None else live.get("reviewer_requestability_precondition")
    )
    if (
        precondition is None
        or getattr(precondition, "observation_authenticated", None) is not True
        or precondition.sha256 != value.reviewer_requestability_precondition_sha256
        or precondition.reviewer_request_nonce_sha256
        != value.reviewer_request_nonce_sha256
        or precondition.pull_request_number != value.pull_request_number
        or precondition.predicted_commit_sha != value.predicted_commit_sha
        or precondition.reviewer_login != value.reviewer_login
        or precondition.reviewer_user_id != value.reviewer_user_id
        or precondition.reviewer_user_node_id_sha256
        != value.reviewer_user_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "ADR-DC-073 lost live ADR-DC-072 provenance"
        )
    return value, precondition


def _require_preflight_window(
    preflight: PilotExactTaskPrReviewerRequestPreflight,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="materialized_at_utc")
    observed = _utc(preflight.observed_at_utc, name="preflight_observed_at_utc")
    if (
        at < observed
        or (at - observed).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEWER_WRITE_MAX_PREFLIGHT_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "ADR-DC-073 preflight is too old for reviewer-write capability"
        )


def _descriptor(value: Any) -> Mapping[str, str]:
    expected = {
        "broker_policy_sha256",
        "broker_executable_path",
        "broker_executable_path_sha256",
        "broker_executable_sha256",
        "broker_version",
        "credential_protocol",
        "operation",
        "secret_source",
        "secret_transport",
        "api_origin",
        "credential_account",
        "request_path_template",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "reviewer-write broker descriptor fields mismatch"
        )
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "reviewer-write broker descriptor contains invalid text"
        )
    for name in (
        "broker_policy_sha256",
        "broker_executable_path_sha256",
        "broker_executable_sha256",
    ):
        _hex64(result[name], name=name)

    path = Path(result["broker_executable_path"])
    expected_path_sha256 = hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(path)))
    ).hexdigest()
    if (
        not path.is_absolute()
        or result["broker_executable_path_sha256"] != expected_path_sha256
        or _VERSION.fullmatch(result["broker_version"]) is None
        or result["credential_protocol"]
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_PROTOCOL
        or result["operation"]
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION
        or result["secret_source"]
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_SECRET_SOURCE
        or result["secret_transport"]
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_SECRET_TRANSPORT
        or result["api_origin"]
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_API_ORIGIN
        or result["credential_account"]
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_ACCOUNT
        or result["request_path_template"]
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_REQUEST_PATH_TEMPLATE
    ):
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "reviewer-write broker descriptor semantics are unsupported"
        )
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerRequestPreflight],
        Mapping[str, str],
    ],
] = {}


def _mark_authenticated(
    capability: Any,
    preflight: PilotExactTaskPrReviewerRequestPreflight,
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


def _get_live_pr_reviewer_write_credential_capability_inputs(
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
        or preflight.observation_authenticated is not True
        or preflight.sha256 != capability.reviewer_request_preflight_sha256
        or capability.sha256 != digest
        or descriptor.get("broker_policy_sha256") != capability.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256")
        != capability.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256")
        != capability.broker_executable_sha256
        or descriptor.get("operation") != capability.credential_operation
        or hashlib.sha256(
            str(descriptor.get("credential_account", "")).encode("utf-8")
        ).hexdigest()
        != capability.credential_account_sha256
        or hashlib.sha256(
            str(descriptor.get("request_path_template", "")).encode("utf-8")
        ).hexdigest()
        != capability.request_path_template_sha256
    ):
        return None
    return MappingProxyType(
        {
            "reviewer_request_preflight": preflight,
            "credential_broker_descriptor": descriptor,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerWriteCredentialCapability:
    reviewer_request_preflight_sha256: str
    reviewer_requestability_precondition_sha256: str
    reviewer_request_credential_capability_sha256: str
    reviewer_identity_observation_sha256: str
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
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
    repository_permission: str
    repository_role_name_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    fresh_pr_response_body_sha256: str
    fresh_pr_response_etag_sha256: str
    fresh_pr_state_observed_at_utc: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    credential_operation: str
    secret_source: str
    secret_transport: str
    api_origin: str
    credential_account_sha256: str
    request_path_template_sha256: str
    materialized_at_utc: str
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_reserved: bool = True
    reviewer_identity_verified: bool = True
    reviewer_requestability_precondition_verified: bool = True
    fresh_exact_pr_state_revalidated: bool = True
    no_requested_reviewers_verified: bool = True
    reviewer_not_pr_author_verified: bool = True
    reviewer_write_credential_capability_materialized: bool = True
    write_broker_host_pinned: bool = True
    write_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    individual_reviewer_write_only: bool = True
    team_reviewers_forbidden: bool = True
    collaborator_permission_read_forbidden: bool = True
    other_repository_reads_forbidden: bool = True
    pull_request_create_forbidden: bool = True
    pull_request_metadata_write_forbidden: bool = True
    ready_for_review_write_forbidden: bool = True
    label_write_forbidden: bool = True
    merge_write_forbidden: bool = True
    repository_contents_write_forbidden: bool = True
    administration_write_forbidden: bool = True
    release_write_forbidden: bool = True
    deployment_write_forbidden: bool = True
    redirect_following_forbidden: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    one_shot_reviewer_request_transaction_required: bool = True
    post_request_readback_verification_required: bool = True
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_AUTHORITY
        ):
            raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
                "reviewer-write capability schema/authority is unsupported"
            )

        for name in (
            "reviewer_request_preflight_sha256",
            "reviewer_requestability_precondition_sha256",
            "reviewer_request_credential_capability_sha256",
            "reviewer_identity_observation_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "repository_role_name_sha256",
            "fresh_pr_response_body_sha256",
            "fresh_pr_response_etag_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "credential_account_sha256",
            "request_path_template_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")

        preflight_observed = _utc(
            self.fresh_pr_state_observed_at_utc,
            name="fresh_pr_state_observed_at_utc",
        )
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if (
            materialized < preflight_observed
            or (materialized - preflight_observed).total_seconds()
            > PILOT_EXACT_TASK_PR_REVIEWER_WRITE_MAX_PREFLIGHT_AGE_SECONDS
        ):
            raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
                "reviewer-write capability materialization is stale"
            )

        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or _LOGIN.fullmatch(self.pull_request_author_login) is None
            or self.repository_permission not in _ALLOWED_PERMISSIONS
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
            or isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol
            != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_PROTOCOL
            or self.credential_operation
            != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION
            or self.secret_source
            != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_SECRET_SOURCE
            or self.secret_transport
            != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_SECRET_TRANSPORT
            or self.api_origin
            != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_API_ORIGIN
            or self.credential_account_sha256
            != hashlib.sha256(
                PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_ACCOUNT.encode("utf-8")
            ).hexdigest()
            or self.request_path_template_sha256
            != hashlib.sha256(
                PILOT_EXACT_TASK_PR_REVIEWER_WRITE_REQUEST_PATH_TEMPLATE.encode("utf-8")
            ).hexdigest()
        ):
            raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
                "reviewer-write capability binding is invalid"
            )

        required_true = (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "reviewer_requestability_precondition_verified",
            "fresh_exact_pr_state_revalidated",
            "no_requested_reviewers_verified",
            "reviewer_not_pr_author_verified",
            "reviewer_write_credential_capability_materialized",
            "write_broker_host_pinned",
            "write_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "individual_reviewer_write_only",
            "team_reviewers_forbidden",
            "collaborator_permission_read_forbidden",
            "other_repository_reads_forbidden",
            "pull_request_create_forbidden",
            "pull_request_metadata_write_forbidden",
            "ready_for_review_write_forbidden",
            "label_write_forbidden",
            "merge_write_forbidden",
            "repository_contents_write_forbidden",
            "administration_write_forbidden",
            "release_write_forbidden",
            "deployment_write_forbidden",
            "redirect_following_forbidden",
            "one_shot_reviewer_request_transaction_required",
            "post_request_readback_verification_required",
        )
        forced_false = (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
                "reviewer-write capability safety evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
                "reviewer-write capability cannot itself grant mutation authority"
            )

    @property
    def capability_authenticated(self) -> bool:
        return (
            _get_live_pr_reviewer_write_credential_capability_inputs(self)
            is not None
        )

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
        cls,
        value: Any,
    ) -> "PilotExactTaskPrReviewerWriteCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
                "reviewer-write capability must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
                "reviewer-write capability fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_reviewer_write_credential_capability(
    *,
    reviewer_request_preflight: PilotExactTaskPrReviewerRequestPreflight,
    broker_descriptor: Mapping[str, str],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerWriteCredentialCapability:
    preflight, _precondition = _require_live_preflight(reviewer_request_preflight)
    materialized_at = now_provider()
    _require_preflight_window(preflight, at_utc=materialized_at)
    descriptor = _descriptor(broker_descriptor)

    result = PilotExactTaskPrReviewerWriteCredentialCapability(
        reviewer_request_preflight_sha256=preflight.sha256,
        reviewer_requestability_precondition_sha256=preflight.reviewer_requestability_precondition_sha256,
        reviewer_request_credential_capability_sha256=preflight.reviewer_request_credential_capability_sha256,
        reviewer_identity_observation_sha256=preflight.reviewer_identity_observation_sha256,
        reviewer_request_reservation_sha256=preflight.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=preflight.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=preflight.reviewer_handoff_requirements_sha256,
        reviewer_target_policy_sha256=preflight.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=preflight.reviewer_target_policy_epoch,
        reviewer_request_nonce_sha256=preflight.reviewer_request_nonce_sha256,
        repository=preflight.repository,
        pull_request_number=preflight.pull_request_number,
        pull_request_api_url=preflight.pull_request_api_url,
        pull_request_html_url=preflight.pull_request_html_url,
        pull_request_node_id_sha256=preflight.pull_request_node_id_sha256,
        base_branch=preflight.base_branch,
        head_branch=preflight.head_branch,
        predicted_commit_sha=preflight.predicted_commit_sha,
        reviewer_login=preflight.reviewer_login,
        reviewer_user_id=preflight.reviewer_user_id,
        reviewer_user_node_id_sha256=preflight.reviewer_user_node_id_sha256,
        repository_permission=preflight.repository_permission,
        repository_role_name_sha256=preflight.repository_role_name_sha256,
        pull_request_author_login=preflight.pull_request_author_login,
        pull_request_author_user_id=preflight.pull_request_author_user_id,
        fresh_pr_response_body_sha256=preflight.fresh_pr_response_body_sha256,
        fresh_pr_response_etag_sha256=preflight.fresh_pr_response_etag_sha256,
        fresh_pr_state_observed_at_utc=preflight.observed_at_utc,
        broker_policy_sha256=descriptor["broker_policy_sha256"],
        broker_executable_path_sha256=descriptor["broker_executable_path_sha256"],
        broker_executable_sha256=descriptor["broker_executable_sha256"],
        broker_version=descriptor["broker_version"],
        credential_protocol=descriptor["credential_protocol"],
        credential_operation=descriptor["operation"],
        secret_source=descriptor["secret_source"],
        secret_transport=descriptor["secret_transport"],
        api_origin=descriptor["api_origin"],
        credential_account_sha256=hashlib.sha256(
            descriptor["credential_account"].encode("utf-8")
        ).hexdigest(),
        request_path_template_sha256=hashlib.sha256(
            descriptor["request_path_template"].encode("utf-8")
        ).hexdigest(),
        materialized_at_utc=materialized_at,
    )
    _mark_authenticated(result, preflight, descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
            "reviewer-write capability lost live ADR-DC-073 provenance"
        )
    return result


def materialize_pilot_exact_task_pr_reviewer_write_credential_capability(
    reviewer_request_preflight: PilotExactTaskPrReviewerRequestPreflight,
) -> PilotExactTaskPrReviewerWriteCredentialCapability:
    raise PilotExactTaskPrReviewerWriteCredentialCapabilityError(
        "production reviewer-write credential boundary is not installed"
    )
