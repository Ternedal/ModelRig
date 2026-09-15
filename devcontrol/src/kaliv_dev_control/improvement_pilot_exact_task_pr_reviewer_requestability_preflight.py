"""ADR-DC-072 credentialed read-only reviewer requestability preflight.

Consumes one live ADR-DC-071 reviewer-request credential capability, freshly
re-verifies the host-pinned broker binary, and asks that broker to perform only
the credentialed repository-permission read required to establish that the exact
pinned reviewer has at least read access to Ternedal/ModelRig. ModelRig never
loads the credential and this boundary performs no reviewer request or other
GitHub mutation.
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
    PilotExactTaskPrReviewerRequestCredentialCapability,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-requestability-preflight/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_AUTHORITY = (
    "credentialed-read-only-dc-l16-exact-pr-reviewer-requestability-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_REQUEST_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-reviewer-requestability-broker-request/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_RESPONSE_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-reviewer-requestability-broker-response/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_OPERATION = (
    "check-reviewer-requestability"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_MAX_BROKER_REQUEST_BYTES = 128 * 1024
_MAX_BROKER_OUTPUT_BYTES = 64 * 1024
_BROKER_TIMEOUT_SECONDS = 30
_ALLOWED_BASE_PERMISSIONS = frozenset({"read", "write", "admin"})


class PilotExactTaskPrReviewerRequestabilityPreflightError(ValueError):
    """Reviewer requestability preflight is stale, drifted or unsafe."""


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
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer requestability evidence is not canonical JSON"
        ) from exc


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(path)))
    ).hexdigest()


def _permission_url(reviewer_login: str) -> str:
    if not isinstance(reviewer_login, str) or _LOGIN.fullmatch(reviewer_login) is None:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer login is invalid for permission endpoint"
        )
    return (
        "https://api.github.com/repos/Ternedal/ModelRig/collaborators/"
        f"{reviewer_login}/permission"
    )


def _safe_role_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > 256
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "repository role_name is invalid"
        )
    return value


def _require_live_capability(
    value: Any,
) -> tuple[
    PilotExactTaskPrReviewerRequestCredentialCapability,
    Any,
    Mapping[str, str],
]:
    if type(value) is not PilotExactTaskPrReviewerRequestCredentialCapability:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "exact ADR-DC-071 reviewer-request credential capability is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestCredentialCapability.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "ADR-DC-071 capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "ADR-DC-071 capability identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or value.reviewer_request_authorization_consumed is not True
        or value.reviewer_request_slot_reserved is not True
        or value.reviewer_public_identity_verified is not True
        or value.reviewer_not_pr_author_verified is not True
        or value.fresh_exact_pr_state_observed is not True
        or value.no_requested_reviewers_verified is not True
        or value.credential_broker_host_pinned is not True
        or value.credential_broker_binary_verified is not True
        or value.credential_secret_not_loaded is not True
        or value.credential_broker_owns_https is not True
        or value.credentialed_requestability_check_required is not True
        or value.one_shot_reviewer_request_transaction_required is not True
        or value.fresh_pr_state_revalidation_before_reviewer_request_required is not True
        or value.post_reviewer_request_readback_required is not True
        or value.team_reviewers_forbidden is not True
        or value.reviewer_requestability_verified is not False
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
        or value.reviewer_user_id == value.pull_request_author_user_id
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "requestability preflight requires one live inert ADR-DC-071 capability"
        )
    inputs = (
        capability_boundary._get_live_pr_reviewer_request_credential_capability_inputs(
            value
        )
    )
    observation = None if inputs is None else inputs.get(
        "reviewer_identity_state_observation"
    )
    descriptor = None if inputs is None else inputs.get(
        "credential_broker_descriptor"
    )
    if (
        observation is None
        or descriptor is None
        or getattr(observation, "observation_authenticated", None) is not True
        or observation.sha256 != value.reviewer_identity_state_observation_sha256
        or observation.reviewer_request_reservation_sha256
        != value.reviewer_request_reservation_sha256
        or observation.reviewer_target_attestation_sha256
        != value.reviewer_target_attestation_sha256
        or observation.reviewer_login != value.reviewer_login
        or observation.reviewer_user_id != value.reviewer_user_id
        or observation.reviewer_node_id_sha256 != value.reviewer_node_id_sha256
        or observation.pull_request_number != value.pull_request_number
        or observation.reviewer_request_nonce_sha256
        != value.reviewer_request_nonce_sha256
        or descriptor.get("broker_policy_sha256") != value.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256")
        != value.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256")
        != value.broker_executable_sha256
        or descriptor.get("credential_protocol") != value.credential_protocol
        or descriptor.get("operation_set") != value.credential_operation_set
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "ADR-DC-071 capability lost exact live observation/broker provenance"
        )
    return value, observation, descriptor


def _require_preflight_window(
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="requestability checked_at_utc")
    materialized = _utc(
        capability.materialized_at_utc,
        name="capability materialized_at_utc",
    )
    if at < materialized:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "requestability preflight predates credential capability"
        )
    if (
        at - materialized
    ).total_seconds() > PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer-request credential capability is too old for preflight"
        )


def _fresh_broker_binary(
    descriptor: Mapping[str, str],
    *,
    require_host_control: bool,
) -> Path:
    path_text = descriptor.get("broker_executable_path")
    if not isinstance(path_text, str) or not path_text:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "live reviewer-request credential-broker path is unavailable"
        )
    path = Path(path_text)
    try:
        payload = broker_boundary._read_broker_bytes(
            path,
            require_host_control=require_host_control,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer-request credential-broker binary could not be freshly verified"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != descriptor.get(
        "broker_executable_sha256"
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer-request credential-broker binary changed after ADR-DC-071"
        )
    if _path_sha256(path) != descriptor.get("broker_executable_path_sha256"):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer-request credential-broker path changed after ADR-DC-071"
        )
    return path


def _broker_request(
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
) -> Mapping[str, Any]:
    permission_api_url = _permission_url(capability.reviewer_login)
    request = {
        "schema": PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_REQUEST_SCHEMA,
        "operation": PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_OPERATION,
        "api_origin": "https://api.github.com",
        "permission_api_url": permission_api_url,
        "repository": capability.repository,
        "pull_request_number": capability.pull_request_number,
        "reviewer_login": capability.reviewer_login,
        "reviewer_user_id": capability.reviewer_user_id,
        "reviewer_node_id_sha256": capability.reviewer_node_id_sha256,
        "reviewer_request_nonce_sha256": capability.reviewer_request_nonce_sha256,
    }
    payload = _canonical_bytes(request)
    if not payload or len(payload) > _MAX_BROKER_REQUEST_BYTES:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer requestability broker request exceeds byte bound"
        )
    return MappingProxyType(request)


def _validate_broker_response(
    payload: bytes,
    *,
    request_sha256: str,
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
) -> Mapping[str, Any]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_BROKER_OUTPUT_BYTES
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer requestability broker response is missing or oversized"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer requestability broker response is not UTF-8 JSON"
        ) from exc
    expected = {
        "schema",
        "status",
        "operation",
        "request_sha256",
        "permission_api_url_sha256",
        "repository",
        "reviewer_login",
        "reviewer_user_id",
        "permission",
        "role_name",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer requestability broker response fields mismatch"
        )
    permission_url_sha256 = hashlib.sha256(
        _permission_url(capability.reviewer_login).encode("utf-8")
    ).hexdigest()
    permission = value.get("permission")
    role_name = _safe_role_name(value.get("role_name"))
    if (
        value.get("schema")
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_RESPONSE_SCHEMA
        or value.get("status") != "requestable"
        or value.get("operation")
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_OPERATION
        or value.get("request_sha256") != request_sha256
        or value.get("permission_api_url_sha256") != permission_url_sha256
        or value.get("repository") != capability.repository
        or value.get("reviewer_login") != capability.reviewer_login
        or value.get("reviewer_user_id") != capability.reviewer_user_id
        or permission not in _ALLOWED_BASE_PERMISSIONS
    ):
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer does not have the exact repository access required for review request"
        )
    return MappingProxyType(
        {
            **dict(value),
            "role_name": role_name,
        }
    )


def _broker_environment() -> dict[str, str]:
    environment = {"LANG": "C", "LC_ALL": "C"}
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value and "\0" not in value:
                environment[name] = value
    return environment


def _invoke_broker(
    *,
    broker_path: Path,
    protocol: str,
    request_payload: bytes,
    request_sha256: str,
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
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
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer requestability broker environment contains credential-shaped keys"
        )
    try:
        result = subprocess_runner(
            command,
            cwd=broker_path.parent,
            env=environment,
            stdin_bytes=request_payload,
            timeout_seconds=_BROKER_TIMEOUT_SECONDS,
            max_output_bytes=_MAX_BROKER_OUTPUT_BYTES,
            stdout_prefix_bytes=_MAX_BROKER_OUTPUT_BYTES,
            stderr_prefix_bytes=_MAX_BROKER_OUTPUT_BYTES,
        )
    except BoundedSubprocessError as exc:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "bounded reviewer requestability broker failed"
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
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "reviewer requestability broker did not complete cleanly"
        )
    return result, _validate_broker_response(
        result.stdout.prefix,
        request_sha256=request_sha256,
        capability=capability,
    )


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
    receipt: Any,
    capability: PilotExactTaskPrReviewerRequestCredentialCapability,
) -> None:
    key = id(receipt)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        receipt.sha256,
        weakref.ref(receipt, cleanup),
        weakref.ref(capability),
    )


def _get_live_pr_reviewer_requestability_preflight_inputs(
    receipt: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(receipt))
    if entry is None:
        return None
    pid, digest, receipt_ref, capability_ref = entry
    capability = capability_ref()
    if (
        pid != os.getpid()
        or receipt_ref() is not receipt
        or capability is None
        or capability.capability_authenticated is not True
        or capability.sha256
        != receipt.reviewer_request_credential_capability_sha256
        or receipt.sha256 != digest
    ):
        return None
    return MappingProxyType(
        {"reviewer_request_credential_capability": capability}
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestabilityPreflight:
    reviewer_request_credential_capability_sha256: str
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
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_node_id_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_request_sha256: str
    broker_stdout_sha256: str
    broker_stderr_sha256: str
    broker_total_output_bytes: int
    permission_api_url_sha256: str
    repository_permission: str
    repository_role_name: str
    capability_materialized_at_utc: str
    checked_at_utc: str
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_reserved: bool = True
    reviewer_public_identity_verified: bool = True
    reviewer_not_pr_author_verified: bool = True
    fresh_exact_pr_state_observed: bool = True
    no_requested_reviewers_verified: bool = True
    credential_broker_freshly_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    credentialed_requestability_check_performed: bool = True
    reviewer_repository_read_access_verified: bool = True
    reviewer_requestability_verified: bool = True
    one_shot_reviewer_request_transaction_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    post_reviewer_request_readback_required: bool = True
    team_reviewers_forbidden: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_AUTHORITY
        ):
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight schema/authority is unsupported"
            )
        for name in (
            "reviewer_request_credential_capability_sha256",
            "reviewer_identity_state_observation_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "ready_transaction_sha256",
            "reviewer_handoff_plan_sha256",
            "reviewer_target_policy_sha256",
            "ready_for_review_nonce_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_node_id_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "broker_request_sha256",
            "broker_stdout_sha256",
            "broker_stderr_sha256",
            "permission_api_url_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if not isinstance(self.reviewer_login, str) or _LOGIN.fullmatch(self.reviewer_login) is None:
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight reviewer login is invalid"
            )
        materialized = _utc(
            self.capability_materialized_at_utc,
            name="capability_materialized_at_utc",
        )
        checked = _utc(self.checked_at_utc, name="checked_at_utc")
        if checked < materialized or (
            checked - materialized
        ).total_seconds() > PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS:
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight timestamps are invalid"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or self.repository_permission not in _ALLOWED_BASE_PERMISSIONS
            or _safe_role_name(self.repository_role_name) != self.repository_role_name
            or isinstance(self.broker_total_output_bytes, bool)
            or not isinstance(self.broker_total_output_bytes, int)
            or self.broker_total_output_bytes < 1
            or self.broker_total_output_bytes > _MAX_BROKER_OUTPUT_BYTES
            or self.permission_api_url_sha256
            != hashlib.sha256(
                _permission_url(self.reviewer_login).encode("utf-8")
            ).hexdigest()
        ):
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight target/output binding is invalid"
            )
        required_true = (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_public_identity_verified",
            "reviewer_not_pr_author_verified",
            "fresh_exact_pr_state_observed",
            "no_requested_reviewers_verified",
            "credential_broker_freshly_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "credentialed_requestability_check_performed",
            "reviewer_repository_read_access_verified",
            "reviewer_requestability_verified",
            "one_shot_reviewer_request_transaction_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "post_reviewer_request_readback_required",
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
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight cannot grant mutation authority"
            )

    @property
    def preflight_authenticated(self) -> bool:
        return _get_live_pr_reviewer_requestability_preflight_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPrReviewerRequestabilityPreflight":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestabilityPreflightError(
                "requestability preflight fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_reviewer_requestability(
    *,
    reviewer_request_credential_capability: PilotExactTaskPrReviewerRequestCredentialCapability,
    subprocess_runner: Callable[..., Any],
    now_provider: Callable[[], str],
    broker_host_control_required: bool,
) -> PilotExactTaskPrReviewerRequestabilityPreflight:
    capability, _observation, descriptor = _require_live_capability(
        reviewer_request_credential_capability
    )
    checked_at = now_provider()
    _require_preflight_window(capability, at_utc=checked_at)
    broker_path = _fresh_broker_binary(
        descriptor,
        require_host_control=broker_host_control_required,
    )
    request = _broker_request(capability)
    request_payload = _canonical_bytes(request)
    request_sha256 = hashlib.sha256(request_payload).hexdigest()
    broker_result, broker_response = _invoke_broker(
        broker_path=broker_path,
        protocol=capability.credential_protocol,
        request_payload=request_payload,
        request_sha256=request_sha256,
        capability=capability,
        subprocess_runner=subprocess_runner,
    )
    result = PilotExactTaskPrReviewerRequestabilityPreflight(
        reviewer_request_credential_capability_sha256=capability.sha256,
        reviewer_identity_state_observation_sha256=capability.reviewer_identity_state_observation_sha256,
        reviewer_request_reservation_sha256=capability.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=capability.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=capability.reviewer_handoff_requirements_sha256,
        ready_transaction_sha256=capability.ready_transaction_sha256,
        predicted_commit_sha=capability.predicted_commit_sha,
        reviewer_handoff_plan_sha256=capability.reviewer_handoff_plan_sha256,
        reviewer_target_policy_sha256=capability.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=capability.reviewer_target_policy_epoch,
        ready_for_review_nonce_sha256=capability.ready_for_review_nonce_sha256,
        reviewer_request_nonce_sha256=capability.reviewer_request_nonce_sha256,
        repository=capability.repository,
        pull_request_number=capability.pull_request_number,
        pull_request_node_id_sha256=capability.pull_request_node_id_sha256,
        base_branch=capability.base_branch,
        head_branch=capability.head_branch,
        reviewer_login=capability.reviewer_login,
        reviewer_user_id=capability.reviewer_user_id,
        reviewer_node_id_sha256=capability.reviewer_node_id_sha256,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        broker_request_sha256=request_sha256,
        broker_stdout_sha256=broker_result.stdout.sha256,
        broker_stderr_sha256=broker_result.stderr.sha256,
        broker_total_output_bytes=broker_result.total_output_bytes,
        permission_api_url_sha256=broker_response["permission_api_url_sha256"],
        repository_permission=broker_response["permission"],
        repository_role_name=broker_response["role_name"],
        capability_materialized_at_utc=capability.materialized_at_utc,
        checked_at_utc=checked_at,
    )
    _mark_authenticated(result, capability)
    if result.preflight_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestabilityPreflightError(
            "requestability preflight lost live ADR-DC-071 provenance"
        )
    return result


def observe_pilot_exact_task_pr_reviewer_requestability(
    reviewer_request_credential_capability: PilotExactTaskPrReviewerRequestCredentialCapability,
) -> PilotExactTaskPrReviewerRequestabilityPreflight:
    """Perform one credentialed read-only reviewer requestability preflight."""
    return _observe_verified_pilot_exact_task_pr_reviewer_requestability(
        reviewer_request_credential_capability=reviewer_request_credential_capability,
        subprocess_runner=run_bounded_subprocess,
        now_provider=_now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_REQUEST_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_RESPONSE_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_OPERATION",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_MAX_CAPABILITY_AGE_SECONDS",
    "PilotExactTaskPrReviewerRequestabilityPreflightError",
    "PilotExactTaskPrReviewerRequestabilityPreflight",
    "observe_pilot_exact_task_pr_reviewer_requestability",
]
