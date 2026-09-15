"""ADR-DC-055 host-pinned opaque GitHub push credential capability.

This boundary accepts only the exact live ADR-DC-054 push-capability requirements
and one host-controlled provider attestation. It binds a short-lived opaque
credential slot to one exact repository / URL / refspec without loading, exposing,
or exporting credential material.

It performs no Git invocation, no network access and no push. A later fixed push
transaction must require this exact live capability and must revalidate the remote
head again immediately before remote mutation.
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

from . import improvement_pilot_exact_task_remote_push_capability_requirements as requirements_boundary
from .improvement_pilot_exact_task_remote_push_capability_requirements import (
    PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_AUTHORITY,
    PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY,
    PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE,
    PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY,
    PilotExactTaskRemotePushCapabilityRequirements,
)

PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-push-credential-capability/v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-bound-one-dc-l16-exact-github-push-credential-capability-only"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCOPE = (
    "opaque-host-pinned-github-push-credential-capability-only-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_ATTESTATION_SCHEMA = (
    "modelrig-github-push-credential-provider-attestation/v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_MAX_AGE_SECONDS = 30

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_BRANCH_REF = re.compile(r"^refs/heads/[A-Za-z0-9._/-]+$")


class PilotExactTaskRemotePushCredentialCapabilityError(ValueError):
    """Opaque GitHub push credential capability is malformed or unsafe."""


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
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "credential capability is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskRemotePushCredentialCapabilityError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskRemotePushCredentialCapabilityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            f"{name} is invalid"
        ) from exc


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return _utc_text(datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True, weakref_slot=True)
class GithubPushCredentialProviderAttestation:
    provider_instance_id: str
    provider_epoch: int
    credential_slot_sha256: str
    repository: str
    canonical_remote_url: str
    attested_at_utc: str
    expires_at_utc: str
    enabled: bool = True
    raw_credential_material_present: bool = False
    credential_export_allowed: bool = False
    provider_interface: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE
    credential_custody_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY
    transport_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_ATTESTATION_SCHEMA
            or self.provider_interface != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE
            or self.credential_custody_policy != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY
            or self.transport_policy != PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY
        ):
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider attestation policy identity mismatch"
            )
        if not isinstance(self.provider_instance_id, str) or _PROVIDER_ID.fullmatch(self.provider_instance_id) is None:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider instance id is invalid"
            )
        if isinstance(self.provider_epoch, bool) or not isinstance(self.provider_epoch, int) or self.provider_epoch < 1 or self.provider_epoch > 2**63 - 1:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider epoch is invalid"
            )
        _hex64(self.credential_slot_sha256, name="credential_slot_sha256")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.canonical_remote_url, str)
            or not self.canonical_remote_url.startswith("https://github.com/")
            or not self.canonical_remote_url.endswith(".git")
        ):
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider repository/remote scope is invalid"
            )
        start = _utc(self.attested_at_utc, name="attested_at_utc")
        end = _utc(self.expires_at_utc, name="expires_at_utc")
        if end <= start:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider attestation expiry is not after attestation"
            )
        if self.enabled is not True:
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential provider is disabled")
        if self.raw_credential_material_present is not False:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider attestation must not contain credential material"
            )
        if self.credential_export_allowed is not False:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider may not export credential material"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "GithubPushCredentialProviderAttestation":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential provider attestation fields mismatch"
            )
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _require_live_requirements(value: Any) -> tuple[PilotExactTaskRemotePushCapabilityRequirements, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskRemotePushCapabilityRequirements:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "exact ADR-DC-054 push-capability requirements are required"
        )
    try:
        replayed = PilotExactTaskRemotePushCapabilityRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "ADR-DC-054 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "ADR-DC-054 requirements identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_AUTHORITY
        or value.requirements_authenticated is not True
        or value.push_capability_requirements_materialized is not True
        or value.remote_publication_authorization_consumed is not True
        or value.host_pinned_credential_provider_required is not True
        or value.caller_supplied_credential_forbidden is not True
        or value.credential_material_present is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.push_started is not False
        or value.push_completed is not False
    ):
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "credential capability requires one live inert ADR-DC-054 manifest"
        )
    live = requirements_boundary._get_live_remote_push_capability_requirements_inputs(value)
    if live is None:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "ADR-DC-054 live provenance is unavailable"
        )
    return value, MappingProxyType(dict(live))


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], weakref.ReferenceType[Any]]] = {}

    def mark(capability: Any, requirements: PilotExactTaskRemotePushCapabilityRequirements, attestation: GithubPushCredentialProviderAttestation) -> None:
        key = id(capability)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            capability.sha256,
            weakref.ref(capability, cleanup),
            weakref.ref(requirements),
            weakref.ref(attestation),
        )

    def get(capability: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(capability))
        if entry is None:
            return None
        pid, digest, capability_ref, requirements_ref, attestation_ref = entry
        requirements = requirements_ref()
        attestation = attestation_ref()
        if (
            pid != os.getpid()
            or capability_ref() is not capability
            or requirements is None
            or attestation is None
            or requirements.requirements_authenticated is not True
        ):
            return None
        try:
            if capability.sha256 != digest:
                return None
        except (AttributeError, TypeError, ValueError):
            return None
        return MappingProxyType({
            "push_capability_requirements": requirements,
            "provider_attestation": attestation,
        })

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_credential_capability_authenticated, _get_live_remote_push_credential_capability_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePushCredentialCapability:
    push_capability_requirements: PilotExactTaskRemotePushCapabilityRequirements
    push_capability_requirements_sha256: str
    write_consumption_receipt_sha256: str
    repository: str
    local_commit_sha: str
    destination_ref: str
    canonical_remote_url: str
    push_refspec: str
    remote_publication_nonce_sha256: str
    provider_attestation: GithubPushCredentialProviderAttestation
    provider_attestation_sha256: str
    provider_instance_id: str
    provider_epoch: int
    credential_slot_sha256: str
    provider_attested_at_utc: str
    provider_expires_at_utc: str
    capability_materialized_at_utc: str
    capability_expires_at_utc: str
    provider_interface: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE
    credential_custody_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY
    transport_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY
    scope: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCOPE
    provider_attestation_host_controlled: bool = True
    provider_enabled: bool = True
    provider_repository_scope_matched: bool = True
    provider_remote_url_scope_matched: bool = True
    provider_transport_scope_matched: bool = True
    opaque_credential_handle_bound: bool = True
    raw_credential_material_present: bool = False
    credential_export_authorized: bool = False
    credential_read_authorized: bool = False
    caller_supplied_credential_forbidden: bool = True
    inherited_git_credential_helpers_forbidden: bool = True
    interactive_credential_prompt_forbidden: bool = True
    exact_push_refspec_bound: bool = True
    fresh_remote_head_revalidation_at_push_required: bool = True
    remote_publication_authorization_consumed: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    push_started: bool = False
    push_completed: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        requirements = self.push_capability_requirements
        if type(requirements) is not PilotExactTaskRemotePushCapabilityRequirements:
            raise PilotExactTaskRemotePushCredentialCapabilityError("nested ADR-DC-054 requirements are invalid")
        try:
            replayed = PilotExactTaskRemotePushCapabilityRequirements.from_mapping(requirements.to_dict())
        except Exception as exc:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "nested ADR-DC-054 requirements replay validation failed"
            ) from exc
        if replayed != requirements or replayed.sha256 != requirements.sha256:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "nested ADR-DC-054 requirements identity mismatch"
            )
        attestation = self.provider_attestation
        if type(attestation) is not GithubPushCredentialProviderAttestation:
            raise PilotExactTaskRemotePushCredentialCapabilityError("nested credential provider attestation is invalid")
        try:
            replayed_attestation = GithubPushCredentialProviderAttestation.from_mapping(attestation.to_dict())
        except Exception as exc:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "nested credential provider attestation replay validation failed"
            ) from exc
        if (
            replayed_attestation != attestation
            or attestation.sha256 != self.provider_attestation_sha256
            or attestation.repository != requirements.repository
            or attestation.canonical_remote_url != requirements.canonical_remote_url
            or attestation.provider_instance_id != self.provider_instance_id
            or attestation.provider_epoch != self.provider_epoch
            or attestation.credential_slot_sha256 != self.credential_slot_sha256
            or attestation.attested_at_utc != self.provider_attested_at_utc
            or attestation.expires_at_utc != self.provider_expires_at_utc
        ):
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential provider attestation binding mismatch")
        if (
            self.schema != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCHEMA
            or self.authority != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY
            or self.scope != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCOPE
            or self.provider_interface != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE
            or self.credential_custody_policy != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY
            or self.transport_policy != PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY
        ):
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential capability policy identity mismatch")
        for name in (
            "push_capability_requirements_sha256",
            "write_consumption_receipt_sha256",
            "remote_publication_nonce_sha256",
            "provider_attestation_sha256",
            "credential_slot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.local_commit_sha, name="local_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.destination_ref, str)
            or _BRANCH_REF.fullmatch(self.destination_ref) is None
            or not isinstance(self.canonical_remote_url, str)
            or not self.canonical_remote_url.startswith("https://github.com/")
            or not self.canonical_remote_url.endswith(".git")
            or not isinstance(self.provider_instance_id, str)
            or _PROVIDER_ID.fullmatch(self.provider_instance_id) is None
        ):
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential capability identity fields are invalid")
        if isinstance(self.provider_epoch, bool) or not isinstance(self.provider_epoch, int) or self.provider_epoch < 1:
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential capability provider epoch is invalid")
        expected = {
            "push_capability_requirements_sha256": requirements.sha256,
            "write_consumption_receipt_sha256": requirements.write_consumption_receipt_sha256,
            "repository": requirements.repository,
            "local_commit_sha": requirements.local_commit_sha,
            "destination_ref": requirements.destination_ref,
            "canonical_remote_url": requirements.canonical_remote_url,
            "push_refspec": requirements.push_refspec,
            "remote_publication_nonce_sha256": requirements.remote_publication_nonce_sha256,
        }
        mismatch = next((name for name, item in expected.items() if getattr(self, name) != item), None)
        if mismatch is not None:
            raise PilotExactTaskRemotePushCredentialCapabilityError(f"credential capability binding mismatch: {mismatch}")
        materialized = _utc(self.capability_materialized_at_utc, name="capability_materialized_at_utc")
        expires = _utc(self.capability_expires_at_utc, name="capability_expires_at_utc")
        provider_start = _utc(self.provider_attested_at_utc, name="provider_attested_at_utc")
        provider_end = _utc(self.provider_expires_at_utc, name="provider_expires_at_utc")
        requirements_end = _utc(requirements.capability_expires_at_utc, name="requirements capability_expires_at_utc")
        if not provider_start <= materialized < provider_end:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "provider attestation is not live at capability materialization"
            )
        if not materialized < expires <= provider_end or expires > requirements_end:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential capability expiry exceeds provider/requirements authority"
            )
        if expires - materialized > timedelta(seconds=PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_MAX_AGE_SECONDS):
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential capability lifetime exceeds policy")
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential capability lost required evidence")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "credential capability cannot expose secrets or grant remote authority"
            )

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["push_capability_requirements"] = self.push_capability_requirements.to_dict()
        result["provider_attestation"] = self.provider_attestation.to_dict()
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemotePushCredentialCapability":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePushCredentialCapabilityError("credential capability fields mismatch")
        mapped = dict(value)
        try:
            mapped["push_capability_requirements"] = PilotExactTaskRemotePushCapabilityRequirements.from_mapping(
                mapped["push_capability_requirements"]
            )
            mapped["provider_attestation"] = GithubPushCredentialProviderAttestation.from_mapping(
                mapped["provider_attestation"]
            )
        except Exception as exc:
            raise PilotExactTaskRemotePushCredentialCapabilityError(
                "nested ADR-DC-054 requirements/provider attestation are invalid"
            ) from exc
        return cls(**mapped)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_remote_push_credential_capability_inputs(self) is not None


def _materialize_verified_pilot_exact_task_remote_push_credential_capability(
    *,
    push_capability_requirements: PilotExactTaskRemotePushCapabilityRequirements,
    provider_attestation: GithubPushCredentialProviderAttestation,
    provider_attestation_host_controlled: bool,
    now_provider=_now_utc_seconds,
) -> PilotExactTaskRemotePushCredentialCapability:
    requirements, _live = _require_live_requirements(push_capability_requirements)
    if type(provider_attestation) is not GithubPushCredentialProviderAttestation:
        raise PilotExactTaskRemotePushCredentialCapabilityError("exact host provider attestation is required")
    try:
        replayed_attestation = GithubPushCredentialProviderAttestation.from_mapping(provider_attestation.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemotePushCredentialCapabilityError("provider attestation replay validation failed") from exc
    if replayed_attestation != provider_attestation:
        raise PilotExactTaskRemotePushCredentialCapabilityError("provider attestation replay identity mismatch")
    if provider_attestation_host_controlled is not True:
        raise PilotExactTaskRemotePushCredentialCapabilityError("credential provider attestation is not host-controlled")
    if provider_attestation.repository != requirements.repository or provider_attestation.canonical_remote_url != requirements.canonical_remote_url:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "credential provider scope does not match exact push requirements"
        )
    now_text = now_provider()
    now = _utc(now_text, name="capability_materialized_at_utc")
    requirements_expiry = _utc(requirements.capability_expires_at_utc, name="requirements capability_expires_at_utc")
    provider_expiry = _utc(provider_attestation.expires_at_utc, name="provider expires_at_utc")
    provider_start = _utc(provider_attestation.attested_at_utc, name="provider attested_at_utc")
    if now < provider_start:
        raise PilotExactTaskRemotePushCredentialCapabilityError("system clock predates credential provider attestation")
    if now >= requirements_expiry:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "ADR-DC-054 push-capability requirements expired before provider binding"
        )
    if now >= provider_expiry:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "credential provider attestation expired before capability binding"
        )
    expiry = min(
        requirements_expiry,
        provider_expiry,
        now + timedelta(seconds=PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_MAX_AGE_SECONDS),
    )
    capability = PilotExactTaskRemotePushCredentialCapability(
        push_capability_requirements=requirements,
        push_capability_requirements_sha256=requirements.sha256,
        write_consumption_receipt_sha256=requirements.write_consumption_receipt_sha256,
        repository=requirements.repository,
        local_commit_sha=requirements.local_commit_sha,
        destination_ref=requirements.destination_ref,
        canonical_remote_url=requirements.canonical_remote_url,
        push_refspec=requirements.push_refspec,
        remote_publication_nonce_sha256=requirements.remote_publication_nonce_sha256,
        provider_attestation=provider_attestation,
        provider_attestation_sha256=provider_attestation.sha256,
        provider_instance_id=provider_attestation.provider_instance_id,
        provider_epoch=provider_attestation.provider_epoch,
        credential_slot_sha256=provider_attestation.credential_slot_sha256,
        provider_attested_at_utc=provider_attestation.attested_at_utc,
        provider_expires_at_utc=provider_attestation.expires_at_utc,
        capability_materialized_at_utc=now_text,
        capability_expires_at_utc=_utc_text(expiry),
    )
    _mark_credential_capability_authenticated(capability, requirements, provider_attestation)
    if capability.capability_authenticated is not True:
        raise PilotExactTaskRemotePushCredentialCapabilityError(
            "live opaque credential capability provenance was not established"
        )
    return capability


def materialize_pilot_exact_task_remote_push_credential_capability(
    push_capability_requirements: PilotExactTaskRemotePushCapabilityRequirements,
) -> PilotExactTaskRemotePushCredentialCapability:
    raise PilotExactTaskRemotePushCredentialCapabilityError(
        "production opaque GitHub push credential boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CAPABILITY_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_ATTESTATION_SCHEMA",
    "PilotExactTaskRemotePushCredentialCapabilityError",
    "PilotExactTaskRemotePushCredentialCapability",
    "materialize_pilot_exact_task_remote_push_credential_capability",
]
