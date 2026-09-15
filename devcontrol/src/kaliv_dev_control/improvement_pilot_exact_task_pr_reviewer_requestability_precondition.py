"""ADR-DC-072 brokered read-only reviewer requestability precondition.

Consumes one exact live ADR-DC-071 reviewer-request credential capability,
freshly verifies the host-pinned broker binary, then invokes only the broker's
collaborator-permission read operation. Credential custody remains broker-owned.
This boundary proves the pinned reviewer has at least read repository access;
it performs no reviewer request and grants no GitHub mutation authority.
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

from . import _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary as broker_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from . import improvement_pilot_exact_task_pr_reviewer_request_credential_capability as capability_boundary
from .improvement_pilot_exact_task_pr_reviewer_request_credential_capability import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY,
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL,
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PERMISSION_READ_OPERATION,
    PilotExactTaskPrReviewerRequestCredentialCapability,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-requestability-precondition/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_AUTHORITY = (
    "observed-one-dc-l16-exact-pr-reviewer-requestability-precondition-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCOPE = (
    "brokered-read-only-exact-reviewer-repository-access-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_BROKER_REQUEST_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-reviewer-permission-broker-request/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_BROKER_RESPONSE_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-reviewer-permission-broker-response/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS = 60
PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_REQUEST_BYTES = 64 * 1024
PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_OUTPUT_BYTES = 64 * 1024
PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_TIMEOUT_SECONDS = 30

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_+/=-]{8,256}$")
_ALLOWED_PERMISSIONS = frozenset({"read", "write", "admin"})


class PilotExactTaskPrReviewerRequestabilityPreconditionError(ValueError):
    """Reviewer repository-access precondition is stale, unsafe, or unbound."""


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
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer requestability evidence is not canonical JSON"
        ) from exc


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            f"{name} is invalid"
        ) from exc


def _login(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _LOGIN.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            f"{name} is invalid"
        )
    return value


def _node_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _NODE_ID.fullmatch(value) is None
        or "\x00" in value
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "permission response reviewer node id is invalid"
        )
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(path)))
    ).hexdigest()


def _require_live_capability(
    value: Any,
) -> tuple[
    PilotExactTaskPrReviewerRequestCredentialCapability,
    Any,
    Mapping[str, str],
]:
    if type(value) is not PilotExactTaskPrReviewerRequestCredentialCapability:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "exact ADR-DC-071 reviewer-request credential capability is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestCredentialCapability.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "ADR-DC-071 capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "ADR-DC-071 capability identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or value.reviewer_request_authorization_consumed is not True
        or value.reviewer_request_slot_reserved is not True
        or value.reviewer_identity_verified is not True
        or value.exact_pr_state_reverified is not True
        or value.reviewer_requestability_observation_required is not True
        or value.credential_broker_host_pinned is not True
        or value.credential_broker_binary_verified is not True
        or value.credential_secret_not_loaded is not True
        or value.credential_broker_owns_https is not True
        or value.permission_read_required is not True
        or value.fresh_pr_state_revalidation_before_reviewer_request_required is not True
        or value.post_request_readback_verification_required is not True
        or value.one_shot_reviewer_request_transaction_required is not True
        or value.team_reviewers_forbidden is not True
        or value.credential_material_in_artifact is not False
        or value.credential_material_in_process_arguments is not False
        or value.credential_material_in_environment is not False
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
        or value.credential_protocol
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL
        or value.permission_read_operation
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PERMISSION_READ_OPERATION
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "requestability precondition requires one live inert ADR-DC-071 capability"
        )
    live = (
        capability_boundary._get_live_pr_reviewer_request_credential_capability_inputs(
            value
        )
    )
    identity = None if live is None else live.get("reviewer_identity_observation")
    descriptor = None if live is None else live.get("credential_broker_descriptor")
    if (
        identity is None
        or getattr(identity, "observation_authenticated", None) is not True
        or identity.sha256 != value.reviewer_identity_observation_sha256
        or identity.reviewer_request_reservation_sha256
        != value.reviewer_request_reservation_sha256
        or identity.reviewer_request_nonce_sha256 != value.reviewer_request_nonce_sha256
        or identity.reviewer_target_attestation_sha256
        != value.reviewer_target_attestation_sha256
        or identity.reviewer_target_policy_sha256 != value.reviewer_target_policy_sha256
        or identity.reviewer_login != value.reviewer_login
        or identity.reviewer_user_id != value.reviewer_user_id
        or identity.pull_request_number != value.pull_request_number
        or identity.predicted_commit_sha != value.predicted_commit_sha
        or not isinstance(descriptor, Mapping)
        or descriptor.get("broker_policy_sha256") != value.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256")
        != value.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256") != value.broker_executable_sha256
        or descriptor.get("credential_protocol") != value.credential_protocol
        or descriptor.get("permission_read_operation") != value.permission_read_operation
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "ADR-DC-071 lost live ADR-DC-070/broker provenance"
        )
    return value, identity, MappingProxyType(dict(descriptor))


def _require_capability_window(
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="permission read start")
    materialized = _utc(
        capability.materialized_at_utc,
        name="capability materialized_at_utc",
    )
    if (
        at < materialized
        or (at - materialized).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "ADR-DC-071 credential capability is too old for permission read"
        )


def _fresh_broker_binary(
    descriptor: Mapping[str, str],
    *,
    require_host_control: bool,
) -> Path:
    path_text = descriptor.get("broker_executable_path")
    if not isinstance(path_text, str) or not path_text:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "live reviewer-request broker path is unavailable"
        )
    path = Path(path_text)
    try:
        payload = broker_boundary._read_broker_bytes(
            path,
            require_host_control=require_host_control,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer-request broker binary could not be freshly verified"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != descriptor.get(
        "broker_executable_sha256"
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer-request broker binary changed after ADR-DC-071"
        )
    if _path_sha256(path) != descriptor.get("broker_executable_path_sha256"):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer-request broker path identity changed after ADR-DC-071"
        )
    return path


def _permission_path(login: str) -> str:
    _login(login, name="reviewer_login")
    return (
        "/repos/Ternedal/ModelRig/collaborators/"
        f"{login}/permission"
    )


def _broker_request(
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
    identity: Any,
) -> Mapping[str, Any]:
    request = {
        "schema": PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_BROKER_REQUEST_SCHEMA,
        "operation": PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PERMISSION_READ_OPERATION,
        "api_origin": "https://api.github.com",
        "api_path": _permission_path(capability.reviewer_login),
        "repository": capability.repository,
        "pull_request_number": capability.pull_request_number,
        "head_sha": capability.predicted_commit_sha,
        "reviewer_login": capability.reviewer_login,
        "reviewer_user_id": capability.reviewer_user_id,
        "reviewer_user_node_id_sha256": identity.reviewer_user_node_id_sha256,
        "reviewer_request_nonce_sha256": capability.reviewer_request_nonce_sha256,
    }
    payload = _canonical_bytes(request)
    if (
        not payload
        or len(payload)
        > PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_REQUEST_BYTES
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer permission broker request exceeds byte bound"
        )
    return MappingProxyType(request)


def _validate_broker_response(
    payload: bytes,
    *,
    request_sha256: str,
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
    identity: Any,
) -> Mapping[str, Any]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_OUTPUT_BYTES
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer permission broker response is missing or oversized"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer permission broker response is not UTF-8 JSON"
        ) from exc
    expected = {
        "schema",
        "status",
        "operation",
        "request_sha256",
        "repository",
        "pull_request_number",
        "reviewer_login",
        "reviewer_user_id",
        "reviewer_node_id",
        "reviewer_api_url",
        "reviewer_html_url",
        "repository_permission",
        "repository_role_name",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer permission broker response fields mismatch"
        )
    login = _login(value.get("reviewer_login"), name="observed reviewer login")
    node_id = _node_id(value.get("reviewer_node_id"))
    permission = value.get("repository_permission")
    role_name = value.get("repository_role_name")
    if (
        value.get("schema")
        != PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_BROKER_RESPONSE_SCHEMA
        or value.get("status") != "permission-observed"
        or value.get("operation")
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PERMISSION_READ_OPERATION
        or value.get("request_sha256") != request_sha256
        or value.get("repository") != capability.repository
        or value.get("pull_request_number") != capability.pull_request_number
        or login != capability.reviewer_login
        or value.get("reviewer_user_id") != capability.reviewer_user_id
        or hashlib.sha256(node_id.encode("utf-8")).hexdigest()
        != identity.reviewer_user_node_id_sha256
        or value.get("reviewer_api_url") != identity.reviewer_user_api_url
        or value.get("reviewer_html_url") != identity.reviewer_user_html_url
        or permission not in _ALLOWED_PERMISSIONS
        or not isinstance(role_name, str)
        or not role_name
        or len(role_name) > 128
        or role_name != role_name.strip()
        or "\r" in role_name
        or "\n" in role_name
        or "\x00" in role_name
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer permission broker response does not prove exact repository access"
        )
    return MappingProxyType(dict(value))


def _broker_environment() -> dict[str, str]:
    environment = {"LANG": "C", "LC_ALL": "C"}
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value and "\0" not in value:
                environment[name] = value
    return environment


def _invoke_permission_broker(
    *,
    broker_path: Path,
    protocol: str,
    request_payload: bytes,
    request_sha256: str,
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
    identity: Any,
    subprocess_runner: Callable[..., Any],
) -> tuple[Any, Mapping[str, Any]]:
    command = (
        os.fspath(broker_path),
        "--protocol",
        protocol,
        "--request-stdin-json",
        "--response-stdout-json",
    )
    environment = _broker_environment()
    if any(
        marker in key.upper()
        for key in environment
        for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "permission broker environment unexpectedly contains credential-shaped keys"
        )
    try:
        result = subprocess_runner(
            command,
            cwd=broker_path.parent,
            env=environment,
            stdin_bytes=request_payload,
            timeout_seconds=PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_TIMEOUT_SECONDS,
            max_output_bytes=PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_OUTPUT_BYTES,
            stdout_prefix_bytes=PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_OUTPUT_BYTES,
            stderr_prefix_bytes=PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_OUTPUT_BYTES,
        )
    except BoundedSubprocessError as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "bounded reviewer permission broker process failed"
        ) from exc
    if (
        result.returncode != 0
        or result.output_limit_exceeded
        or result.timed_out
        or result.stdout.truncated
        or result.stderr.truncated
        or result.stderr.total_bytes != 0
        or result.stdout.total_bytes != len(result.stdout.prefix)
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "reviewer permission broker did not complete cleanly and silently"
        )
    response = _validate_broker_response(
        result.stdout.prefix,
        request_sha256=request_sha256,
        capability=capability,
        identity=identity,
    )
    return result, response


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerRequestCredentialCapability],
    ],
] = {}


def _mark_authenticated(
    observation: Any,
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
) -> None:
    key = id(observation)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        observation.sha256,
        weakref.ref(observation, cleanup),
        weakref.ref(capability),
    )


def _get_live_pr_reviewer_requestability_precondition_inputs(
    observation: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(observation))
    if entry is None:
        return None
    pid, digest, observation_ref, capability_ref = entry
    capability = capability_ref()
    if (
        pid != os.getpid()
        or observation_ref() is not observation
        or capability is None
        or capability.capability_authenticated is not True
        or capability.sha256
        != observation.reviewer_request_credential_capability_sha256
        or observation.sha256 != digest
    ):
        return None
    return MappingProxyType({"reviewer_request_credential_capability": capability})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestabilityPrecondition:
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
    credential_protocol: str
    permission_read_operation: str
    capability_materialized_at_utc: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_request_sha256: str
    broker_stdout_sha256: str
    broker_stderr_sha256: str
    broker_total_output_bytes: int
    repository_permission: str
    repository_role_name_sha256: str
    permission_read_started_at_utc: str
    observed_at_utc: str
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_reserved: bool = True
    reviewer_identity_verified: bool = True
    exact_pr_state_reverified: bool = True
    credential_broker_freshly_verified: bool = True
    credential_broker_invoked_without_secret_exposure: bool = True
    permission_read_performed: bool = True
    minimum_read_repository_permission_verified: bool = True
    reviewer_requestability_precondition_verified: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCOPE
        ):
            raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
                "requestability precondition schema/authority/scope is unsupported"
            )
        for name in (
            "reviewer_request_credential_capability_sha256",
            "reviewer_identity_observation_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "broker_request_sha256",
            "broker_stdout_sha256",
            "broker_stderr_sha256",
            "repository_role_name_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        materialized = _utc(
            self.capability_materialized_at_utc,
            name="capability_materialized_at_utc",
        )
        started = _utc(
            self.permission_read_started_at_utc,
            name="permission_read_started_at_utc",
        )
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if (
            started < materialized
            or observed < started
            or (started - materialized).total_seconds()
            > PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS
        ):
            raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
                "requestability precondition timestamps are invalid"
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
            or self.credential_protocol
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL
            or self.permission_read_operation
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_PERMISSION_READ_OPERATION
            or self.repository_permission not in _ALLOWED_PERMISSIONS
            or isinstance(self.broker_total_output_bytes, bool)
            or not isinstance(self.broker_total_output_bytes, int)
            or self.broker_total_output_bytes < 1
            or self.broker_total_output_bytes
            > PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_MAX_OUTPUT_BYTES
        ):
            raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
                "requestability precondition binding is invalid"
            )
        required_true = (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "exact_pr_state_reverified",
            "credential_broker_freshly_verified",
            "credential_broker_invoked_without_secret_exposure",
            "permission_read_performed",
            "minimum_read_repository_permission_verified",
            "reviewer_requestability_precondition_verified",
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
            raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
                "requestability precondition evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
                "requestability precondition cannot grant mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_reviewer_requestability_precondition_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPrReviewerRequestabilityPrecondition":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
                "requestability precondition must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
                "requestability precondition fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_reviewer_requestability_precondition(
    *,
    reviewer_request_credential_capability: PilotExactTaskPrReviewerRequestCredentialCapability,
    subprocess_runner: Callable[..., Any],
    now_provider: Callable[[], str],
    broker_host_control_required: bool,
) -> PilotExactTaskPrReviewerRequestabilityPrecondition:
    capability, identity, descriptor = _require_live_capability(
        reviewer_request_credential_capability
    )
    started_at = now_provider()
    _require_capability_window(capability, at_utc=started_at)
    broker_path = _fresh_broker_binary(
        descriptor,
        require_host_control=broker_host_control_required,
    )
    request = _broker_request(capability, identity)
    request_payload = _canonical_bytes(request)
    request_sha256 = hashlib.sha256(request_payload).hexdigest()
    broker_result, response = _invoke_permission_broker(
        broker_path=broker_path,
        protocol=capability.credential_protocol,
        request_payload=request_payload,
        request_sha256=request_sha256,
        capability=capability,
        identity=identity,
        subprocess_runner=subprocess_runner,
    )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        started_at,
        name="permission_read_started_at_utc",
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "clock moved backwards during reviewer permission read"
        )
    result = PilotExactTaskPrReviewerRequestabilityPrecondition(
        reviewer_request_credential_capability_sha256=capability.sha256,
        reviewer_identity_observation_sha256=capability.reviewer_identity_observation_sha256,
        reviewer_request_reservation_sha256=capability.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=capability.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=capability.reviewer_handoff_requirements_sha256,
        reviewer_target_policy_sha256=capability.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=capability.reviewer_target_policy_epoch,
        reviewer_request_nonce_sha256=capability.reviewer_request_nonce_sha256,
        repository=capability.repository,
        pull_request_number=capability.pull_request_number,
        pull_request_api_url=capability.pull_request_api_url,
        pull_request_html_url=capability.pull_request_html_url,
        pull_request_node_id_sha256=capability.pull_request_node_id_sha256,
        base_branch=capability.base_branch,
        head_branch=capability.head_branch,
        predicted_commit_sha=capability.predicted_commit_sha,
        reviewer_login=capability.reviewer_login,
        reviewer_user_id=capability.reviewer_user_id,
        reviewer_user_node_id_sha256=identity.reviewer_user_node_id_sha256,
        credential_protocol=capability.credential_protocol,
        permission_read_operation=capability.permission_read_operation,
        capability_materialized_at_utc=capability.materialized_at_utc,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        broker_request_sha256=request_sha256,
        broker_stdout_sha256=broker_result.stdout.sha256,
        broker_stderr_sha256=broker_result.stderr.sha256,
        broker_total_output_bytes=broker_result.total_output_bytes,
        repository_permission=str(response["repository_permission"]),
        repository_role_name_sha256=hashlib.sha256(
            str(response["repository_role_name"]).encode("utf-8")
        ).hexdigest(),
        permission_read_started_at_utc=started_at,
        observed_at_utc=observed_at,
    )
    _mark_authenticated(result, capability)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestabilityPreconditionError(
            "requestability precondition lost live ADR-DC-071 provenance"
        )
    return result


def observe_pilot_exact_task_pr_reviewer_requestability_precondition(
    reviewer_request_credential_capability: PilotExactTaskPrReviewerRequestCredentialCapability,
) -> PilotExactTaskPrReviewerRequestabilityPrecondition:
    """Perform one brokered permission read; never request a reviewer."""
    return _observe_verified_pilot_exact_task_pr_reviewer_requestability_precondition(
        reviewer_request_credential_capability=reviewer_request_credential_capability,
        subprocess_runner=run_bounded_subprocess,
        now_provider=_now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PRECONDITION_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_BROKER_REQUEST_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_BROKER_RESPONSE_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS",
    "PilotExactTaskPrReviewerRequestabilityPreconditionError",
    "PilotExactTaskPrReviewerRequestabilityPrecondition",
    "observe_pilot_exact_task_pr_reviewer_requestability_precondition",
]
