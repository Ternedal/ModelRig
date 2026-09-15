"""ADR-DC-052 replay-safe admission for one exact human-authorized remote publication.

This boundary may durably reserve the fresh ADR-DC-051 remote-publication nonce
exactly once on the canonical host. It re-verifies the human authorization and
requires the exact live ADR-DC-050 observation, but performs no network access,
does not consume the authorization for push, and grants no remote-write authority.
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
    PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY,
    PilotExactTaskRemoteHeadObservation,
)
from .improvement_pilot_exact_task_remote_publication_authorization import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskRemotePublicationAuthorizationProof,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-authorization-admission-receipt/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_AUTHORITY = (
    "host-admitted-one-dc-l16-exact-remote-publication-authorization-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)
_MAX_ARTIFACT_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskRemotePublicationAuthorizationAdmissionError(ValueError):
    """The exact remote-publication authorization cannot be admitted safely."""


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
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "remote-publication authorization admission is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
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


def _require_verified_proof(
    value: Any,
) -> PilotExactTaskRemotePublicationAuthorizationProof:
    if type(value) is not PilotExactTaskRemotePublicationAuthorizationProof:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "exact ADR-DC-051 human remote-publication authorization proof is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "ADR-DC-051 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "ADR-DC-051 proof replay identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_remote_publication_authorization_verified is not True
        or value.one_shot_remote_publication_required is not True
        or value.fresh_remote_head_revalidation_before_push_required is not True
        or value.remote_publication_authorization_consumed is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "admission requires one verified inert ADR-DC-051 proof"
        )
    return value


def _stable_proof_mapping(
    proof: PilotExactTaskRemotePublicationAuthorizationProof,
) -> dict[str, Any]:
    exact = _require_verified_proof(proof)
    data = exact.to_dict()
    data.pop("verified_at_utc", None)
    return data


def require_fresh_remote_publication_authorization_proof_identity(
    supplied: PilotExactTaskRemotePublicationAuthorizationProof,
    fresh: PilotExactTaskRemotePublicationAuthorizationProof,
) -> None:
    if _stable_proof_mapping(supplied) != _stable_proof_mapping(fresh):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "fresh ADR-DC-051 proof identity does not match supplied proof"
        )


def _require_live_observation_for_proof(
    proof: PilotExactTaskRemotePublicationAuthorizationProof,
    remote_head_observation: Any,
) -> tuple[PilotExactTaskRemoteHeadObservation, Mapping[str, Any]]:
    exact_proof = _require_verified_proof(proof)
    if type(remote_head_observation) is not PilotExactTaskRemoteHeadObservation:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "exact live ADR-DC-050 remote-head observation is required"
        )
    try:
        replayed = PilotExactTaskRemoteHeadObservation.from_mapping(
            remote_head_observation.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "ADR-DC-050 observation replay validation failed"
        ) from exc
    if replayed != remote_head_observation or replayed.sha256 != remote_head_observation.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "ADR-DC-050 observation replay identity mismatch"
        )
    live = observation_boundary._get_live_remote_head_observation_inputs(
        remote_head_observation
    )
    if live is None or remote_head_observation.observation_authenticated is not True:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "ADR-DC-050 live observation provenance is unavailable"
        )
    claim_observation = exact_proof.authorization.remote_head_observation
    if (
        remote_head_observation.authority
        != PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY
        or remote_head_observation.sha256 != exact_proof.remote_head_observation_sha256
        or remote_head_observation.sha256 != claim_observation.sha256
        or remote_head_observation.observation_key_sha256
        != exact_proof.observation_key_sha256
        or remote_head_observation.local_commit_sha != exact_proof.local_commit_sha
        or remote_head_observation.destination_ref != exact_proof.destination_ref
        or remote_head_observation.network_access_performed is not True
        or remote_head_observation.credential_material_present is not False
        or remote_head_observation.remote_head_observed is not True
        or remote_head_observation.remote_head_stable_across_double_observation is not True
        or remote_head_observation.local_commit_state_matched is not True
        or remote_head_observation.fast_forward_candidate is not True
        or remote_head_observation.remote_write_authorized is not False
        or remote_head_observation.push_authorized is not False
        or remote_head_observation.pr_mutation_authorized is not False
        or remote_head_observation.production_activation_authorized is not False
    ):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "ADR-DC-051 proof is not bound to the exact live ADR-DC-050 observation"
        )
    requirements = live.get("requirements")
    if requirements is None or requirements.sha256 != remote_head_observation.requirements_sha256:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "ADR-DC-050 live requirements binding is unavailable"
        )
    return remote_head_observation, MappingProxyType(dict(live))


def _admission_key(
    proof: PilotExactTaskRemotePublicationAuthorizationProof,
) -> str:
    exact = _require_verified_proof(proof)
    return _hex64(
        exact.remote_publication_nonce_sha256,
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
        ],
    ] = {}

    def mark(
        receipt: Any,
        observation: PilotExactTaskRemoteHeadObservation,
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
            weakref.ref(observation),
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
            observation_ref,
        ) = entry
        observation = observation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or observation is None
            or observation.observation_authenticated is not True
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
        return MappingProxyType({"remote_head_observation": observation})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_admission_authenticated, _get_live_remote_publication_authorization_admission_inputs = (
    _transaction_registry()
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt:
    ledger_root_path_sha256: str
    admission_key_sha256: str
    authorization_proof: PilotExactTaskRemotePublicationAuthorizationProof
    authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    remote_head_observation_sha256: str
    observation_key_sha256: str
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
    observation_completed_at_utc: str
    fresh_verified_at_utc: str
    admitted_at_utc: str
    ledger_scope: str = (
        PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_LEDGER_SCOPE
    )
    host_replay_guard_committed: bool = True
    human_remote_publication_authorization_verified: bool = True
    remote_publication_authorization_admitted: bool = True
    remote_publication_authorization_consumed: bool = False
    one_shot_remote_publication_required: bool = True
    exact_live_remote_observation_bound: bool = True
    fresh_authorization_reverified: bool = True
    fresh_remote_head_revalidation_before_push_required: bool = True
    credential_material_present: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        proof = _require_verified_proof(self.authorization_proof)
        if (
            self.schema
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA
            or self.ledger_scope
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_LEDGER_SCOPE
            or self.authority
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_AUTHORITY
        ):
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission receipt schema/scope/authority is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "admission_key_sha256",
            "authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "remote_head_observation_sha256",
            "observation_key_sha256",
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
            "observation_completed_at_utc",
            "fresh_verified_at_utc",
            "admitted_at_utc",
        ):
            _utc(getattr(self, name), name=name)
        observation = proof.authorization.remote_head_observation
        requirements = observation.requirements
        expected = {
            "admission_key_sha256": proof.remote_publication_nonce_sha256,
            "authorization_proof_sha256": proof.sha256,
            "authorization_sha256": proof.authorization_sha256,
            "authorization_signature_sha256": proof.signature_sha256,
            "remote_head_observation_sha256": observation.sha256,
            "observation_key_sha256": observation.observation_key_sha256,
            "requirements_sha256": observation.requirements_sha256,
            "requirements_key_sha256": observation.requirements_key_sha256,
            "repository": observation.repository,
            "base_sha": observation.base_sha,
            "local_commit_sha": observation.local_commit_sha,
            "destination_ref": observation.destination_ref,
            "canonical_remote_url": observation.canonical_remote_url,
            "remote_head_present": observation.remote_head_present,
            "remote_head_sha": observation.remote_head_sha,
            "publication_mode": observation.publication_mode,
            "remote_publication_nonce_sha256": proof.remote_publication_nonce_sha256,
            "observation_completed_at_utc": observation.observation_completed_at_utc,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                f"remote-publication admission receipt binding mismatch: {mismatch}"
            )
        if requirements.repository != self.repository:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission repository binding mismatch"
            )
        if _utc(self.fresh_verified_at_utc, name="fresh_verified_at_utc") < _utc(
            proof.authorization.authorized_at_utc, name="authorized_at_utc"
        ):
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "fresh proof verification predates human authorization"
            )
        if _utc(self.admitted_at_utc, name="admitted_at_utc") < _utc(
            self.fresh_verified_at_utc, name="fresh_verified_at_utc"
        ):
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "admission time predates fresh proof verification"
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission receipt lost required evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission cannot grant or consume remote authority"
            )

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }
        result["authorization_proof"] = self.authorization_proof.to_dict()
        return result

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission receipt fields mismatch"
            )
        mapped = dict(value)
        try:
            mapped["authorization_proof"] = (
                PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(
                    mapped["authorization_proof"]
                )
            )
        except Exception as exc:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission nested proof is invalid"
            ) from exc
        return cls(**mapped)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def admission_authenticated(self) -> bool:
        return (
            _get_live_remote_publication_authorization_admission_inputs(self)
            is not None
        )


class _PilotExactTaskRemotePublicationAuthorizationAdmissionLedger:
    """Create-once host-local replay ledger keyed by publication nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _lock_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='admission key')}.lock.json"

    def _receipt_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='admission key')}.receipt.json"

    def reserve(
        self,
        *,
        key: str,
        proof: PilotExactTaskRemotePublicationAuthorizationProof,
        observation: PilotExactTaskRemoteHeadObservation,
    ) -> tuple[Path, bytes]:
        lock = self._lock_path(key)
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-remote-publication-authorization-admission-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "admission_key_sha256": key,
                "authorization_proof_sha256": proof.sha256,
                "authorization_sha256": proof.authorization_sha256,
                "authorization_signature_sha256": proof.signature_sha256,
                "remote_head_observation_sha256": observation.sha256,
                "observation_key_sha256": observation.observation_key_sha256,
                "requirements_sha256": observation.requirements_sha256,
                "local_commit_sha": observation.local_commit_sha,
                "destination_ref": observation.destination_ref,
                "remote_head_present": observation.remote_head_present,
                "remote_head_sha": observation.remote_head_sha,
                "publication_mode": observation.publication_mode,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication nonce was already admitted or could not be durably reserved"
            ) from exc
        if _read_bound_file(lock) != payload:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission lock read-back mismatch"
            )
        return lock, payload

    def publish(
        self,
        *,
        key: str,
        receipt: PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt,
    ) -> tuple[Path, bytes]:
        path = self._receipt_path(key)
        payload = receipt.canonical_json().encode("utf-8")
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission receipt already exists or could not be persisted"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "remote-publication admission receipt read-back mismatch"
            )
        try:
            parsed = PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
        except Exception as exc:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "persisted remote-publication admission receipt is invalid"
            ) from exc
        if parsed != receipt or parsed.sha256 != receipt.sha256:
            raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
                "persisted remote-publication admission receipt identity mismatch"
            )
        return path, payload


def _admit_verified_pilot_exact_task_remote_publication_authorization(
    *,
    supplied_proof: PilotExactTaskRemotePublicationAuthorizationProof,
    fresh_proof: PilotExactTaskRemotePublicationAuthorizationProof,
    remote_head_observation: PilotExactTaskRemoteHeadObservation,
    ledger: _PilotExactTaskRemotePublicationAuthorizationAdmissionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt:
    supplied = _require_verified_proof(supplied_proof)
    fresh = _require_verified_proof(fresh_proof)
    require_fresh_remote_publication_authorization_proof_identity(supplied, fresh)
    observation, _live = _require_live_observation_for_proof(
        supplied,
        remote_head_observation,
    )
    if not isinstance(ledger, _PilotExactTaskRemotePublicationAuthorizationAdmissionLedger):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "host-local remote-publication admission ledger is required"
        )
    key = _admission_key(supplied)
    before = now_provider()
    if _utc(before, name="pre-admission time") < _utc(
        fresh.verified_at_utc, name="fresh_verified_at_utc"
    ):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "remote-publication admission clock moved backwards before durable reservation"
        )
    if _utc(before, name="pre-admission time") >= _utc(
        supplied.authorization.expires_at_utc,
        name="authorization expires_at_utc",
    ):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "human remote-publication authorization expired before durable reservation"
        )
    lock_path, lock_payload = ledger.reserve(
        key=key,
        proof=supplied,
        observation=observation,
    )
    admitted_at = now_provider()
    if _utc(admitted_at, name="admitted_at_utc") < _utc(
        before, name="pre-admission time"
    ):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "remote-publication admission clock moved backwards after durable nonce reservation"
        )
    if _utc(admitted_at, name="admitted_at_utc") >= _utc(
        supplied.authorization.expires_at_utc,
        name="authorization expires_at_utc",
    ):
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "human remote-publication authorization expired after durable nonce reservation; nonce remains burned"
        )
    receipt = PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        admission_key_sha256=key,
        authorization_proof=supplied,
        authorization_proof_sha256=supplied.sha256,
        authorization_sha256=supplied.authorization_sha256,
        authorization_signature_sha256=supplied.signature_sha256,
        remote_head_observation_sha256=observation.sha256,
        observation_key_sha256=observation.observation_key_sha256,
        requirements_sha256=observation.requirements_sha256,
        requirements_key_sha256=observation.requirements_key_sha256,
        repository=observation.repository,
        base_sha=observation.base_sha,
        local_commit_sha=observation.local_commit_sha,
        destination_ref=observation.destination_ref,
        canonical_remote_url=observation.canonical_remote_url,
        remote_head_present=observation.remote_head_present,
        remote_head_sha=observation.remote_head_sha,
        publication_mode=observation.publication_mode,
        remote_publication_nonce_sha256=supplied.remote_publication_nonce_sha256,
        observation_completed_at_utc=observation.observation_completed_at_utc,
        fresh_verified_at_utc=fresh.verified_at_utc,
        admitted_at_utc=admitted_at,
    )
    receipt_path, receipt_payload = ledger.publish(key=key, receipt=receipt)
    _mark_admission_authenticated(
        receipt,
        observation,
        lock_path=lock_path,
        lock_payload=lock_payload,
        receipt_path=receipt_path,
        receipt_payload=receipt_payload,
    )
    if receipt.admission_authenticated is not True:
        raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
            "live remote-publication admission provenance was not established"
        )
    return receipt


def admit_pilot_exact_task_remote_publication_authorization(
    *,
    authorization_proof: PilotExactTaskRemotePublicationAuthorizationProof,
    authorization_signature: Any,
    remote_head_observation: PilotExactTaskRemoteHeadObservation,
) -> PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt:
    raise PilotExactTaskRemotePublicationAuthorizationAdmissionError(
        "production remote-publication authorization admission boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_ADMISSION_LEDGER_SCOPE",
    "PilotExactTaskRemotePublicationAuthorizationAdmissionError",
    "PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt",
    "admit_pilot_exact_task_remote_publication_authorization",
]
