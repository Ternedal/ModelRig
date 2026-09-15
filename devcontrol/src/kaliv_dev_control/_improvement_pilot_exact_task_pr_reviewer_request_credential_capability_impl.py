"""ADR-DC-071 read-only reviewer-requestability credential capability.

Consumes one exact live ADR-DC-070 reviewer identity/PR-state observation and
binds it to one host-admin-controlled, read-only collaborator-permission broker.
No secret is loaded, no network I/O is performed, and no GitHub write authority
is granted by this capability.
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

from . import improvement_pilot_exact_task_pr_reviewer_identity_observation as identity_boundary
from .improvement_pilot_exact_task_pr_reviewer_identity_observation import (
    PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_AUTHORITY,
    PilotExactTaskPrReviewerIdentityObservation,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-credential-capability/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-exact-pr-reviewer-requestability-credential-broker-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL = (
    "github-rest-reviewer-requestability-broker-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION = (
    "get-collaborator-permission"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE = (
    "host-secret-store-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT = (
    "broker-owned-https-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN = "https://api.github.com"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT = "Ternedal"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PilotExactTaskPrReviewerRequestCredentialCapabilityError(ValueError):
    """Reviewer-requestability credential capability is unsafe or unbound."""


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
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "credential capability is not canonical JSON"
        ) from exc


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
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_identity(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerIdentityObservation, Any]:
    if type(value) is not PilotExactTaskPrReviewerIdentityObservation:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "exact ADR-DC-070 reviewer identity observation is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerIdentityObservation.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "ADR-DC-070 identity observation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "ADR-DC-070 identity observation mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.reviewer_request_authorization_consumed is not True
        or value.reviewer_request_slot_reserved is not True
        or value.reviewer_identity_verified is not True
        or value.pull_request_author_verified is not True
        or value.self_review_excluded is not True
        or value.no_requested_reviewers_verified is not True
        or value.exact_pr_state_reverified is not True
        or value.credential_free_reads is not True
        or value.reviewer_requestability_observation_required is not True
        or value.fresh_pr_state_revalidation_before_reviewer_request_required is not True
        or value.reviewer_request_transaction_required is not True
        or value.team_reviewers_forbidden is not True
        or value.reviewer_mutation_authorized is not False
        or value.reviewer_request_performed is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
    ):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "credential capability requires one live inert ADR-DC-070 observation"
        )
    live = identity_boundary._get_live_pr_reviewer_identity_observation_inputs(value)
    reservation = None if live is None else live.get("reviewer_request_reservation")
    if (
        reservation is None
        or getattr(reservation, "reservation_authenticated", None) is not True
        or reservation.sha256 != value.reviewer_request_reservation_sha256
        or reservation.reviewer_target_attestation_sha256
        != value.reviewer_target_attestation_sha256
        or reservation.reviewer_target_policy_sha256
        != value.reviewer_target_policy_sha256
        or reservation.reviewer_target_policy_epoch
        != value.reviewer_target_policy_epoch
        or reservation.reviewer_request_nonce_sha256 != value.reviewer_request_nonce_sha256
        or reservation.reviewer_login != value.reviewer_login
        or reservation.reviewer_user_id != value.reviewer_user_id
        or reservation.pull_request_number != value.pull_request_number
        or reservation.pull_request_api_url != value.pull_request_api_url
        or reservation.pull_request_html_url != value.pull_request_html_url
        or reservation.pull_request_node_id_sha256 != value.pull_request_node_id_sha256
        or reservation.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "ADR-DC-070 lost live ADR-DC-069 reservation provenance"
        )
    return value, reservation


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
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "credential-broker descriptor fields mismatch"
        )
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "credential-broker descriptor contains invalid text"
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
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL
        or result["operation"]
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION
        or result["secret_source"]
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE
        or result["secret_transport"]
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT
        or result["api_origin"]
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN
        or result["credential_account"]
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT
    ):
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "credential-broker descriptor semantics are unsupported"
        )
    return MappingProxyType(result)


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerIdentityObservation],
        Mapping[str, str],
    ],
] = {}


def _mark_authenticated(
    capability: Any,
    identity: PilotExactTaskPrReviewerIdentityObservation,
    descriptor: Mapping[str, str],
) -> None:
    key = id(capability)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        capability.sha256,
        weakref.ref(capability, cleanup),
        weakref.ref(identity),
        descriptor,
    )


def _get_live_pr_reviewer_request_credential_capability_inputs(
    capability: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(capability))
    if entry is None:
        return None
    pid, digest, capability_ref, identity_ref, descriptor = entry
    identity = identity_ref()
    if (
        pid != os.getpid()
        or capability_ref() is not capability
        or identity is None
        or identity.observation_authenticated is not True
        or identity.sha256 != capability.reviewer_identity_observation_sha256
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
    ):
        return None
    return MappingProxyType(
        {
            "reviewer_identity_observation": identity,
            "credential_broker_descriptor": descriptor,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestCredentialCapability:
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
    identity_observed_at_utc: str
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
    exact_pr_state_reverified: bool = True
    reviewer_requestability_observation_required: bool = True
    credential_broker_host_pinned: bool = True
    credential_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    collaborator_permission_read_required: bool = True
    other_repository_reads_forbidden: bool = True
    reviewer_write_forbidden: bool = True
    pull_request_write_forbidden: bool = True
    redirect_following_forbidden: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    post_request_readback_verification_required: bool = True
    one_shot_reviewer_request_transaction_required: bool = True
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
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY
        ):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
                "credential capability schema/authority is unsupported"
            )
        for name in (
            "reviewer_identity_observation_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "credential_account_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        observed = _utc(self.identity_observed_at_utc, name="identity_observed_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if materialized < observed:
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
                "credential capability predates identity observation"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL
            or self.credential_operation
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION
            or self.secret_source
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE
            or self.secret_transport
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT
            or self.api_origin
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN
            or self.credential_account_sha256
            != hashlib.sha256(
                PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT.encode("utf-8")
            ).hexdigest()
        ):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
                "credential capability binding is invalid"
            )
        required_true = (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "exact_pr_state_reverified",
            "reviewer_requestability_observation_required",
            "credential_broker_host_pinned",
            "credential_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "collaborator_permission_read_required",
            "other_repository_reads_forbidden",
            "reviewer_write_forbidden",
            "pull_request_write_forbidden",
            "redirect_following_forbidden",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "post_request_readback_verification_required",
            "one_shot_reviewer_request_transaction_required",
            "team_reviewers_forbidden",
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
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
                "credential capability safety evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
                "credential capability cannot grant GitHub mutation authority"
            )

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_reviewer_request_credential_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPrReviewerRequestCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
                "credential capability must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
                "credential capability fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
    *,
    reviewer_identity_observation: PilotExactTaskPrReviewerIdentityObservation,
    broker_descriptor: Mapping[str, str],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerRequestCredentialCapability:
    identity, _reservation = _require_live_identity(reviewer_identity_observation)
    descriptor = _descriptor(broker_descriptor)
    materialized_at = now_provider()
    _utc(materialized_at, name="materialized_at_utc")
    result = PilotExactTaskPrReviewerRequestCredentialCapability(
        reviewer_identity_observation_sha256=identity.sha256,
        reviewer_request_reservation_sha256=identity.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=identity.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=identity.reviewer_handoff_requirements_sha256,
        reviewer_target_policy_sha256=identity.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=identity.reviewer_target_policy_epoch,
        reviewer_request_nonce_sha256=identity.reviewer_request_nonce_sha256,
        repository=identity.repository,
        pull_request_number=identity.pull_request_number,
        pull_request_api_url=identity.pull_request_api_url,
        pull_request_html_url=identity.pull_request_html_url,
        pull_request_node_id_sha256=identity.pull_request_node_id_sha256,
        base_branch=identity.base_branch,
        head_branch=identity.head_branch,
        predicted_commit_sha=identity.predicted_commit_sha,
        reviewer_login=identity.reviewer_login,
        reviewer_user_id=identity.reviewer_user_id,
        identity_observed_at_utc=identity.observed_at_utc,
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
        materialized_at_utc=materialized_at,
    )
    _mark_authenticated(result, identity, descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
            "credential capability lost live ADR-DC-070 provenance"
        )
    return result


def materialize_pilot_exact_task_pr_reviewer_request_credential_capability(
    reviewer_identity_observation: PilotExactTaskPrReviewerIdentityObservation,
) -> PilotExactTaskPrReviewerRequestCredentialCapability:
    raise PilotExactTaskPrReviewerRequestCredentialCapabilityError(
        "production reviewer-requestability credential boundary is not installed"
    )
