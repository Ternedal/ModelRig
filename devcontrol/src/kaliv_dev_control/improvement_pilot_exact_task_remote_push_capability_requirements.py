"""ADR-DC-054 exact remote push-capability requirements.

This boundary accepts only the exact live ADR-DC-053 write-consumption receipt
and freezes the requirements for one later fixed push transaction. It binds the
exact consumed publication intent, source commit, destination branch, expected
remote state, credential-custody policy and fixed push policy.

It does not load credentials, perform network access, invoke Git, push, mutate a
PR, merge, release, deploy, or activate production.
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

from . import improvement_pilot_exact_task_remote_publication_write_consumption as consumption_boundary
from .improvement_pilot_exact_task_remote_publication_write_consumption import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY,
    PilotExactTaskRemotePublicationWriteConsumptionReceipt,
)

PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-push-capability-requirements/v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_AUTHORITY = (
    "host-planned-one-dc-l16-exact-remote-push-capability-only"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCOPE = (
    "exact-github-push-capability-requirements-only-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY = (
    "host-pinned-github-https-transport-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY = (
    "host-pinned-out-of-process-github-credential-provider-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE = (
    "modelrig-github-push-credential-provider/v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_OPERATION = (
    "push-one-exact-commit-to-one-exact-branch-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_STATE_COMPARE_POLICY = (
    "exact-observed-head-or-absence-match-before-push-v1"
)
PILOT_EXACT_TASK_REMOTE_PUSH_OUTPUT_POLICY = "bounded-porcelain-v1"
PILOT_EXACT_TASK_REMOTE_PUSH_TIMEOUT_SECONDS = 60
PILOT_EXACT_TASK_REMOTE_PUSH_MAX_OUTPUT_BYTES = 65536
PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_MAX_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_BRANCH_REF = re.compile(r"^refs/heads/[A-Za-z0-9._/-]+$")


class PilotExactTaskRemotePushCapabilityRequirementsError(ValueError):
    """Exact remote push capability requirements are malformed or unsafe."""


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
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "remote push capability requirements are not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_consumption(
    value: Any,
) -> tuple[PilotExactTaskRemotePublicationWriteConsumptionReceipt, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskRemotePublicationWriteConsumptionReceipt:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "exact ADR-DC-053 write-consumption receipt is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationWriteConsumptionReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "ADR-DC-053 write-consumption receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "ADR-DC-053 write-consumption receipt identity mismatch"
        )
    required_true = (
        "host_consume_guard_committed",
        "human_remote_publication_authorization_verified",
        "remote_publication_authorization_admitted",
        "fresh_remote_head_revalidation_completed",
        "exact_remote_state_unchanged_since_admission",
        "remote_publication_authorization_consumed",
        "one_shot_remote_publication_required",
        "separate_fixed_push_transaction_required",
        "fresh_remote_head_revalidation_at_push_required",
        "network_access_performed",
    )
    forced_false = (
        "credential_material_present",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY
        or value.consumption_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "push requirements require one live consumed but inert ADR-DC-053 receipt"
        )
    live = consumption_boundary._get_live_remote_publication_write_consumption_inputs(value)
    if live is None:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "ADR-DC-053 live consumption provenance is unavailable"
        )
    fresh = live.get("fresh_remote_head_observation")
    if fresh is None or fresh is not value.fresh_remote_head_observation:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "ADR-DC-053 live fresh remote observation identity is unavailable"
        )
    if (
        fresh.observation_authenticated is not True
        or fresh.sha256 != value.fresh_remote_head_observation_sha256
        or fresh.requirements_sha256 != value.requirements_sha256
        or fresh.repository != value.repository
        or fresh.base_sha != value.base_sha
        or fresh.local_commit_sha != value.local_commit_sha
        or fresh.destination_ref != value.destination_ref
        or fresh.canonical_remote_url != value.canonical_remote_url
        or fresh.remote_head_present != value.remote_head_present
        or fresh.remote_head_sha != value.remote_head_sha
        or fresh.publication_mode != value.publication_mode
        or fresh.network_access_performed is not True
        or fresh.credential_material_present is not False
        or fresh.remote_write_authorized is not False
        or fresh.push_authorized is not False
    ):
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "ADR-DC-053 live remote observation no longer matches the consumed authority"
        )
    return value, MappingProxyType(dict(live))


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
        ],
    ] = {}

    def mark(
        requirements: Any,
        consumption: PilotExactTaskRemotePublicationWriteConsumptionReceipt,
    ) -> None:
        key = id(requirements)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            requirements.sha256,
            weakref.ref(requirements, cleanup),
            weakref.ref(consumption),
        )

    def get(requirements: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(requirements))
        if entry is None:
            return None
        pid, digest, requirements_ref, consumption_ref = entry
        consumption = consumption_ref()
        if (
            pid != os.getpid()
            or requirements_ref() is not requirements
            or consumption is None
            or consumption.consumption_authenticated is not True
        ):
            return None
        try:
            if requirements.sha256 != digest:
                return None
        except (AttributeError, TypeError, ValueError):
            return None
        return MappingProxyType({"write_consumption_receipt": consumption})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_push_capability_requirements_authenticated, _get_live_remote_push_capability_requirements_inputs = (
    _live_registry()
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePushCapabilityRequirements:
    write_consumption_receipt: PilotExactTaskRemotePublicationWriteConsumptionReceipt
    write_consumption_receipt_sha256: str
    authorization_admission_receipt_sha256: str
    authorization_proof_sha256: str
    original_remote_head_observation_sha256: str
    fresh_remote_head_observation_sha256: str
    requirements_sha256: str
    requirements_key_sha256: str
    repository: str
    base_sha: str
    local_commit_sha: str
    source_ref: str
    destination_ref: str
    canonical_remote_url: str
    remote_name: str
    remote_provider: str
    push_refspec: str
    expected_remote_head_present: bool
    expected_remote_head_sha: str | None
    publication_mode: str
    remote_publication_nonce_sha256: str
    consumed_at_utc: str
    capability_materialized_at_utc: str
    capability_expires_at_utc: str
    push_timeout_seconds: int = PILOT_EXACT_TASK_REMOTE_PUSH_TIMEOUT_SECONDS
    max_push_output_bytes: int = PILOT_EXACT_TASK_REMOTE_PUSH_MAX_OUTPUT_BYTES
    push_capability_max_age_seconds: int = PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_MAX_AGE_SECONDS
    transport_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY
    credential_custody_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY
    credential_provider_interface: str = PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE
    push_operation: str = PILOT_EXACT_TASK_REMOTE_PUSH_OPERATION
    remote_state_compare_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_STATE_COMPARE_POLICY
    output_policy: str = PILOT_EXACT_TASK_REMOTE_PUSH_OUTPUT_POLICY
    scope: str = PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCOPE
    push_capability_requirements_materialized: bool = True
    remote_publication_authorization_consumed: bool = True
    consumption_authenticated_at_materialization: bool = True
    exact_source_commit_required: bool = True
    exact_destination_ref_required: bool = True
    exact_remote_repository_required: bool = True
    fresh_remote_head_revalidation_at_push_required: bool = True
    host_pinned_credential_provider_required: bool = True
    caller_supplied_credential_forbidden: bool = True
    credential_material_present: bool = False
    inherited_git_credential_helpers_forbidden: bool = True
    interactive_credential_prompt_forbidden: bool = True
    fast_forward_only_required: bool = True
    force_push_forbidden: bool = True
    force_with_lease_forbidden: bool = True
    remote_delete_forbidden: bool = True
    tag_publication_forbidden: bool = True
    pr_mutation_separate_authority_required: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    push_started: bool = False
    push_completed: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        receipt = self.write_consumption_receipt
        if type(receipt) is not PilotExactTaskRemotePublicationWriteConsumptionReceipt:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "nested ADR-DC-053 write-consumption receipt is invalid"
            )
        try:
            replayed = PilotExactTaskRemotePublicationWriteConsumptionReceipt.from_mapping(
                receipt.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "nested ADR-DC-053 receipt replay validation failed"
            ) from exc
        if replayed != receipt or replayed.sha256 != receipt.sha256:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "nested ADR-DC-053 receipt identity mismatch"
            )
        if (
            self.schema != PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCHEMA
            or self.authority != PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_AUTHORITY
            or self.scope != PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCOPE
            or self.transport_policy != PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY
            or self.credential_custody_policy
            != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY
            or self.credential_provider_interface
            != PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE
            or self.push_operation != PILOT_EXACT_TASK_REMOTE_PUSH_OPERATION
            or self.remote_state_compare_policy
            != PILOT_EXACT_TASK_REMOTE_PUSH_STATE_COMPARE_POLICY
            or self.output_policy != PILOT_EXACT_TASK_REMOTE_PUSH_OUTPUT_POLICY
        ):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "remote push capability policy identity mismatch"
            )
        for name in (
            "write_consumption_receipt_sha256",
            "authorization_admission_receipt_sha256",
            "authorization_proof_sha256",
            "original_remote_head_observation_sha256",
            "fresh_remote_head_observation_sha256",
            "requirements_sha256",
            "requirements_key_sha256",
            "remote_publication_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "local_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.expected_remote_head_sha is not None:
            _hex40(self.expected_remote_head_sha, name="expected_remote_head_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.source_ref, str)
            or _BRANCH_REF.fullmatch(self.source_ref) is None
            or not isinstance(self.destination_ref, str)
            or _BRANCH_REF.fullmatch(self.destination_ref) is None
        ):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "repository/source/destination identity is invalid"
            )
        if self.source_ref != self.destination_ref:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "pilot push must preserve the exact reviewed branch ref"
            )
        if self.remote_name != "origin" or self.remote_provider != "github":
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "pilot push requires exact origin/GitHub binding"
            )
        if self.push_refspec != f"{self.local_commit_sha}:{self.destination_ref}":
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "exact push refspec binding mismatch"
            )
        if (
            not isinstance(self.canonical_remote_url, str)
            or not self.canonical_remote_url.startswith("https://github.com/")
            or not self.canonical_remote_url.endswith(".git")
        ):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "canonical remote URL is not the exact GitHub HTTPS form"
            )
        for name in (
            "consumed_at_utc",
            "capability_materialized_at_utc",
            "capability_expires_at_utc",
        ):
            _utc(getattr(self, name), name=name)
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        materialized = _utc(
            self.capability_materialized_at_utc,
            name="capability_materialized_at_utc",
        )
        expires = _utc(self.capability_expires_at_utc, name="capability_expires_at_utc")
        if materialized < consumed:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "push capability requirements predate ADR-DC-053 consumption"
            )
        if materialized > consumed + timedelta(
            seconds=PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_MAX_AGE_SECONDS
        ):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "ADR-DC-053 consumption is too old to materialize push capability requirements"
            )
        if expires != materialized + timedelta(
            seconds=PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_MAX_AGE_SECONDS
        ):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "push capability expiry does not match the fixed lifetime"
            )
        if (
            self.push_timeout_seconds != PILOT_EXACT_TASK_REMOTE_PUSH_TIMEOUT_SECONDS
            or self.max_push_output_bytes != PILOT_EXACT_TASK_REMOTE_PUSH_MAX_OUTPUT_BYTES
            or self.push_capability_max_age_seconds
            != PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_MAX_AGE_SECONDS
        ):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "push execution bounds are unsupported"
            )
        fresh = receipt.fresh_remote_head_observation
        expected = {
            "write_consumption_receipt_sha256": receipt.sha256,
            "authorization_admission_receipt_sha256": receipt.authorization_admission_receipt_sha256,
            "authorization_proof_sha256": receipt.authorization_proof_sha256,
            "original_remote_head_observation_sha256": receipt.original_remote_head_observation_sha256,
            "fresh_remote_head_observation_sha256": receipt.fresh_remote_head_observation_sha256,
            "requirements_sha256": receipt.requirements_sha256,
            "requirements_key_sha256": receipt.requirements_key_sha256,
            "repository": receipt.repository,
            "base_sha": receipt.base_sha,
            "local_commit_sha": receipt.local_commit_sha,
            "source_ref": fresh.source_ref,
            "destination_ref": receipt.destination_ref,
            "canonical_remote_url": receipt.canonical_remote_url,
            "remote_name": fresh.remote_name,
            "remote_provider": fresh.remote_provider,
            "push_refspec": f"{receipt.local_commit_sha}:{receipt.destination_ref}",
            "expected_remote_head_present": receipt.remote_head_present,
            "expected_remote_head_sha": receipt.remote_head_sha,
            "publication_mode": receipt.publication_mode,
            "remote_publication_nonce_sha256": receipt.remote_publication_nonce_sha256,
            "consumed_at_utc": receipt.consumed_at_utc,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                f"remote push capability binding mismatch: {mismatch}"
            )
        if self.expected_remote_head_present:
            if self.expected_remote_head_sha != self.base_sha:
                raise PilotExactTaskRemotePushCapabilityRequirementsError(
                    "fast-forward publication must bind the exact reviewed base SHA"
                )
        elif self.expected_remote_head_sha is not None:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "absent destination branch cannot carry an expected SHA"
            )
        required_true = (
            "push_capability_requirements_materialized",
            "remote_publication_authorization_consumed",
            "consumption_authenticated_at_materialization",
            "exact_source_commit_required",
            "exact_destination_ref_required",
            "exact_remote_repository_required",
            "fresh_remote_head_revalidation_at_push_required",
            "host_pinned_credential_provider_required",
            "caller_supplied_credential_forbidden",
            "inherited_git_credential_helpers_forbidden",
            "interactive_credential_prompt_forbidden",
            "fast_forward_only_required",
            "force_push_forbidden",
            "force_with_lease_forbidden",
            "remote_delete_forbidden",
            "tag_publication_forbidden",
            "pr_mutation_separate_authority_required",
        )
        forced_false = (
            "credential_material_present",
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
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "remote push capability requirements lost required safety evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "remote push capability requirements cannot grant remote authority"
            )

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["write_consumption_receipt"] = self.write_consumption_receipt.to_dict()
        return result

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemotePushCapabilityRequirements":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "remote push capability requirements fields mismatch"
            )
        data = dict(value)
        try:
            data["write_consumption_receipt"] = (
                PilotExactTaskRemotePublicationWriteConsumptionReceipt.from_mapping(
                    data["write_consumption_receipt"]
                )
            )
        except Exception as exc:
            raise PilotExactTaskRemotePushCapabilityRequirementsError(
                "nested ADR-DC-053 receipt is invalid"
            ) from exc
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def requirements_authenticated(self) -> bool:
        return _get_live_remote_push_capability_requirements_inputs(self) is not None


def _materialize_verified_pilot_exact_task_remote_push_capability_requirements(
    *,
    write_consumption_receipt: PilotExactTaskRemotePublicationWriteConsumptionReceipt,
    now_provider=_now_utc_seconds,
) -> PilotExactTaskRemotePushCapabilityRequirements:
    receipt, _live = _require_live_consumption(write_consumption_receipt)
    materialized_at = now_provider()
    if _utc(materialized_at, name="capability_materialized_at_utc") < _utc(
        receipt.consumed_at_utc, name="consumed_at_utc"
    ):
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "system clock moved backwards before push capability materialization"
        )
    fresh = receipt.fresh_remote_head_observation
    requirements = PilotExactTaskRemotePushCapabilityRequirements(
        write_consumption_receipt=receipt,
        write_consumption_receipt_sha256=receipt.sha256,
        authorization_admission_receipt_sha256=receipt.authorization_admission_receipt_sha256,
        authorization_proof_sha256=receipt.authorization_proof_sha256,
        original_remote_head_observation_sha256=receipt.original_remote_head_observation_sha256,
        fresh_remote_head_observation_sha256=receipt.fresh_remote_head_observation_sha256,
        requirements_sha256=receipt.requirements_sha256,
        requirements_key_sha256=receipt.requirements_key_sha256,
        repository=receipt.repository,
        base_sha=receipt.base_sha,
        local_commit_sha=receipt.local_commit_sha,
        source_ref=fresh.source_ref,
        destination_ref=receipt.destination_ref,
        canonical_remote_url=receipt.canonical_remote_url,
        remote_name=fresh.remote_name,
        remote_provider=fresh.remote_provider,
        push_refspec=f"{receipt.local_commit_sha}:{receipt.destination_ref}",
        expected_remote_head_present=receipt.remote_head_present,
        expected_remote_head_sha=receipt.remote_head_sha,
        publication_mode=receipt.publication_mode,
        remote_publication_nonce_sha256=receipt.remote_publication_nonce_sha256,
        consumed_at_utc=receipt.consumed_at_utc,
        capability_materialized_at_utc=materialized_at,
        capability_expires_at_utc=(
            _utc(materialized_at, name="capability_materialized_at_utc")
            + timedelta(seconds=PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_MAX_AGE_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _mark_push_capability_requirements_authenticated(requirements, receipt)
    if requirements.requirements_authenticated is not True:
        raise PilotExactTaskRemotePushCapabilityRequirementsError(
            "live push capability requirements provenance was not established"
        )
    return requirements


def materialize_pilot_exact_task_remote_push_capability_requirements(
    write_consumption_receipt: PilotExactTaskRemotePublicationWriteConsumptionReceipt,
) -> PilotExactTaskRemotePushCapabilityRequirements:
    """Freeze one exact later push capability without granting push authority."""
    return _materialize_verified_pilot_exact_task_remote_push_capability_requirements(
        write_consumption_receipt=write_consumption_receipt,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CAPABILITY_REQUIREMENTS_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUSH_TRANSPORT_POLICY",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_CUSTODY_POLICY",
    "PILOT_EXACT_TASK_REMOTE_PUSH_CREDENTIAL_PROVIDER_INTERFACE",
    "PILOT_EXACT_TASK_REMOTE_PUSH_OPERATION",
    "PILOT_EXACT_TASK_REMOTE_PUSH_STATE_COMPARE_POLICY",
    "PILOT_EXACT_TASK_REMOTE_PUSH_OUTPUT_POLICY",
    "PilotExactTaskRemotePushCapabilityRequirementsError",
    "PilotExactTaskRemotePushCapabilityRequirements",
    "materialize_pilot_exact_task_remote_push_capability_requirements",
]
