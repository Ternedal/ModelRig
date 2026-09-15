"""ADR-DC-056 exact remote push execution preflight.

Accept only the exact live ADR-DC-055 opaque credential capability, perform a
fresh ADR-DC-050 double remote-head/local-source revalidation, and freeze the
non-secret request a later host credential broker invocation must satisfy.

This boundary never invokes the credential provider, obtains a credential
handle, pushes, mutates a PR, merges, releases, deploys, or activates production.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_remote_head_observation as observation_boundary
from . import improvement_pilot_exact_task_remote_push_capability_requirements as push_requirements_boundary
from . import improvement_pilot_exact_task_remote_publication_write_consumption as consumption_boundary
from . import _improvement_pilot_exact_task_remote_push_credential_capability_impl as credential_boundary
from ._improvement_pilot_exact_task_remote_push_credential_capability_impl import (
    PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY,
    GithubPushCredentialProviderAttestation,
    PilotExactTaskRemotePushCredentialCapability,
)

PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-push-execution-preflight/v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_AUTHORITY = (
    "host-preflighted-one-dc-l16-exact-remote-push-only"
)
PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCOPE = (
    "exact-github-push-execution-preflight-only-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_REQUEST_SCHEMA = (
    "modelrig-github-push-credential-broker-request/v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_OPERATION = (
    "resolve-one-opaque-slot-for-one-exact-github-push-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_RESPONSE_POLICY = (
    "opaque-process-bound-handle-only-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_MAX_AGE_SECONDS = 10

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskRemotePushExecutionPreflightError(ValueError):
    """Exact remote push execution preflight is malformed, stale, or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "remote push execution preflight is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskRemotePushExecutionPreflightError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskRemotePushExecutionPreflightError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskRemotePushExecutionPreflightError(f"{name} is invalid") from exc


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return _utc_text(datetime.now(timezone.utc))


def _require_live_capability(value: Any):
    if type(value) is not PilotExactTaskRemotePushCredentialCapability:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "exact ADR-DC-055 opaque credential capability is required"
        )
    try:
        replayed = PilotExactTaskRemotePushCredentialCapability.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-055 credential capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-055 credential capability identity mismatch"
        )
    required_true = (
        "provider_attestation_host_controlled",
        "provider_enabled",
        "provider_repository_scope_matched",
        "provider_remote_url_scope_matched",
        "provider_transport_scope_matched",
        "opaque_credential_handle_bound",
        "caller_supplied_credential_forbidden",
        "inherited_git_credential_helpers_forbidden",
        "interactive_credential_prompt_forbidden",
        "exact_push_refspec_bound",
        "fresh_remote_head_revalidation_at_push_required",
        "remote_publication_authorization_consumed",
    )
    forced_false = (
        "raw_credential_material_present",
        "credential_export_authorized",
        "credential_read_authorized",
        "remote_write_authorized",
        "push_authorized",
        "push_started",
        "push_completed",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or any(getattr(value, n) is not True for n in required_true)
        or any(getattr(value, n) is not False for n in forced_false)
    ):
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "preflight requires one live inert ADR-DC-055 capability"
        )

    cap_live = credential_boundary._get_live_remote_push_credential_capability_inputs(value)
    if cap_live is None:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-055 live capability provenance is unavailable"
        )
    push_requirements = cap_live.get("push_capability_requirements")
    provider = cap_live.get("provider_attestation")
    if (
        push_requirements is not value.push_capability_requirements
        or provider is not value.provider_attestation
        or type(provider) is not GithubPushCredentialProviderAttestation
    ):
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-055 live provider/requirements identity is unavailable"
        )

    req_live = push_requirements_boundary._get_live_remote_push_capability_requirements_inputs(
        push_requirements
    )
    if req_live is None:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-054 live requirements provenance is unavailable"
        )
    consumption = req_live.get("write_consumption_receipt")
    if consumption is None or consumption.sha256 != value.write_consumption_receipt_sha256:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-054 live consumption binding is unavailable"
        )

    consumption_live = consumption_boundary._get_live_remote_publication_write_consumption_inputs(
        consumption
    )
    if consumption_live is None:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-053 live consumption provenance is unavailable"
        )
    source_observation = consumption_live.get("fresh_remote_head_observation")
    if (
        source_observation is None
        or source_observation is not consumption.fresh_remote_head_observation
        or source_observation.observation_authenticated is not True
    ):
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-053 live remote observation provenance is unavailable"
        )
    observation_live = observation_boundary._get_live_remote_head_observation_inputs(
        source_observation
    )
    if observation_live is None:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "ADR-DC-050 live publication requirements are unavailable"
        )
    publication_requirements = observation_live.get("requirements")
    if (
        publication_requirements is None
        or publication_requirements is not source_observation.requirements
        or publication_requirements.sha256 != consumption.requirements_sha256
    ):
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "live ADR-DC-049 publication requirements identity mismatch"
        )
    return value, push_requirements, consumption, publication_requirements, provider


def _broker_request_values(
    capability: PilotExactTaskRemotePushCredentialCapability,
    fresh_observation: Any,
) -> dict[str, Any]:
    requirements = capability.push_capability_requirements
    return {
        "schema": PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_REQUEST_SCHEMA,
        "credential_capability_sha256": capability.sha256,
        "push_capability_requirements_sha256": capability.push_capability_requirements_sha256,
        "provider_instance_id": capability.provider_instance_id,
        "provider_epoch": capability.provider_epoch,
        "credential_slot_sha256": capability.credential_slot_sha256,
        "repository": capability.repository,
        "canonical_remote_url": capability.canonical_remote_url,
        "local_commit_sha": capability.local_commit_sha,
        "destination_ref": capability.destination_ref,
        "push_refspec": capability.push_refspec,
        "remote_publication_nonce_sha256": capability.remote_publication_nonce_sha256,
        "fresh_remote_head_observation_sha256": fresh_observation.sha256,
        "expected_remote_head_present": requirements.expected_remote_head_present,
        "expected_remote_head_sha": requirements.expected_remote_head_sha,
        "publication_mode": requirements.publication_mode,
        "broker_operation": PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_OPERATION,
        "broker_response_policy": PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_RESPONSE_POLICY,
    }


def _broker_request_sha256(
    capability: PilotExactTaskRemotePushCredentialCapability,
    fresh_observation: Any,
) -> str:
    return hashlib.sha256(
        _canonical(_broker_request_values(capability, fresh_observation)).encode("utf-8")
    ).hexdigest()


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], weakref.ReferenceType[Any]]] = {}

    def mark(preflight: Any, capability: Any, fresh_observation: Any) -> None:
        key = id(preflight)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            preflight.sha256,
            weakref.ref(preflight, cleanup),
            weakref.ref(capability),
            weakref.ref(fresh_observation),
        )

    def get(preflight: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(preflight))
        if entry is None:
            return None
        pid, digest, preflight_ref, capability_ref, observation_ref = entry
        capability = capability_ref()
        observation = observation_ref()
        if (
            pid != os.getpid()
            or preflight_ref() is not preflight
            or capability is None
            or observation is None
            or capability.capability_authenticated is not True
            or observation.observation_authenticated is not True
        ):
            return None
        try:
            if preflight.sha256 != digest:
                return None
        except (AttributeError, TypeError, ValueError):
            return None
        return MappingProxyType(
            {
                "credential_capability": capability,
                "fresh_remote_head_observation": observation,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_push_execution_preflight_authenticated, _get_live_remote_push_execution_preflight_inputs = (
    _live_registry()
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePushExecutionPreflight:
    credential_capability: PilotExactTaskRemotePushCredentialCapability
    credential_capability_sha256: str
    push_capability_requirements_sha256: str
    write_consumption_receipt_sha256: str
    fresh_remote_head_observation: Any
    fresh_remote_head_observation_sha256: str
    fresh_observation_key_sha256: str
    repository: str
    base_sha: str
    local_commit_sha: str
    destination_ref: str
    canonical_remote_url: str
    push_refspec: str
    remote_publication_nonce_sha256: str
    provider_attestation_sha256: str
    provider_instance_id: str
    provider_epoch: int
    credential_slot_sha256: str
    expected_remote_head_present: bool
    expected_remote_head_sha: str | None
    publication_mode: str
    preflight_started_at_utc: str
    fresh_remote_observation_started_at_utc: str
    fresh_remote_observation_completed_at_utc: str
    preflight_completed_at_utc: str
    preflight_expires_at_utc: str
    broker_request_schema: str = PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_REQUEST_SCHEMA
    broker_request_sha256: str = "f" * 64
    broker_operation: str = PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_OPERATION
    broker_response_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_RESPONSE_POLICY
    preflight_scope: str = PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCOPE
    credential_capability_authenticated_at_preflight: bool = True
    fresh_remote_head_revalidation_completed: bool = True
    exact_remote_state_unchanged: bool = True
    local_source_state_revalidated: bool = True
    provider_attestation_replay_revalidated: bool = True
    opaque_credential_slot_bound: bool = True
    credential_broker_invocation_required: bool = True
    credential_broker_invoked: bool = False
    credential_handle_materialized: bool = False
    raw_credential_material_present: bool = False
    credential_export_authorized: bool = False
    credential_read_authorized: bool = False
    inherited_git_credential_helpers_forbidden: bool = True
    interactive_credential_prompt_forbidden: bool = True
    exact_push_refspec_bound: bool = True
    push_transaction_must_revalidate_provider_attestation: bool = True
    push_transaction_must_revalidate_remote_head: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    push_started: bool = False
    push_completed: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCHEMA

    def __post_init__(self) -> None:
        capability = self.credential_capability
        if type(capability) is not PilotExactTaskRemotePushCredentialCapability:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "embedded ADR-DC-055 credential capability is invalid"
            )
        try:
            cap_replay = PilotExactTaskRemotePushCredentialCapability.from_mapping(
                capability.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "embedded ADR-DC-055 capability replay failed"
            ) from exc
        if cap_replay != capability or cap_replay.sha256 != capability.sha256:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "embedded ADR-DC-055 capability identity mismatch"
            )

        observation = self.fresh_remote_head_observation
        if type(observation) is not observation_boundary.PilotExactTaskRemoteHeadObservation:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "embedded fresh ADR-DC-050 observation is invalid"
            )
        try:
            obs_replay = observation_boundary.PilotExactTaskRemoteHeadObservation.from_mapping(
                observation.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "embedded fresh ADR-DC-050 observation replay failed"
            ) from exc
        if obs_replay != observation or obs_replay.sha256 != observation.sha256:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "embedded fresh ADR-DC-050 observation identity mismatch"
            )

        if (
            self.schema != PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCHEMA
            or self.authority != PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_AUTHORITY
            or self.preflight_scope != PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCOPE
            or self.broker_request_schema != PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_REQUEST_SCHEMA
            or self.broker_operation != PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_OPERATION
            or self.broker_response_policy != PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_RESPONSE_POLICY
        ):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "remote push preflight policy identity mismatch"
            )

        for name in (
            "credential_capability_sha256",
            "push_capability_requirements_sha256",
            "write_consumption_receipt_sha256",
            "fresh_remote_head_observation_sha256",
            "fresh_observation_key_sha256",
            "remote_publication_nonce_sha256",
            "provider_attestation_sha256",
            "credential_slot_sha256",
            "broker_request_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "local_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.expected_remote_head_sha is not None:
            _hex40(self.expected_remote_head_sha, name="expected_remote_head_sha")
        if isinstance(self.provider_epoch, bool) or not isinstance(self.provider_epoch, int) or self.provider_epoch < 1:
            raise PilotExactTaskRemotePushExecutionPreflightError("provider_epoch is invalid")

        requirements = capability.push_capability_requirements
        bindings = {
            "credential_capability_sha256": capability.sha256,
            "push_capability_requirements_sha256": capability.push_capability_requirements_sha256,
            "write_consumption_receipt_sha256": capability.write_consumption_receipt_sha256,
            "repository": capability.repository,
            "base_sha": requirements.base_sha,
            "local_commit_sha": capability.local_commit_sha,
            "destination_ref": capability.destination_ref,
            "canonical_remote_url": capability.canonical_remote_url,
            "push_refspec": capability.push_refspec,
            "remote_publication_nonce_sha256": capability.remote_publication_nonce_sha256,
            "provider_attestation_sha256": capability.provider_attestation_sha256,
            "provider_instance_id": capability.provider_instance_id,
            "provider_epoch": capability.provider_epoch,
            "credential_slot_sha256": capability.credential_slot_sha256,
            "expected_remote_head_present": requirements.expected_remote_head_present,
            "expected_remote_head_sha": requirements.expected_remote_head_sha,
            "publication_mode": requirements.publication_mode,
            "fresh_remote_head_observation_sha256": observation.sha256,
            "fresh_observation_key_sha256": observation.observation_key_sha256,
        }
        mismatch = next(
            (name for name, expected in bindings.items() if getattr(self, name) != expected),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                f"remote push preflight binding mismatch: {mismatch}"
            )
        if (
            observation.repository != self.repository
            or observation.base_sha != self.base_sha
            or observation.local_commit_sha != self.local_commit_sha
            or observation.destination_ref != self.destination_ref
            or observation.canonical_remote_url != self.canonical_remote_url
            or observation.remote_head_present != self.expected_remote_head_present
            or observation.remote_head_sha != self.expected_remote_head_sha
            or observation.publication_mode != self.publication_mode
            or observation.network_access_performed is not True
            or observation.credential_material_present is not False
            or observation.local_commit_state_matched is not True
            or observation.remote_write_authorized is not False
            or observation.push_authorized is not False
        ):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "fresh ADR-DC-050 observation does not match exact push capability"
            )

        provider = capability.provider_attestation
        try:
            provider_replay = GithubPushCredentialProviderAttestation.from_mapping(
                provider.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "embedded provider attestation replay failed"
            ) from exc
        if provider_replay != provider or provider_replay.sha256 != self.provider_attestation_sha256:
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "provider attestation replay identity mismatch"
            )

        started = _utc(self.preflight_started_at_utc, name="preflight_started_at_utc")
        obs_started = _utc(
            self.fresh_remote_observation_started_at_utc,
            name="fresh_remote_observation_started_at_utc",
        )
        obs_completed = _utc(
            self.fresh_remote_observation_completed_at_utc,
            name="fresh_remote_observation_completed_at_utc",
        )
        completed = _utc(self.preflight_completed_at_utc, name="preflight_completed_at_utc")
        expires = _utc(self.preflight_expires_at_utc, name="preflight_expires_at_utc")
        cap_start = _utc(
            capability.capability_materialized_at_utc,
            name="credential capability materialized_at_utc",
        )
        cap_expiry = _utc(
            capability.capability_expires_at_utc,
            name="credential capability expires_at_utc",
        )
        provider_expiry = _utc(
            capability.provider_expires_at_utc,
            name="provider expires_at_utc",
        )
        req_expiry = _utc(
            requirements.capability_expires_at_utc,
            name="push requirements expires_at_utc",
        )
        if not (
            cap_start <= started <= obs_started <= obs_completed <= completed < expires
            and expires <= cap_expiry
            and expires <= provider_expiry
            and expires <= req_expiry
        ):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "remote push preflight timestamps are stale or non-monotonic"
            )
        expected_expiry = min(
            cap_expiry,
            provider_expiry,
            req_expiry,
            completed
            + timedelta(seconds=PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_MAX_AGE_SECONDS),
        )
        if self.preflight_expires_at_utc != _utc_text(expected_expiry):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "remote push preflight expiry mismatch"
            )
        if (
            self.fresh_remote_observation_started_at_utc
            != observation.observation_started_at_utc
            or self.fresh_remote_observation_completed_at_utc
            != observation.observation_completed_at_utc
        ):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "fresh remote observation timestamp binding mismatch"
            )
        if self.broker_request_sha256 != _broker_request_sha256(capability, observation):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "credential broker request identity mismatch"
            )

        required_true = (
            "credential_capability_authenticated_at_preflight",
            "fresh_remote_head_revalidation_completed",
            "exact_remote_state_unchanged",
            "local_source_state_revalidated",
            "provider_attestation_replay_revalidated",
            "opaque_credential_slot_bound",
            "credential_broker_invocation_required",
            "inherited_git_credential_helpers_forbidden",
            "interactive_credential_prompt_forbidden",
            "exact_push_refspec_bound",
            "push_transaction_must_revalidate_provider_attestation",
            "push_transaction_must_revalidate_remote_head",
        )
        forced_false = (
            "credential_broker_invoked",
            "credential_handle_materialized",
            "raw_credential_material_present",
            "credential_export_authorized",
            "credential_read_authorized",
            "remote_write_authorized",
            "push_authorized",
            "push_started",
            "push_completed",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "required remote push preflight evidence is not satisfied"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "remote push preflight cannot invoke credentials or grant push authority"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemotePushExecutionPreflight":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "remote push execution preflight fields mismatch"
            )
        data = dict(value)
        capability = data.get("credential_capability")
        observation = data.get("fresh_remote_head_observation")
        if not isinstance(capability, Mapping) or not isinstance(observation, Mapping):
            raise PilotExactTaskRemotePushExecutionPreflightError(
                "nested preflight evidence must be objects"
            )
        data["credential_capability"] = PilotExactTaskRemotePushCredentialCapability.from_mapping(
            capability
        )
        data["fresh_remote_head_observation"] = (
            observation_boundary.PilotExactTaskRemoteHeadObservation.from_mapping(observation)
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.credential_capability.to_dict()
                if name == "credential_capability"
                else self.fresh_remote_head_observation.to_dict()
                if name == "fresh_remote_head_observation"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def preflight_authenticated(self) -> bool:
        return _get_live_remote_push_execution_preflight_inputs(self) is not None


def _preflight_verified_pilot_exact_task_remote_push(
    *,
    credential_capability: PilotExactTaskRemotePushCredentialCapability,
    now_provider=_now_utc_seconds,
) -> PilotExactTaskRemotePushExecutionPreflight:
    (
        capability,
        push_requirements,
        _consumption,
        publication_requirements,
        provider,
    ) = _require_live_capability(credential_capability)

    preflight_started_at = now_provider()
    started = _utc(preflight_started_at, name="preflight_started_at_utc")
    cap_expiry = _utc(
        capability.capability_expires_at_utc,
        name="credential capability expires_at_utc",
    )
    provider_expiry = _utc(
        capability.provider_expires_at_utc,
        name="provider expires_at_utc",
    )
    req_expiry = _utc(
        push_requirements.capability_expires_at_utc,
        name="push requirements expires_at_utc",
    )
    if started < _utc(
        capability.capability_materialized_at_utc,
        name="credential capability materialized_at_utc",
    ):
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "system clock predates ADR-DC-055 credential capability"
        )
    if started >= cap_expiry or started >= provider_expiry or started >= req_expiry:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "push capability expired before execution preflight"
        )
    try:
        provider_replay = GithubPushCredentialProviderAttestation.from_mapping(
            provider.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "live provider attestation replay validation failed"
        ) from exc
    if provider_replay != provider or provider_replay.sha256 != capability.provider_attestation_sha256:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "live provider attestation identity mismatch"
        )

    try:
        fresh = observation_boundary._observe_verified_pilot_exact_task_remote_head(
            requirements=publication_requirements,
            now_provider=now_provider,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "fresh push-time remote-head revalidation failed"
        ) from exc
    if (
        fresh.observation_authenticated is not True
        or fresh.repository != capability.repository
        or fresh.base_sha != push_requirements.base_sha
        or fresh.local_commit_sha != capability.local_commit_sha
        or fresh.destination_ref != capability.destination_ref
        or fresh.canonical_remote_url != capability.canonical_remote_url
        or fresh.remote_head_present != push_requirements.expected_remote_head_present
        or fresh.remote_head_sha != push_requirements.expected_remote_head_sha
        or fresh.publication_mode != push_requirements.publication_mode
        or fresh.local_commit_state_matched is not True
        or fresh.network_access_performed is not True
        or fresh.credential_material_present is not False
        or fresh.remote_write_authorized is not False
        or fresh.push_authorized is not False
    ):
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "remote state changed since exact push capability was frozen"
        )

    preflight_completed_at = now_provider()
    completed = _utc(preflight_completed_at, name="preflight_completed_at_utc")
    fresh_completed = _utc(
        fresh.observation_completed_at_utc,
        name="fresh remote observation completed_at_utc",
    )
    if completed < fresh_completed:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "system clock moved backwards during remote push preflight"
        )
    if completed >= cap_expiry or completed >= provider_expiry or completed >= req_expiry:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "push capability expired during execution preflight"
        )
    expiry = min(
        cap_expiry,
        provider_expiry,
        req_expiry,
        completed
        + timedelta(seconds=PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_MAX_AGE_SECONDS),
    )
    if expiry <= completed:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "remote push preflight has no positive execution window"
        )

    preflight = PilotExactTaskRemotePushExecutionPreflight(
        credential_capability=capability,
        credential_capability_sha256=capability.sha256,
        push_capability_requirements_sha256=capability.push_capability_requirements_sha256,
        write_consumption_receipt_sha256=capability.write_consumption_receipt_sha256,
        fresh_remote_head_observation=fresh,
        fresh_remote_head_observation_sha256=fresh.sha256,
        fresh_observation_key_sha256=fresh.observation_key_sha256,
        repository=capability.repository,
        base_sha=push_requirements.base_sha,
        local_commit_sha=capability.local_commit_sha,
        destination_ref=capability.destination_ref,
        canonical_remote_url=capability.canonical_remote_url,
        push_refspec=capability.push_refspec,
        remote_publication_nonce_sha256=capability.remote_publication_nonce_sha256,
        provider_attestation_sha256=capability.provider_attestation_sha256,
        provider_instance_id=capability.provider_instance_id,
        provider_epoch=capability.provider_epoch,
        credential_slot_sha256=capability.credential_slot_sha256,
        expected_remote_head_present=push_requirements.expected_remote_head_present,
        expected_remote_head_sha=push_requirements.expected_remote_head_sha,
        publication_mode=push_requirements.publication_mode,
        preflight_started_at_utc=preflight_started_at,
        fresh_remote_observation_started_at_utc=fresh.observation_started_at_utc,
        fresh_remote_observation_completed_at_utc=fresh.observation_completed_at_utc,
        preflight_completed_at_utc=preflight_completed_at,
        preflight_expires_at_utc=_utc_text(expiry),
        broker_request_sha256=_broker_request_sha256(capability, fresh),
    )
    _mark_push_execution_preflight_authenticated(preflight, capability, fresh)
    if preflight.preflight_authenticated is not True:
        raise PilotExactTaskRemotePushExecutionPreflightError(
            "live remote push preflight provenance was not established"
        )
    return preflight


def preflight_pilot_exact_task_remote_push(
    credential_capability: PilotExactTaskRemotePushCredentialCapability,
) -> PilotExactTaskRemotePushExecutionPreflight:
    """Perform one exact read-only preflight for a later fixed push transaction."""
    return _preflight_verified_pilot_exact_task_remote_push(
        credential_capability=credential_capability,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUSH_EXECUTION_PREFLIGHT_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_REQUEST_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_OPERATION",
    "PILOT_EXACT_TASK_REMOTE_PUSH_BROKER_RESPONSE_POLICY",
    "PilotExactTaskRemotePushExecutionPreflightError",
    "PilotExactTaskRemotePushExecutionPreflight",
    "preflight_pilot_exact_task_remote_push",
]
