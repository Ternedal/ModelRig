"""ADR-DC-063 host-pinned credential capability for one exact ready-for-review transition.

Private implementation/test seam. The public production facade supplies one
host-admin-controlled broker descriptor. No credential secret is loaded here,
no HTTP request is performed, and no GitHub mutation authority is granted.
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

from . import improvement_pilot_exact_task_pr_ready_for_review_state_observation as state_boundary
from .improvement_pilot_exact_task_pr_ready_for_review_state_observation import (
    PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskPrReadyStateObservation,
)

PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-credential-capability/v1"
)
PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-exact-pr-ready-for-review-credential-broker-only"
)
PILOT_EXACT_TASK_PR_READY_CREDENTIAL_PROTOCOL = "github-graphql-ready-for-review-broker-v1"
PILOT_EXACT_TASK_PR_READY_CREDENTIAL_OPERATION = "mark-pull-request-ready-for-review"
PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_SOURCE = "host-secret-store-only"
PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_TRANSPORT = "broker-owned-https-only"
PILOT_EXACT_TASK_PR_READY_CREDENTIAL_API_ORIGIN = "https://api.github.com/graphql"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PilotExactTaskPrReadyCredentialCapabilityError(ValueError):
    """The host-pinned ready-for-review credential capability is unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability is not canonical JSON") from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReadyCredentialCapabilityError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReadyCredentialCapabilityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReadyCredentialCapabilityError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrReadyCredentialCapabilityError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_observation(value: Any) -> tuple[PilotExactTaskPrReadyStateObservation, Any, Any]:
    if type(value) is not PilotExactTaskPrReadyStateObservation:
        raise PilotExactTaskPrReadyCredentialCapabilityError("exact ADR-DC-062 ready-state observation is required")
    try:
        replayed = PilotExactTaskPrReadyStateObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ADR-DC-062 observation replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ADR-DC-062 observation identity mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.ready_for_review_authorization_consumed is not True
        or value.ready_for_review_slot_reserved is not True
        or value.credential_free_read_verified is not True
        or value.pull_request_open_verified is not True
        or value.draft_state_verified is not True
        or value.exact_head_sha_verified is not True
        or value.exact_base_verified is not True
        or value.exact_metadata_verified is not True
        or value.signed_updated_at_still_current is not True
        or value.ready_for_review_transaction_required is not True
        or value.reviewer_mutation_separate_authority_required is not True
        or value.label_mutation_separate_authority_required is not True
        or value.merge_separate_authority_required is not True
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.ready_for_review_authorized is not False
        or value.ready_for_review_performed is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or value.signed_observed_updated_at_utc != value.fresh_observed_updated_at_utc
    ):
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability requires one live inert ADR-DC-062 observation")
    inputs = state_boundary._get_live_pr_ready_state_observation_inputs(value)
    reservation = None if inputs is None else inputs.get("ready_for_review_reservation")
    requirements = None if inputs is None else inputs.get("review_handoff_requirements")
    if (
        reservation is None or requirements is None
        or getattr(reservation, "reservation_authenticated", None) is not True
        or getattr(requirements, "requirements_authenticated", None) is not True
        or reservation.sha256 != value.ready_for_review_reservation_sha256
        or requirements.sha256 != value.review_handoff_requirements_sha256
        or reservation.ready_for_review_nonce_sha256 != value.ready_for_review_nonce_sha256
        or requirements.pr_create_transaction_sha256 != value.pr_create_transaction_sha256
        or requirements.review_handoff_plan_sha256 != value.review_handoff_plan_sha256
        or requirements.pull_request_number != value.pull_request_number
    ):
        raise PilotExactTaskPrReadyCredentialCapabilityError("ADR-DC-062 observation lost live reservation/handoff provenance")
    return value, reservation, requirements


def _descriptor(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrReadyCredentialCapabilityError("host ready credential-broker descriptor is required")
    expected = {
        "broker_policy_sha256", "broker_executable_path", "broker_executable_path_sha256",
        "broker_executable_sha256", "broker_version", "credential_protocol", "operation",
        "secret_source", "secret_transport", "api_origin",
    }
    if set(value) != expected:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential-broker descriptor fields mismatch")
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential-broker descriptor contains invalid text")
    for name in ("broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256"):
        _hex64(result[name], name=name)
    path = Path(result["broker_executable_path"])
    if not path.is_absolute():
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential-broker executable path must be absolute")
    expected_path_sha256 = hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()
    if result["broker_executable_path_sha256"] != expected_path_sha256:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential-broker executable path hash mismatch")
    if _VERSION.fullmatch(result["broker_version"]) is None:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential-broker version is invalid")
    if (
        result["credential_protocol"] != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_PROTOCOL
        or result["operation"] != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_OPERATION
        or result["secret_source"] != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_SOURCE
        or result["secret_transport"] != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_TRANSPORT
        or result["api_origin"] != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_API_ORIGIN
    ):
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential-broker semantics are unsupported")
    return MappingProxyType(result)


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrReadyStateObservation], Mapping[str, str]]] = {}

    def mark(capability: Any, observation: PilotExactTaskPrReadyStateObservation, descriptor: Mapping[str, str]) -> None:
        key = id(capability)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), capability.sha256, weakref.ref(capability, cleanup), weakref.ref(observation), descriptor)

    def get(capability: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(capability))
        if entry is None:
            return None
        pid, digest, capability_ref, observation_ref, descriptor = entry
        observation = observation_ref()
        if (
            pid != os.getpid() or capability_ref() is not capability or observation is None
            or observation.observation_authenticated is not True
            or observation.sha256 != capability.ready_state_observation_sha256
            or capability.sha256 != digest
            or descriptor.get("broker_policy_sha256") != capability.broker_policy_sha256
            or descriptor.get("broker_executable_path_sha256") != capability.broker_executable_path_sha256
            or descriptor.get("broker_executable_sha256") != capability.broker_executable_sha256
            or descriptor.get("operation") != capability.credential_operation
        ):
            return None
        return MappingProxyType({"ready_state_observation": observation, "credential_broker_descriptor": descriptor})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(_mark_pr_ready_credential_capability_authenticated, _get_live_pr_ready_credential_capability_inputs) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReadyCredentialCapability:
    ready_state_observation_sha256: str
    ready_for_review_reservation_sha256: str
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    review_handoff_plan_sha256: str
    ready_for_review_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    base_branch: str
    head_branch: str
    signed_observed_updated_at_utc: str
    fresh_observed_updated_at_utc: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    credential_operation: str
    secret_source: str
    secret_transport: str
    api_origin: str
    materialized_at_utc: str
    ready_for_review_authorization_consumed: bool = True
    ready_for_review_slot_reserved: bool = True
    fresh_exact_pr_state_observed: bool = True
    signed_updated_at_still_current: bool = True
    credential_broker_host_pinned: bool = True
    credential_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    one_shot_ready_for_review_transaction_required: bool = True
    fresh_pr_state_revalidation_before_ready_required: bool = True
    post_ready_readback_verification_required: bool = True
    reviewer_mutation_separate_authority_required: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    ready_for_review_authorized: bool = False
    ready_for_review_performed: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_AUTHORITY:
            raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability schema/authority is unsupported")
        for name in (
            "ready_state_observation_sha256", "ready_for_review_reservation_sha256", "review_handoff_requirements_sha256",
            "pr_create_transaction_sha256", "review_handoff_plan_sha256", "ready_for_review_nonce_sha256",
            "broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        signed = _utc(self.signed_observed_updated_at_utc, name="signed_observed_updated_at_utc")
        fresh = _utc(self.fresh_observed_updated_at_utc, name="fresh_observed_updated_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if signed != fresh or materialized < fresh:
            raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability timestamps are inconsistent")
        if (
            self.repository != "Ternedal/ModelRig" or self.base_branch != "main" or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or self.pull_request_api_url != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_PROTOCOL
            or self.credential_operation != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_OPERATION
            or self.secret_source != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_SOURCE
            or self.secret_transport != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_TRANSPORT
            or self.api_origin != PILOT_EXACT_TASK_PR_READY_CREDENTIAL_API_ORIGIN
        ):
            raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability binding is invalid")
        required_true = (
            "ready_for_review_authorization_consumed", "ready_for_review_slot_reserved", "fresh_exact_pr_state_observed",
            "signed_updated_at_still_current", "credential_broker_host_pinned", "credential_broker_binary_verified",
            "credential_secret_not_loaded", "credential_broker_owns_https", "one_shot_ready_for_review_transaction_required",
            "fresh_pr_state_revalidation_before_ready_required", "post_ready_readback_verification_required",
            "reviewer_mutation_separate_authority_required", "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "credential_material_in_artifact", "credential_material_in_process_arguments", "credential_material_in_environment",
            "pr_mutation_authorized", "pull_request_create_authorized", "ready_for_review_authorized",
            "ready_for_review_performed", "reviewer_mutation_authorized", "label_mutation_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability cannot grant GitHub mutation authority")

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_ready_credential_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReadyCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_ready_credential_capability(
    *, ready_state_observation: PilotExactTaskPrReadyStateObservation, broker_descriptor: Mapping[str, Any], now_provider: Callable[[], str],
) -> PilotExactTaskPrReadyCredentialCapability:
    observation, reservation, requirements = _require_live_observation(ready_state_observation)
    descriptor = _descriptor(broker_descriptor)
    materialized_at = now_provider()
    if _utc(materialized_at, name="materialized_at_utc") < _utc(observation.observed_at_utc, name="observation observed_at_utc"):
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability predates fresh PR observation")
    result = PilotExactTaskPrReadyCredentialCapability(
        ready_state_observation_sha256=observation.sha256,
        ready_for_review_reservation_sha256=observation.ready_for_review_reservation_sha256,
        review_handoff_requirements_sha256=observation.review_handoff_requirements_sha256,
        pr_create_transaction_sha256=observation.pr_create_transaction_sha256,
        predicted_commit_sha=observation.predicted_commit_sha,
        review_handoff_plan_sha256=observation.review_handoff_plan_sha256,
        ready_for_review_nonce_sha256=observation.ready_for_review_nonce_sha256,
        repository=observation.repository,
        pull_request_number=observation.pull_request_number,
        pull_request_api_url=observation.pull_request_api_url,
        pull_request_html_url=observation.pull_request_html_url,
        base_branch=observation.base_branch,
        head_branch=observation.head_branch,
        signed_observed_updated_at_utc=observation.signed_observed_updated_at_utc,
        fresh_observed_updated_at_utc=observation.fresh_observed_updated_at_utc,
        broker_policy_sha256=descriptor["broker_policy_sha256"],
        broker_executable_path_sha256=descriptor["broker_executable_path_sha256"],
        broker_executable_sha256=descriptor["broker_executable_sha256"],
        broker_version=descriptor["broker_version"], credential_protocol=descriptor["credential_protocol"],
        credential_operation=descriptor["operation"], secret_source=descriptor["secret_source"],
        secret_transport=descriptor["secret_transport"], api_origin=descriptor["api_origin"],
        materialized_at_utc=materialized_at,
    )
    if reservation.sha256 != result.ready_for_review_reservation_sha256 or requirements.sha256 != result.review_handoff_requirements_sha256:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability lost exact live provenance")
    _mark_pr_ready_credential_capability_authenticated(result, observation, descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrReadyCredentialCapabilityError("ready credential capability lost live observation provenance")
    return result


def materialize_pilot_exact_task_pr_ready_credential_capability(
    ready_state_observation: PilotExactTaskPrReadyStateObservation,
) -> PilotExactTaskPrReadyCredentialCapability:
    raise PilotExactTaskPrReadyCredentialCapabilityError("production ready credential capability boundary is not installed")


__all__ = [
    "PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_SCHEMA", "PILOT_EXACT_TASK_PR_READY_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_READY_CREDENTIAL_PROTOCOL", "PILOT_EXACT_TASK_PR_READY_CREDENTIAL_OPERATION",
    "PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_SOURCE", "PILOT_EXACT_TASK_PR_READY_CREDENTIAL_SECRET_TRANSPORT",
    "PILOT_EXACT_TASK_PR_READY_CREDENTIAL_API_ORIGIN", "PilotExactTaskPrReadyCredentialCapabilityError",
    "PilotExactTaskPrReadyCredentialCapability", "materialize_pilot_exact_task_pr_ready_credential_capability",
]
