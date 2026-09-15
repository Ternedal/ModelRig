"""ADR-DC-052 host-pinned credential-broker capability for one remote write.

Private implementation/test seam. The public production facade supplies the
host-admin-controlled broker descriptor. No credential secret is loaded here and
no network or Git mutation is performed.
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

from . import improvement_pilot_exact_task_remote_publication_write_reservation as reservation_boundary
from .improvement_pilot_exact_task_remote_publication_write_reservation import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_AUTHORITY,
    PilotExactTaskRemotePublicationWriteReservationReceipt,
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-credential-capability/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_AUTHORITY = (
    "host-attested-one-dc-l16-exact-remote-credential-broker-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_PROTOCOL = "git-askpass-v1"
PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_SOURCE = (
    "host-secret-store-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_TRANSPORT = (
    "askpass-stdout-direct-to-git-only"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REF = re.compile(r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PilotExactTaskRemotePublicationCredentialCapabilityError(ValueError):
    """The host-pinned remote credential capability is unsafe or unavailable."""


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
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential capability is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            f"{name} is invalid"
        )
    if not allow_zero and value == "0" * 40:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            f"{name} must not be zero"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_reservation(
    value: Any,
) -> tuple[PilotExactTaskRemotePublicationWriteReservationReceipt, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskRemotePublicationWriteReservationReceipt:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "exact ADR-DC-051 remote-write reservation receipt is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationWriteReservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "ADR-DC-051 receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "ADR-DC-051 receipt identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_AUTHORITY
        or value.reservation_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.fresh_remote_state_revalidated is not True
        or value.remote_destination_ref_absent is not True
        or value.create_only_remote_ref_required is not True
        or value.remote_publication_authorization_consumed is not True
        or value.remote_write_slot_reserved is not True
        or value.remote_write_transaction_required is not True
        or value.fresh_remote_state_revalidation_before_write_required is not True
        or value.remote_branch_compare_and_swap_required is not True
        or value.no_force_push_required is not True
        or value.separate_pr_mutation_authorization_required is not True
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.expected_old_remote_sha != "0" * 40
        or value.canonical_remote_url != "https://github.com/Ternedal/ModelRig.git"
        or _REF.fullmatch(value.destination_ref) is None
        or not value.destination_ref.endswith(value.remote_publication_nonce_sha256)
    ):
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential capability requires one live inert ADR-DC-051 reservation"
        )
    inputs = reservation_boundary._get_live_remote_publication_write_reservation_inputs(
        value
    )
    if inputs is None:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "ADR-DC-051 durable live provenance is unavailable"
        )
    observation = inputs.get("remote_publication_state_observation")
    if (
        observation is None
        or getattr(observation, "sha256", None) != value.fresh_state_observation_sha256
        or getattr(observation, "observation_authenticated", None) is not True
        or getattr(observation, "remote_publication_nonce_sha256", None)
        != value.remote_publication_nonce_sha256
        or getattr(observation, "predicted_commit_sha", None) != value.predicted_commit_sha
        or getattr(observation, "destination_ref", None) != value.destination_ref
    ):
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "ADR-DC-051 reservation lost exact live remote-state provenance"
        )
    return value, inputs


def _descriptor(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "host credential-broker descriptor is required"
        )
    expected = {
        "broker_policy_sha256",
        "broker_executable_path",
        "broker_executable_path_sha256",
        "broker_executable_sha256",
        "broker_version",
        "credential_protocol",
        "secret_source",
        "secret_transport",
    }
    if set(value) != expected:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential-broker descriptor fields mismatch"
        )
    result = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in result.values()):
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential-broker descriptor contains invalid text"
        )
    _hex64(result["broker_policy_sha256"], name="broker_policy_sha256")
    _hex64(
        result["broker_executable_path_sha256"],
        name="broker_executable_path_sha256",
    )
    _hex64(
        result["broker_executable_sha256"],
        name="broker_executable_sha256",
    )
    path = Path(result["broker_executable_path"])
    if not path.is_absolute():
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential-broker executable path must be absolute"
        )
    if _VERSION.fullmatch(result["broker_version"]) is None:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential-broker version is invalid"
        )
    if (
        result["credential_protocol"]
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_PROTOCOL
        or result["secret_source"]
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_SOURCE
        or result["secret_transport"]
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_TRANSPORT
    ):
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential-broker semantics are unsupported"
        )
    return MappingProxyType(result)


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[PilotExactTaskRemotePublicationWriteReservationReceipt],
            Mapping[str, str],
        ],
    ] = {}

    def mark(
        capability: Any,
        reservation: PilotExactTaskRemotePublicationWriteReservationReceipt,
        descriptor: Mapping[str, str],
    ) -> None:
        key = id(capability)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            capability.sha256,
            weakref.ref(capability, cleanup),
            weakref.ref(reservation),
            descriptor,
        )

    def get(capability: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(capability))
        if entry is None:
            return None
        pid, digest, capability_ref, reservation_ref, descriptor = entry
        reservation = reservation_ref()
        if (
            pid != os.getpid()
            or capability_ref() is not capability
            or reservation is None
            or reservation.reservation_authenticated is not True
            or reservation.sha256 != capability.remote_write_reservation_sha256
            or capability.sha256 != digest
            or descriptor.get("broker_policy_sha256")
            != capability.broker_policy_sha256
            or descriptor.get("broker_executable_path_sha256")
            != capability.broker_executable_path_sha256
            or descriptor.get("broker_executable_sha256")
            != capability.broker_executable_sha256
        ):
            return None
        return MappingProxyType(
            {
                "remote_publication_write_reservation": reservation,
                "credential_broker_descriptor": descriptor,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_credential_capability_authenticated,
    _get_live_remote_publication_credential_capability_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationCredentialCapability:
    remote_write_reservation_sha256: str
    fresh_state_observation_sha256: str
    target_attestation_sha256: str
    authorization_proof_sha256: str
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    predicted_commit_sha: str
    canonical_remote_url: str
    destination_ref: str
    expected_old_remote_sha: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    secret_source: str
    secret_transport: str
    materialized_at_utc: str
    host_replay_guard_committed: bool = True
    remote_publication_authorization_consumed: bool = True
    remote_write_slot_reserved: bool = True
    credential_broker_host_pinned: bool = True
    credential_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    one_shot_remote_write_required: bool = True
    fresh_remote_state_revalidation_before_write_required: bool = True
    create_only_remote_ref_required: bool = True
    remote_branch_compare_and_swap_required: bool = True
    no_force_push_required: bool = True
    separate_pr_mutation_authorization_required: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_SCHEMA:
            raise PilotExactTaskRemotePublicationCredentialCapabilityError(
                "credential capability schema is unsupported"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_AUTHORITY:
            raise PilotExactTaskRemotePublicationCredentialCapabilityError(
                "credential capability authority is unsupported"
            )
        for name in (
            "remote_write_reservation_sha256",
            "fresh_state_observation_sha256",
            "target_attestation_sha256",
            "authorization_proof_sha256",
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "remote_publication_nonce_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(self.expected_old_remote_sha, name="expected_old_remote_sha", allow_zero=True)
        if (
            self.expected_old_remote_sha != "0" * 40
            or self.canonical_remote_url != "https://github.com/Ternedal/ModelRig.git"
            or _REF.fullmatch(self.destination_ref) is None
            or not self.destination_ref.endswith(self.remote_publication_nonce_sha256)
            or _VERSION.fullmatch(self.broker_version) is None
            or self.credential_protocol
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_PROTOCOL
            or self.secret_source
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_SOURCE
            or self.secret_transport
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_TRANSPORT
        ):
            raise PilotExactTaskRemotePublicationCredentialCapabilityError(
                "credential capability target/broker binding is invalid"
            )
        _utc(self.materialized_at_utc, name="materialized_at_utc")
        required_true = (
            "host_replay_guard_committed",
            "remote_publication_authorization_consumed",
            "remote_write_slot_reserved",
            "credential_broker_host_pinned",
            "credential_broker_binary_verified",
            "credential_secret_not_loaded",
            "one_shot_remote_write_required",
            "fresh_remote_state_revalidation_before_write_required",
            "create_only_remote_ref_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        )
        forced_false = (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationCredentialCapabilityError(
                "credential capability evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationCredentialCapabilityError(
                "credential capability cannot grant remote mutation authority"
            )

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_remote_publication_credential_capability_inputs(self) is not None

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
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationCredentialCapability":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationCredentialCapabilityError(
                "credential capability must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationCredentialCapabilityError(
                "credential capability fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_remote_publication_credential_capability(
    *,
    remote_write_reservation: PilotExactTaskRemotePublicationWriteReservationReceipt,
    broker_descriptor: Mapping[str, str],
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationCredentialCapability:
    reservation, _inputs = _require_live_reservation(remote_write_reservation)
    descriptor = _descriptor(broker_descriptor)
    result = PilotExactTaskRemotePublicationCredentialCapability(
        remote_write_reservation_sha256=reservation.sha256,
        fresh_state_observation_sha256=reservation.fresh_state_observation_sha256,
        target_attestation_sha256=reservation.target_attestation_sha256,
        authorization_proof_sha256=reservation.authorization_proof_sha256,
        local_commit_publication_requirements_sha256=(
            reservation.local_commit_publication_requirements_sha256
        ),
        local_commit_write_transaction_sha256=(
            reservation.local_commit_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=reservation.remote_publication_nonce_sha256,
        predicted_commit_sha=reservation.predicted_commit_sha,
        canonical_remote_url=reservation.canonical_remote_url,
        destination_ref=reservation.destination_ref,
        expected_old_remote_sha=reservation.expected_old_remote_sha,
        broker_policy_sha256=descriptor["broker_policy_sha256"],
        broker_executable_path_sha256=descriptor["broker_executable_path_sha256"],
        broker_executable_sha256=descriptor["broker_executable_sha256"],
        broker_version=descriptor["broker_version"],
        credential_protocol=descriptor["credential_protocol"],
        secret_source=descriptor["secret_source"],
        secret_transport=descriptor["secret_transport"],
        materialized_at_utc=now_provider(),
    )
    _mark_remote_publication_credential_capability_authenticated(
        result,
        reservation,
        descriptor,
    )
    if result.capability_authenticated is not True:
        raise PilotExactTaskRemotePublicationCredentialCapabilityError(
            "credential capability lost live host provenance"
        )
    return result


def materialize_pilot_exact_task_remote_publication_credential_capability(
    remote_write_reservation: PilotExactTaskRemotePublicationWriteReservationReceipt,
) -> PilotExactTaskRemotePublicationCredentialCapability:
    raise PilotExactTaskRemotePublicationCredentialCapabilityError(
        "production remote credential capability boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_CAPABILITY_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_PROTOCOL",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_SOURCE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_SECRET_TRANSPORT",
    "PilotExactTaskRemotePublicationCredentialCapabilityError",
    "PilotExactTaskRemotePublicationCredentialCapability",
    "materialize_pilot_exact_task_remote_publication_credential_capability",
]
