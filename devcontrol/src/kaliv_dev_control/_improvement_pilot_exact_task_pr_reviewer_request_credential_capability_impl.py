"""ADR-DC-071 host-pinned credential capability for one reviewer-requestability read.

The capability consumes one exact live ADR-DC-070 identity/ready-PR observation
and binds it to a host-admin-controlled broker descriptor. It loads no secret,
performs no network I/O, and grants no GitHub mutation authority.
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

from . import improvement_pilot_exact_task_pr_reviewer_identity_state_observation as observation_boundary
from . import improvement_pilot_exact_task_pr_reviewer_request_reservation as reservation_boundary
from .improvement_pilot_exact_task_pr_reviewer_identity_state_observation import (
    PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskPrReviewerIdentityStateObservation,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-credential-capability/v1"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY = "host-attested-one-dc-l16-exact-pr-reviewer-requestability-credential-broker-only"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL = "github-rest-reviewer-requestability-broker-v1"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION = "get-collaborator-permission"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE = "host-secret-store-only"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT = "broker-owned-https-only"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN = "https://api.github.com"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT = "Ternedal"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_MAX_OBSERVATION_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PilotExactTaskPrReviewerRequestCredentialCapabilityError(ValueError):
    """Reviewer-request credential capability is unsafe or inconsistent."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability is not canonical JSON") from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(f"{name} is invalid") from exc


def _login(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _LOGIN.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(f"{name} is invalid")
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_observation(value: Any) -> tuple[PilotExactTaskPrReviewerIdentityStateObservation, Any, Any]:
    if type(value) is not PilotExactTaskPrReviewerIdentityStateObservation:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("exact ADR-DC-070 observation is required")
    try:
        replayed = PilotExactTaskPrReviewerIdentityStateObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("ADR-DC-070 replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("ADR-DC-070 observation identity mismatch")
    required_true = (
        "reviewer_public_identity_verified", "reviewer_numeric_user_id_verified",
        "reviewer_not_pr_author_verified", "ready_pr_state_freshly_revalidated",
        "no_requested_reviewers_verified", "credential_free_reads", "redirects_forbidden",
        "responses_bounded", "credentialed_reviewer_requestability_check_required",
        "reviewer_request_credential_capability_required", "reviewer_request_transaction_required",
        "team_reviewers_forbidden",
    )
    forced_false = (
        "reviewer_requestability_verified", "reviewer_mutation_authorized",
        "reviewer_request_performed", "label_mutation_authorized", "merge_authorized",
        "release_authorized", "deploy_authorized", "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig" or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
    ):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability requires one live inert ADR-DC-070 observation")

    inputs = observation_boundary._get_live_pr_reviewer_identity_state_observation_inputs(value)
    reservation = None if inputs is None else inputs.get("reviewer_request_reservation")
    if (
        reservation is None or getattr(reservation, "reservation_authenticated", None) is not True
        or reservation.sha256 != value.reviewer_request_reservation_sha256
        or reservation.reviewer_target_attestation_sha256 != value.reviewer_target_attestation_sha256
        or reservation.reviewer_handoff_requirements_sha256 != value.reviewer_handoff_requirements_sha256
        or reservation.ready_transaction_sha256 != value.ready_transaction_sha256
        or reservation.predicted_commit_sha != value.predicted_commit_sha
        or reservation.reviewer_handoff_plan_sha256 != value.reviewer_handoff_plan_sha256
        or reservation.reviewer_target_policy_sha256 != value.reviewer_target_policy_sha256
        or reservation.reviewer_target_policy_epoch != value.reviewer_target_policy_epoch
        or reservation.ready_for_review_nonce_sha256 != value.ready_for_review_nonce_sha256
        or reservation.reviewer_request_nonce_sha256 != value.reviewer_request_nonce_sha256
        or reservation.reviewer_login != value.reviewer_login
        or reservation.reviewer_user_id != value.reviewer_user_id
        or reservation.pull_request_number != value.pull_request_number
        or reservation.pull_request_node_id_sha256 != value.pull_request_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("ADR-DC-070 lost live reviewer-request reservation provenance")

    reservation_inputs = reservation_boundary._get_live_pr_reviewer_request_reservation_inputs(reservation)
    target = None if reservation_inputs is None else reservation_inputs.get("reviewer_target_attestation")
    if (
        target is None or getattr(target, "attestation_authenticated", None) is not True
        or target.sha256 != value.reviewer_target_attestation_sha256
        or target.reviewer_login != value.reviewer_login
        or target.reviewer_user_id != value.reviewer_user_id
        or target.predicted_commit_sha != value.predicted_commit_sha
        or target.pull_request_number != value.pull_request_number
        or target.pull_request_node_id_sha256 != value.pull_request_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("ADR-DC-070 lost live host-pinned reviewer target")
    return value, reservation, target


def _descriptor(value: Any) -> Mapping[str, str]:
    expected = {
        "broker_policy_sha256", "broker_executable_path", "broker_executable_path_sha256",
        "broker_executable_sha256", "broker_version", "credential_protocol", "operation",
        "secret_source", "secret_transport", "api_origin", "credential_account",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential-broker descriptor fields mismatch")
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential-broker descriptor contains invalid text")
    for name in ("broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256"):
        _hex64(result[name], name=name)
    path = Path(result["broker_executable_path"])
    expected_path_sha256 = hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()
    if not path.is_absolute() or result["broker_executable_path_sha256"] != expected_path_sha256:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential-broker executable path/hash is invalid")
    if _VERSION.fullmatch(result["broker_version"]) is None:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential-broker version is invalid")
    if (
        result["credential_protocol"] != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL
        or result["operation"] != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION
        or result["secret_source"] != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE
        or result["secret_transport"] != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT
        or result["api_origin"] != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN
        or result["credential_account"] != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT
    ):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential-broker semantics are unsupported")
    return MappingProxyType(result)


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], Mapping[str, str]]] = {}


def _mark_pr_reviewer_request_credential_capability_authenticated(capability: Any, observation: Any, descriptor: Mapping[str, str]) -> None:
    key = id(capability)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), capability.sha256, weakref.ref(capability, cleanup), weakref.ref(observation), descriptor)


def _get_live_pr_reviewer_request_credential_capability_inputs(capability: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(capability))
    if entry is None:
        return None
    pid, digest, capability_ref, observation_ref, descriptor = entry
    observation = observation_ref()
    if (
        pid != os.getpid() or capability_ref() is not capability or observation is None
        or observation.observation_authenticated is not True
        or observation.sha256 != capability.reviewer_identity_state_observation_sha256
        or capability.sha256 != digest
        or descriptor.get("broker_policy_sha256") != capability.broker_policy_sha256
        or descriptor.get("broker_executable_sha256") != capability.broker_executable_sha256
        or descriptor.get("operation") != capability.credential_operation
    ):
        return None
    return MappingProxyType({"reviewer_identity_state_observation": observation, "credential_broker_descriptor": descriptor})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestCredentialCapability:
    reviewer_identity_state_observation_sha256: str
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    ready_transaction_sha256: str
    predicted_commit_sha: str
    reviewer_handoff_plan_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    ready_for_review_nonce_sha256: str
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    ready_updated_at_utc: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    observation_observed_at_utc: str
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
    materialized_at_utc: str
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_reserved: bool = True
    reviewer_identity_verified: bool = True
    ready_pr_state_freshly_revalidated: bool = True
    no_requested_reviewers_verified: bool = True
    reviewer_requestability_verified: bool = False
    credentialed_reviewer_requestability_check_required: bool = True
    credential_broker_host_pinned: bool = True
    credential_broker_binary_verified: bool = True
    credential_account_host_pinned: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    exact_read_only_permission_operation_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY:
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability schema/authority is unsupported")
        for name in (
            "reviewer_identity_state_observation_sha256", "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256", "reviewer_handoff_requirements_sha256",
            "ready_transaction_sha256", "reviewer_handoff_plan_sha256", "reviewer_target_policy_sha256",
            "ready_for_review_nonce_sha256", "reviewer_request_nonce_sha256", "pull_request_node_id_sha256",
            "reviewer_node_id_sha256", "broker_policy_sha256", "broker_executable_path_sha256",
            "broker_executable_sha256", "credential_account_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _login(self.reviewer_login, name="reviewer_login")
        _login(self.pull_request_author_login, name="pull_request_author_login")
        observed = _utc(self.observation_observed_at_utc, name="observation_observed_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        _utc(self.ready_updated_at_utc, name="ready_updated_at_utc")
        if materialized < observed:
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability predates ADR-DC-070 observation")
        account_sha = hashlib.sha256(PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT.encode("utf-8")).hexdigest()
        if (
            isinstance(self.reviewer_target_policy_epoch, bool) or not isinstance(self.reviewer_target_policy_epoch, int) or self.reviewer_target_policy_epoch < 1
            or isinstance(self.reviewer_user_id, bool) or not isinstance(self.reviewer_user_id, int) or self.reviewer_user_id < 1
            or isinstance(self.pull_request_author_user_id, bool) or not isinstance(self.pull_request_author_user_id, int) or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.repository != "Ternedal/ModelRig" or self.base_branch != "main" or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or self.pull_request_api_url != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL
            or self.credential_operation != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION
            or self.secret_source != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE
            or self.secret_transport != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT
            or self.api_origin != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN
            or self.credential_account_sha256 != account_sha
        ):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability target/broker binding is invalid")
        required_true = (
            "reviewer_request_authorization_consumed", "reviewer_request_slot_reserved",
            "reviewer_identity_verified", "ready_pr_state_freshly_revalidated",
            "no_requested_reviewers_verified", "credentialed_reviewer_requestability_check_required",
            "credential_broker_host_pinned", "credential_broker_binary_verified",
            "credential_account_host_pinned", "credential_secret_not_loaded",
            "credential_broker_owns_https", "exact_read_only_permission_operation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required", "team_reviewers_forbidden",
        )
        forced_false = (
            "reviewer_requestability_verified", "credential_material_in_artifact",
            "credential_material_in_process_arguments", "credential_material_in_environment",
            "reviewer_mutation_authorized", "reviewer_request_performed",
            "label_mutation_authorized", "merge_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability cannot grant GitHub mutation authority")

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_reviewer_request_credential_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerRequestCredentialCapability":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
    *,
    reviewer_identity_state_observation: PilotExactTaskPrReviewerIdentityStateObservation,
    broker_descriptor: Mapping[str, Any],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerRequestCredentialCapability:
    observation, reservation, target = _require_live_observation(reviewer_identity_state_observation)
    descriptor = _descriptor(broker_descriptor)
    materialized_at = now_provider()
    materialized = _utc(materialized_at, name="materialized_at_utc")
    observed = _utc(observation.observed_at_utc, name="observation observed_at_utc")
    if materialized < observed or (materialized - observed).total_seconds() > PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_MAX_OBSERVATION_AGE_SECONDS:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability is too far from fresh ADR-DC-070 observation")
    result = PilotExactTaskPrReviewerRequestCredentialCapability(
        reviewer_identity_state_observation_sha256=observation.sha256,
        reviewer_request_reservation_sha256=observation.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=observation.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=observation.reviewer_handoff_requirements_sha256,
        ready_transaction_sha256=observation.ready_transaction_sha256,
        predicted_commit_sha=observation.predicted_commit_sha,
        reviewer_handoff_plan_sha256=observation.reviewer_handoff_plan_sha256,
        reviewer_target_policy_sha256=observation.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=observation.reviewer_target_policy_epoch,
        ready_for_review_nonce_sha256=observation.ready_for_review_nonce_sha256,
        reviewer_request_nonce_sha256=observation.reviewer_request_nonce_sha256,
        repository=observation.repository,
        pull_request_number=observation.pull_request_number,
        pull_request_api_url=observation.pull_request_api_url,
        pull_request_html_url=observation.pull_request_html_url,
        pull_request_node_id_sha256=observation.pull_request_node_id_sha256,
        base_branch=observation.base_branch,
        head_branch=observation.head_branch,
        ready_updated_at_utc=observation.ready_updated_at_utc,
        reviewer_login=observation.reviewer_login,
        reviewer_user_id=observation.reviewer_user_id,
        reviewer_node_id_sha256=observation.reviewer_node_id_sha256,
        pull_request_author_login=observation.pull_request_author_login,
        pull_request_author_user_id=observation.pull_request_author_user_id,
        observation_observed_at_utc=observation.observed_at_utc,
        broker_policy_sha256=descriptor["broker_policy_sha256"],
        broker_executable_path_sha256=descriptor["broker_executable_path_sha256"],
        broker_executable_sha256=descriptor["broker_executable_sha256"],
        broker_version=descriptor["broker_version"],
        credential_protocol=descriptor["credential_protocol"],
        credential_operation=descriptor["operation"],
        secret_source=descriptor["secret_source"],
        secret_transport=descriptor["secret_transport"],
        api_origin=descriptor["api_origin"],
        credential_account_sha256=hashlib.sha256(descriptor["credential_account"].encode("utf-8")).hexdigest(),
        materialized_at_utc=materialized_at,
    )
    if reservation.sha256 != result.reviewer_request_reservation_sha256 or target.sha256 != result.reviewer_target_attestation_sha256:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability lost exact live provenance")
    _mark_pr_reviewer_request_credential_capability_authenticated(result, observation, descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("credential capability lost live observation provenance")
    return result


def materialize_pilot_exact_task_pr_reviewer_request_credential_capability(
    reviewer_identity_state_observation: PilotExactTaskPrReviewerIdentityStateObservation,
) -> PilotExactTaskPrReviewerRequestCredentialCapability:
    raise PilotExactTaskPrReviewerRequestCredentialCapabilityError("production credential capability boundary is not installed")


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_MAX_OBSERVATION_AGE_SECONDS",
    "PilotExactTaskPrReviewerRequestCredentialCapabilityError",
    "PilotExactTaskPrReviewerRequestCredentialCapability",
    "materialize_pilot_exact_task_pr_reviewer_request_credential_capability",
]
