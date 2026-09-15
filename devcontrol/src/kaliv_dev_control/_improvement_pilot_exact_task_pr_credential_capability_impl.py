"""ADR-DC-057 host-pinned credential-broker capability for one draft-PR create.

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

from . import improvement_pilot_exact_task_pr_state_observation as observation_boundary
from .improvement_pilot_exact_task_pr_state_observation import (
    PILOT_EXACT_TASK_PR_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskPrStateObservation,
)

PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-credential-capability/v1"
)
PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-exact-pr-credential-broker-only"
)
PILOT_EXACT_TASK_PR_CREDENTIAL_PROTOCOL = "github-rest-broker-v1"
PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_SOURCE = "host-secret-store-only"
PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_TRANSPORT = "broker-owned-https-only"
PILOT_EXACT_TASK_PR_CREDENTIAL_API_ORIGIN = "https://api.github.com"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PilotExactTaskPrCredentialCapabilityError(ValueError):
    """The host-pinned PR credential capability is unsafe or unavailable."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrCredentialCapabilityError("PR credential capability is not canonical JSON") from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrCredentialCapabilityError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrCredentialCapabilityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrCredentialCapabilityError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrCredentialCapabilityError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_observation(value: Any) -> tuple[PilotExactTaskPrStateObservation, Any]:
    if type(value) is not PilotExactTaskPrStateObservation:
        raise PilotExactTaskPrCredentialCapabilityError("exact ADR-DC-056 PR-state observation is required")
    try:
        replayed = PilotExactTaskPrStateObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrCredentialCapabilityError("ADR-DC-056 observation replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrCredentialCapabilityError("ADR-DC-056 observation identity mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_PR_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.reservation_revalidated is not True
        or value.fixed_origin_github_read is not True
        or value.credential_free_read is not True
        or value.redirects_forbidden is not True
        or value.response_bounded is not True
        or value.no_existing_open_pr_verified is not True
        or value.create_new_draft_pull_request_required is not True
        or value.fresh_pr_state_revalidation_before_create_required is not True
        or value.maintainer_can_modify is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.pull_request_created is not False
        or value.ready_for_review_authorized is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or value.open_pr_match_count != 0
    ):
        raise PilotExactTaskPrCredentialCapabilityError("credential capability requires one live inert ADR-DC-056 observation")
    inputs = observation_boundary._get_live_pr_state_observation_inputs(value)
    reservation = None if inputs is None else inputs.get("pr_mutation_reservation")
    if (
        reservation is None
        or getattr(reservation, "reservation_authenticated", None) is not True
        or getattr(reservation, "sha256", None) != value.pr_mutation_reservation_sha256
        or getattr(reservation, "pr_mutation_nonce_sha256", None) != value.pr_mutation_nonce_sha256
        or getattr(reservation, "head_branch", None) != value.head_branch
        or getattr(reservation, "base_branch", None) != value.base_branch
    ):
        raise PilotExactTaskPrCredentialCapabilityError("ADR-DC-056 observation lost live reservation provenance")
    return value, reservation


def _descriptor(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrCredentialCapabilityError("host PR credential-broker descriptor is required")
    expected = {
        "broker_policy_sha256", "broker_executable_path", "broker_executable_path_sha256",
        "broker_executable_sha256", "broker_version", "credential_protocol", "secret_source",
        "secret_transport", "api_origin",
    }
    if set(value) != expected:
        raise PilotExactTaskPrCredentialCapabilityError("PR credential-broker descriptor fields mismatch")
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskPrCredentialCapabilityError("PR credential-broker descriptor contains invalid text")
    _hex64(result["broker_policy_sha256"], name="broker_policy_sha256")
    _hex64(result["broker_executable_path_sha256"], name="broker_executable_path_sha256")
    _hex64(result["broker_executable_sha256"], name="broker_executable_sha256")
    path = Path(result["broker_executable_path"])
    if not path.is_absolute():
        raise PilotExactTaskPrCredentialCapabilityError("PR credential-broker executable path must be absolute")
    expected_path_sha256 = hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()
    if result["broker_executable_path_sha256"] != expected_path_sha256:
        raise PilotExactTaskPrCredentialCapabilityError("PR credential-broker executable path hash mismatch")
    if _VERSION.fullmatch(result["broker_version"]) is None:
        raise PilotExactTaskPrCredentialCapabilityError("PR credential-broker version is invalid")
    if (
        result["credential_protocol"] != PILOT_EXACT_TASK_PR_CREDENTIAL_PROTOCOL
        or result["secret_source"] != PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_SOURCE
        or result["secret_transport"] != PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_TRANSPORT
        or result["api_origin"] != PILOT_EXACT_TASK_PR_CREDENTIAL_API_ORIGIN
    ):
        raise PilotExactTaskPrCredentialCapabilityError("PR credential-broker semantics are unsupported")
    return MappingProxyType(result)


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrStateObservation], Mapping[str, str]]] = {}

    def mark(capability: Any, observation: PilotExactTaskPrStateObservation, descriptor: Mapping[str, str]) -> None:
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
            pid != os.getpid()
            or capability_ref() is not capability
            or observation is None
            or observation.observation_authenticated is not True
            or observation.sha256 != capability.pr_state_observation_sha256
            or capability.sha256 != digest
            or descriptor.get("broker_policy_sha256") != capability.broker_policy_sha256
            or descriptor.get("broker_executable_path_sha256") != capability.broker_executable_path_sha256
            or descriptor.get("broker_executable_sha256") != capability.broker_executable_sha256
        ):
            return None
        return MappingProxyType({"pr_state_observation": observation, "credential_broker_descriptor": descriptor})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_pr_credential_capability_authenticated, _get_live_pr_credential_capability_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrCredentialCapability:
    pr_state_observation_sha256: str
    pr_mutation_reservation_sha256: str
    pr_mutation_requirements_sha256: str
    remote_write_transaction_sha256: str
    predicted_commit_sha: str
    pr_plan_sha256: str
    pr_mutation_nonce_sha256: str
    repository: str
    base_branch: str
    head_branch: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    secret_source: str
    secret_transport: str
    api_origin: str
    materialized_at_utc: str
    pr_mutation_slot_reserved: bool = True
    no_existing_open_pr_verified: bool = True
    credential_broker_host_pinned: bool = True
    credential_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    one_shot_draft_pr_create_required: bool = True
    fresh_pr_state_revalidation_before_create_required: bool = True
    post_create_readback_verification_required: bool = True
    maintainer_can_modify: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_created: bool = False
    ready_for_review_authorized: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_AUTHORITY:
            raise PilotExactTaskPrCredentialCapabilityError("PR credential capability schema/authority is unsupported")
        for name in (
            "pr_state_observation_sha256", "pr_mutation_reservation_sha256", "pr_mutation_requirements_sha256",
            "remote_write_transaction_sha256", "pr_plan_sha256", "pr_mutation_nonce_sha256", "broker_policy_sha256",
            "broker_executable_path_sha256", "broker_executable_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.materialized_at_utc, name="materialized_at_utc")
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol != PILOT_EXACT_TASK_PR_CREDENTIAL_PROTOCOL
            or self.secret_source != PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_SOURCE
            or self.secret_transport != PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_TRANSPORT
            or self.api_origin != PILOT_EXACT_TASK_PR_CREDENTIAL_API_ORIGIN
        ):
            raise PilotExactTaskPrCredentialCapabilityError("PR credential capability binding is invalid")
        required_true = (
            "pr_mutation_slot_reserved", "no_existing_open_pr_verified", "credential_broker_host_pinned",
            "credential_broker_binary_verified", "credential_secret_not_loaded", "credential_broker_owns_https",
            "one_shot_draft_pr_create_required", "fresh_pr_state_revalidation_before_create_required",
            "post_create_readback_verification_required",
        )
        forced_false = (
            "credential_material_in_artifact", "credential_material_in_process_arguments", "credential_material_in_environment",
            "maintainer_can_modify", "pr_mutation_authorized", "pull_request_create_authorized", "pull_request_created",
            "ready_for_review_authorized", "reviewer_mutation_authorized", "label_mutation_authorized", "merge_authorized",
            "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrCredentialCapabilityError("PR credential capability evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrCredentialCapabilityError("PR credential capability cannot grant GitHub mutation authority")

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_credential_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrCredentialCapabilityError("PR credential capability must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrCredentialCapabilityError("PR credential capability fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pr_credential_capability(
    *, pr_state_observation: PilotExactTaskPrStateObservation, broker_descriptor: Mapping[str, Any], now_provider: Callable[[], str],
) -> PilotExactTaskPrCredentialCapability:
    observation, reservation = _require_live_observation(pr_state_observation)
    descriptor = _descriptor(broker_descriptor)
    materialized_at = now_provider()
    _utc(materialized_at, name="materialized_at_utc")
    result = PilotExactTaskPrCredentialCapability(
        pr_state_observation_sha256=observation.sha256,
        pr_mutation_reservation_sha256=observation.pr_mutation_reservation_sha256,
        pr_mutation_requirements_sha256=observation.pr_mutation_requirements_sha256,
        remote_write_transaction_sha256=observation.remote_write_transaction_sha256,
        predicted_commit_sha=observation.predicted_commit_sha,
        pr_plan_sha256=observation.pr_plan_sha256,
        pr_mutation_nonce_sha256=observation.pr_mutation_nonce_sha256,
        repository=observation.repository,
        base_branch=observation.base_branch,
        head_branch=observation.head_branch,
        broker_policy_sha256=descriptor["broker_policy_sha256"],
        broker_executable_path_sha256=descriptor["broker_executable_path_sha256"],
        broker_executable_sha256=descriptor["broker_executable_sha256"],
        broker_version=descriptor["broker_version"],
        credential_protocol=descriptor["credential_protocol"],
        secret_source=descriptor["secret_source"],
        secret_transport=descriptor["secret_transport"],
        api_origin=descriptor["api_origin"],
        materialized_at_utc=materialized_at,
    )
    if reservation.sha256 != result.pr_mutation_reservation_sha256:
        raise PilotExactTaskPrCredentialCapabilityError("PR credential capability lost exact reservation provenance")
    _mark_pr_credential_capability_authenticated(result, observation, descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrCredentialCapabilityError("PR credential capability lost live observation provenance")
    return result


def materialize_pilot_exact_task_pr_credential_capability(
    pr_state_observation: PilotExactTaskPrStateObservation,
) -> PilotExactTaskPrCredentialCapability:
    raise PilotExactTaskPrCredentialCapabilityError("production PR credential capability boundary is not installed")


__all__ = [
    "PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_SCHEMA", "PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_CREDENTIAL_PROTOCOL", "PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_SOURCE",
    "PILOT_EXACT_TASK_PR_CREDENTIAL_SECRET_TRANSPORT", "PILOT_EXACT_TASK_PR_CREDENTIAL_API_ORIGIN",
    "PilotExactTaskPrCredentialCapabilityError", "PilotExactTaskPrCredentialCapability",
    "materialize_pilot_exact_task_pr_credential_capability",
]
