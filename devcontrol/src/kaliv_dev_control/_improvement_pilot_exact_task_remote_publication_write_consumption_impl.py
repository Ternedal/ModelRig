"""ADR-DC-053 fresh pre-push revalidation and remote-publication write consumption.

This boundary accepts only the exact live ADR-DC-052 admission receipt. It
performs a fresh double read-only remote-head observation through ADR-DC-050,
requires the exact human-approved remote state to remain unchanged, and only
then durably consumes the one-shot remote-publication nonce in a separate
host-local ledger.

It does not push, load credentials, mutate a PR, merge, release, deploy, or
activate production. A later fixed push transaction must require this exact
live receipt and must revalidate the remote head again immediately at push.
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

from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_remote_head_observation as observation_boundary
from .improvement_pilot_exact_task_remote_head_observation import (
    PilotExactTaskRemoteHeadObservation,
)
from . import improvement_pilot_exact_task_remote_publication_authorization_admission as admission_boundary
from .improvement_pilot_exact_task_remote_publication_authorization_admission import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_AUTHORITY,
    PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-write-consumption-receipt/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY = (
    "host-consumed-one-dc-l16-exact-remote-publication-authorization-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)
_MAX_ARTIFACT_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskRemotePublicationWriteConsumptionError(ValueError):
    """The exact remote-publication authorization cannot be consumed safely."""


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
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "remote-publication write consumption is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _read_bound_file(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        return None
    return payload


def _require_live_admission(
    value: Any,
) -> tuple[
    PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
    PilotExactTaskRemoteHeadObservation,
    Any,
]:
    if type(value) is not PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "exact ADR-DC-052 remote-publication admission receipt is required"
        )
    try:
        replayed = (
            PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt.from_mapping(
                value.to_dict()
            )
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "ADR-DC-052 admission receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "ADR-DC-052 admission receipt identity mismatch"
        )
    required_true = (
        "host_replay_guard_committed",
        "human_remote_publication_authorization_verified",
        "remote_publication_authorization_admitted",
        "one_shot_remote_publication_required",
        "exact_live_remote_observation_bound",
        "fresh_authorization_reverified",
        "fresh_remote_head_revalidation_before_push_required",
    )
    forced_false = (
        "remote_publication_authorization_consumed",
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
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_AUTHORITY
        or value.admission_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "write consumption requires one live inert ADR-DC-052 admission"
        )
    live = (
        admission_boundary._get_live_remote_publication_authorization_admission_inputs(
            value
        )
    )
    if live is None:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "ADR-DC-052 live admission provenance is unavailable"
        )
    original = live.get("remote_head_observation")
    if type(original) is not PilotExactTaskRemoteHeadObservation:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "ADR-DC-052 live remote-head observation is unavailable"
        )
    if (
        original.observation_authenticated is not True
        or original.sha256 != value.remote_head_observation_sha256
        or original.observation_key_sha256 != value.observation_key_sha256
        or original.requirements_sha256 != value.requirements_sha256
        or original.repository != value.repository
        or original.base_sha != value.base_sha
        or original.local_commit_sha != value.local_commit_sha
        or original.destination_ref != value.destination_ref
        or original.canonical_remote_url != value.canonical_remote_url
        or original.remote_head_present != value.remote_head_present
        or original.remote_head_sha != value.remote_head_sha
        or original.publication_mode != value.publication_mode
    ):
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "ADR-DC-052 admission no longer binds its exact live ADR-DC-050 observation"
        )
    requirements = original.requirements
    if (
        requirements.requirements_authenticated is not True
        or requirements.sha256 != value.requirements_sha256
        or requirements.requirements_key_sha256 != value.requirements_key_sha256
    ):
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "live ADR-DC-049 publication requirements are unavailable"
        )
    return value, original, requirements


def _require_fresh_remote_state_matches_admission(
    admission: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
    original: PilotExactTaskRemoteHeadObservation,
    fresh: PilotExactTaskRemoteHeadObservation,
) -> None:
    try:
        replayed = PilotExactTaskRemoteHeadObservation.from_mapping(fresh.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "fresh ADR-DC-050 observation replay validation failed"
        ) from exc
    if replayed != fresh or replayed.sha256 != fresh.sha256:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "fresh ADR-DC-050 observation replay identity mismatch"
        )
    expected = (
        ("requirements_sha256", admission.requirements_sha256),
        ("requirements_key_sha256", admission.requirements_key_sha256),
        ("repository", admission.repository),
        ("base_sha", admission.base_sha),
        ("local_commit_sha", admission.local_commit_sha),
        ("destination_ref", admission.destination_ref),
        ("canonical_remote_url", admission.canonical_remote_url),
        ("remote_head_present", admission.remote_head_present),
        ("remote_head_sha", admission.remote_head_sha),
        ("publication_mode", admission.publication_mode),
    )
    mismatch = next(
        (name for name, item in expected if getattr(fresh, name) != item),
        None,
    )
    if mismatch is not None:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            f"remote state changed since human authorization/admission: {mismatch}"
        )
    if (
        original.remote_head_present != fresh.remote_head_present
        or original.remote_head_sha != fresh.remote_head_sha
        or original.publication_mode != fresh.publication_mode
        or original.local_state_after_sha256 != fresh.local_state_before_sha256
        or fresh.local_state_before_sha256 != fresh.local_state_after_sha256
        or fresh.network_access_performed is not True
        or fresh.credential_material_present is not False
        or fresh.remote_head_stable_across_double_observation is not True
        or fresh.local_commit_state_matched is not True
        or fresh.fast_forward_candidate is not True
        or fresh.remote_write_authorized is not False
        or fresh.push_authorized is not False
        or fresh.pr_mutation_authorized is not False
        or fresh.production_activation_authorized is not False
    ):
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "fresh pre-push remote revalidation is not the exact admitted state"
        )


def _consumption_key(
    admission: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
) -> str:
    return _hex64(
        admission.remote_publication_nonce_sha256,
        name="remote_publication_nonce_sha256",
    )


def _transaction_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            Path,
            bytes,
            Path,
            bytes,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
        ],
    ] = {}

    def mark(
        receipt: Any,
        admission: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
        fresh_observation: PilotExactTaskRemoteHeadObservation,
        *,
        lock_path: Path,
        lock_payload: bytes,
        receipt_path: Path,
        receipt_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            lock_path,
            lock_payload,
            receipt_path,
            receipt_payload,
            weakref.ref(receipt, cleanup),
            weakref.ref(admission),
            weakref.ref(fresh_observation),
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            lock_path,
            lock_payload,
            receipt_path,
            receipt_payload,
            receipt_ref,
            admission_ref,
            observation_ref,
        ) = entry
        admission = admission_ref()
        fresh_observation = observation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or admission is None
            or fresh_observation is None
            or admission.admission_authenticated is not True
            or fresh_observation.observation_authenticated is not True
        ):
            return None
        try:
            if receipt.sha256 != digest:
                return None
        except (AttributeError, TypeError, ValueError):
            return None
        if (
            _read_bound_file(lock_path) != lock_payload
            or _read_bound_file(receipt_path) != receipt_payload
        ):
            return None
        return MappingProxyType(
            {
                "authorization_admission_receipt": admission,
                "fresh_remote_head_observation": fresh_observation,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_consumption_authenticated, _get_live_remote_publication_write_consumption_inputs = (
    _transaction_registry()
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationWriteConsumptionReceipt:
    ledger_root_path_sha256: str
    consumption_key_sha256: str
    authorization_admission_receipt: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt
    authorization_admission_receipt_sha256: str
    authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    original_remote_head_observation_sha256: str
    original_observation_key_sha256: str
    fresh_remote_head_observation: PilotExactTaskRemoteHeadObservation
    fresh_remote_head_observation_sha256: str
    fresh_observation_key_sha256: str
    requirements_sha256: str
    requirements_key_sha256: str
    repository: str
    base_sha: str
    local_commit_sha: str
    destination_ref: str
    canonical_remote_url: str
    remote_head_present: bool
    remote_head_sha: str | None
    publication_mode: str
    remote_publication_nonce_sha256: str
    admitted_at_utc: str
    fresh_observation_started_at_utc: str
    fresh_observation_completed_at_utc: str
    consumed_at_utc: str
    ledger_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE
    host_consume_guard_committed: bool = True
    human_remote_publication_authorization_verified: bool = True
    remote_publication_authorization_admitted: bool = True
    fresh_remote_head_revalidation_completed: bool = True
    exact_remote_state_unchanged_since_admission: bool = True
    remote_publication_authorization_consumed: bool = True
    one_shot_remote_publication_required: bool = True
    separate_fixed_push_transaction_required: bool = True
    fresh_remote_head_revalidation_at_push_required: bool = True
    network_access_performed: bool = True
    credential_material_present: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        admission = self.authorization_admission_receipt
        if type(admission) is not PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "nested ADR-DC-052 admission receipt is invalid"
            )
        try:
            replayed_admission = (
                PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt.from_mapping(
                    admission.to_dict()
                )
            )
        except Exception as exc:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "nested ADR-DC-052 admission receipt replay failed"
            ) from exc
        if replayed_admission != admission or replayed_admission.sha256 != admission.sha256:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "nested ADR-DC-052 admission receipt identity mismatch"
            )
        fresh = self.fresh_remote_head_observation
        try:
            replayed_fresh = PilotExactTaskRemoteHeadObservation.from_mapping(
                fresh.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "nested fresh ADR-DC-050 observation replay failed"
            ) from exc
        if replayed_fresh != fresh or replayed_fresh.sha256 != fresh.sha256:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "nested fresh ADR-DC-050 observation identity mismatch"
            )
        if (
            self.schema
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_RECEIPT_SCHEMA
            or self.ledger_scope
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE
            or self.authority
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY
        ):
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption receipt schema/scope/authority unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "consumption_key_sha256",
            "authorization_admission_receipt_sha256",
            "authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "original_remote_head_observation_sha256",
            "original_observation_key_sha256",
            "fresh_remote_head_observation_sha256",
            "fresh_observation_key_sha256",
            "requirements_sha256",
            "requirements_key_sha256",
            "remote_publication_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "local_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.remote_head_sha is not None:
            _hex40(self.remote_head_sha, name="remote_head_sha")
        for name in (
            "admitted_at_utc",
            "fresh_observation_started_at_utc",
            "fresh_observation_completed_at_utc",
            "consumed_at_utc",
        ):
            _utc(getattr(self, name), name=name)
        expected = {
            "consumption_key_sha256": admission.remote_publication_nonce_sha256,
            "authorization_admission_receipt_sha256": admission.sha256,
            "authorization_proof_sha256": admission.authorization_proof_sha256,
            "authorization_sha256": admission.authorization_sha256,
            "authorization_signature_sha256": admission.authorization_signature_sha256,
            "original_remote_head_observation_sha256": admission.remote_head_observation_sha256,
            "original_observation_key_sha256": admission.observation_key_sha256,
            "fresh_remote_head_observation_sha256": fresh.sha256,
            "fresh_observation_key_sha256": fresh.observation_key_sha256,
            "requirements_sha256": admission.requirements_sha256,
            "requirements_key_sha256": admission.requirements_key_sha256,
            "repository": admission.repository,
            "base_sha": admission.base_sha,
            "local_commit_sha": admission.local_commit_sha,
            "destination_ref": admission.destination_ref,
            "canonical_remote_url": admission.canonical_remote_url,
            "remote_head_present": admission.remote_head_present,
            "remote_head_sha": admission.remote_head_sha,
            "publication_mode": admission.publication_mode,
            "remote_publication_nonce_sha256": admission.remote_publication_nonce_sha256,
            "admitted_at_utc": admission.admitted_at_utc,
            "fresh_observation_started_at_utc": fresh.observation_started_at_utc,
            "fresh_observation_completed_at_utc": fresh.observation_completed_at_utc,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                f"remote-publication consumption receipt binding mismatch: {mismatch}"
            )
        _require_fresh_remote_state_matches_admission(
            admission,
            admission.authorization_proof.authorization.remote_head_observation,
            fresh,
        )
        admitted = _utc(self.admitted_at_utc, name="admitted_at_utc")
        started = _utc(
            self.fresh_observation_started_at_utc,
            name="fresh_observation_started_at_utc",
        )
        completed = _utc(
            self.fresh_observation_completed_at_utc,
            name="fresh_observation_completed_at_utc",
        )
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        if not admitted <= started <= completed <= consumed:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption timestamps are not monotonic"
            )
        if consumed >= _utc(
            admission.authorization_proof.authorization.expires_at_utc,
            name="authorization expires_at_utc",
        ):
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication authorization expired before consumption completed"
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption receipt lost required evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption cannot grant remote mutation authority"
            )

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }
        result["authorization_admission_receipt"] = (
            self.authorization_admission_receipt.to_dict()
        )
        result["fresh_remote_head_observation"] = (
            self.fresh_remote_head_observation.to_dict()
        )
        return result

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskRemotePublicationWriteConsumptionReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption receipt fields mismatch"
            )
        mapped = dict(value)
        try:
            mapped["authorization_admission_receipt"] = (
                PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt.from_mapping(
                    mapped["authorization_admission_receipt"]
                )
            )
            mapped["fresh_remote_head_observation"] = (
                PilotExactTaskRemoteHeadObservation.from_mapping(
                    mapped["fresh_remote_head_observation"]
                )
            )
        except Exception as exc:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption nested evidence is invalid"
            ) from exc
        return cls(**mapped)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def consumption_authenticated(self) -> bool:
        return (
            _get_live_remote_publication_write_consumption_inputs(self)
            is not None
        )


class _PilotExactTaskRemotePublicationWriteConsumptionLedger:
    """Create-once host-local consume ledger keyed by publication nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _lock_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='consumption key')}.lock.json"

    def _receipt_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='consumption key')}.receipt.json"

    def consume(
        self,
        *,
        key: str,
        admission: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
        fresh_observation: PilotExactTaskRemoteHeadObservation,
    ) -> tuple[Path, bytes]:
        lock = self._lock_path(key)
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-remote-publication-write-consumption-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "consumption_key_sha256": key,
                "authorization_admission_receipt_sha256": admission.sha256,
                "authorization_proof_sha256": admission.authorization_proof_sha256,
                "authorization_sha256": admission.authorization_sha256,
                "authorization_signature_sha256": admission.authorization_signature_sha256,
                "original_remote_head_observation_sha256": admission.remote_head_observation_sha256,
                "fresh_remote_head_observation_sha256": fresh_observation.sha256,
                "fresh_observation_key_sha256": fresh_observation.observation_key_sha256,
                "requirements_sha256": admission.requirements_sha256,
                "local_commit_sha": admission.local_commit_sha,
                "destination_ref": admission.destination_ref,
                "remote_head_present": admission.remote_head_present,
                "remote_head_sha": admission.remote_head_sha,
                "publication_mode": admission.publication_mode,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication authorization was already consumed or could not be durably consumed"
            ) from exc
        if _read_bound_file(lock) != payload:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption lock read-back mismatch"
            )
        return lock, payload

    def publish(
        self,
        *,
        key: str,
        receipt: PilotExactTaskRemotePublicationWriteConsumptionReceipt,
    ) -> tuple[Path, bytes]:
        path = self._receipt_path(key)
        payload = receipt.canonical_json().encode("utf-8")
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption receipt already exists or could not be persisted"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "remote-publication consumption receipt read-back mismatch"
            )
        try:
            parsed = PilotExactTaskRemotePublicationWriteConsumptionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
        except Exception as exc:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "persisted remote-publication consumption receipt is invalid"
            ) from exc
        if parsed != receipt or parsed.sha256 != receipt.sha256:
            raise PilotExactTaskRemotePublicationWriteConsumptionError(
                "persisted remote-publication consumption receipt identity mismatch"
            )
        return path, payload


def _consume_verified_pilot_exact_task_remote_publication_authorization(
    *,
    authorization_admission_receipt: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
    ledger: _PilotExactTaskRemotePublicationWriteConsumptionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationWriteConsumptionReceipt:
    admission, original, requirements = _require_live_admission(
        authorization_admission_receipt
    )
    if not isinstance(ledger, _PilotExactTaskRemotePublicationWriteConsumptionLedger):
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "host-local remote-publication consumption ledger is required"
        )
    try:
        fresh = observation_boundary._observe_verified_pilot_exact_task_remote_head(
            requirements=requirements,
            now_provider=now_provider,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "fresh pre-push remote-head revalidation failed"
        ) from exc
    if fresh.observation_authenticated is not True:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "fresh pre-push remote-head observation lost live provenance"
        )
    _require_fresh_remote_state_matches_admission(admission, original, fresh)
    admitted = _utc(admission.admitted_at_utc, name="admitted_at_utc")
    started = _utc(
        fresh.observation_started_at_utc,
        name="fresh_observation_started_at_utc",
    )
    completed = _utc(
        fresh.observation_completed_at_utc,
        name="fresh_observation_completed_at_utc",
    )
    expires = _utc(
        admission.authorization_proof.authorization.expires_at_utc,
        name="authorization expires_at_utc",
    )
    if started < admitted or completed < started:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "fresh remote revalidation predates admission or moved backwards"
        )
    if completed >= expires:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "human remote-publication authorization expired before durable consumption"
        )
    key = _consumption_key(admission)
    lock_path, lock_payload = ledger.consume(
        key=key,
        admission=admission,
        fresh_observation=fresh,
    )
    consumed_at = now_provider()
    if _utc(consumed_at, name="consumed_at_utc") < completed:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "remote-publication consumption clock moved backwards after durable marker"
        )
    if _utc(consumed_at, name="consumed_at_utc") >= expires:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "human remote-publication authorization expired after durable consumption; nonce remains burned"
        )
    receipt = PilotExactTaskRemotePublicationWriteConsumptionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        consumption_key_sha256=key,
        authorization_admission_receipt=admission,
        authorization_admission_receipt_sha256=admission.sha256,
        authorization_proof_sha256=admission.authorization_proof_sha256,
        authorization_sha256=admission.authorization_sha256,
        authorization_signature_sha256=admission.authorization_signature_sha256,
        original_remote_head_observation_sha256=admission.remote_head_observation_sha256,
        original_observation_key_sha256=admission.observation_key_sha256,
        fresh_remote_head_observation=fresh,
        fresh_remote_head_observation_sha256=fresh.sha256,
        fresh_observation_key_sha256=fresh.observation_key_sha256,
        requirements_sha256=admission.requirements_sha256,
        requirements_key_sha256=admission.requirements_key_sha256,
        repository=admission.repository,
        base_sha=admission.base_sha,
        local_commit_sha=admission.local_commit_sha,
        destination_ref=admission.destination_ref,
        canonical_remote_url=admission.canonical_remote_url,
        remote_head_present=admission.remote_head_present,
        remote_head_sha=admission.remote_head_sha,
        publication_mode=admission.publication_mode,
        remote_publication_nonce_sha256=admission.remote_publication_nonce_sha256,
        admitted_at_utc=admission.admitted_at_utc,
        fresh_observation_started_at_utc=fresh.observation_started_at_utc,
        fresh_observation_completed_at_utc=fresh.observation_completed_at_utc,
        consumed_at_utc=consumed_at,
    )
    receipt_path, receipt_payload = ledger.publish(key=key, receipt=receipt)
    _mark_consumption_authenticated(
        receipt,
        admission,
        fresh,
        lock_path=lock_path,
        lock_payload=lock_payload,
        receipt_path=receipt_path,
        receipt_payload=receipt_payload,
    )
    if receipt.consumption_authenticated is not True:
        raise PilotExactTaskRemotePublicationWriteConsumptionError(
            "live remote-publication consumption provenance was not established"
        )
    return receipt


def consume_pilot_exact_task_remote_publication_authorization(
    authorization_admission_receipt: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
) -> PilotExactTaskRemotePublicationWriteConsumptionReceipt:
    raise PilotExactTaskRemotePublicationWriteConsumptionError(
        "production remote-publication write-consumption boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_CONSUMPTION_LEDGER_SCOPE",
    "PilotExactTaskRemotePublicationWriteConsumptionError",
    "PilotExactTaskRemotePublicationWriteConsumptionReceipt",
    "consume_pilot_exact_task_remote_publication_authorization",
]
