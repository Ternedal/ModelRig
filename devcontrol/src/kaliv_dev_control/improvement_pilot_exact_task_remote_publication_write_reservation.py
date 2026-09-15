"""ADR-DC-051 durable replay-safe reservation for one exact remote publication write.

The boundary accepts only one live ADR-DC-050 observation, re-observes the exact
host-pinned destination read-only, then durably burns the signed remote-publication
nonce in a create-once host ledger. Reservation consumes the human publication
authorization but grants no remote-write, push, PR, merge, release, deploy or
production-activation authority.
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

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_remote_publication_state_observation as state_boundary
from . import improvement_pilot_exact_task_remote_publication_target_attestation as target_boundary
from .improvement_pilot_exact_task_remote_publication_state_observation import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA,
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskRemotePublicationStateObservation,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-write-reservation/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_AUTHORITY = (
    "host-reserved-one-dc-l16-exact-remote-publication-write-slot-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_LEDGER_SCOPE = (
    "canonical-host-remote-publication-v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_MAX_OBSERVATION_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REF = re.compile(r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-remote-publication-write-reservation-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-remote-publication-write-reservation-ledger-v1"
)


class PilotExactTaskRemotePublicationWriteReservationError(ValueError):
    """The exact remote-write reservation is replayed, stale, drifted, or unsafe."""


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
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "remote-write reservation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationWriteReservationError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            f"{name} is invalid"
        )
    if not allow_zero and value == "0" * 40:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            f"{name} must not be zero"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


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


def _require_safe_ledger_root(path: Path) -> Path:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or not candidate.is_dir()
        or _has_linkish_component(candidate)
    ):
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "remote-write reservation ledger root is unsafe"
        )
    return candidate


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            return _require_host_controlled_ledger_root(_POSIX_LEDGER)
        if os.name == "nt":
            return _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "canonical remote-write reservation ledger is not host controlled"
        ) from exc
    raise PilotExactTaskRemotePublicationWriteReservationError(
        "remote-write reservation platform is unsupported"
    )


def _stable_observation_mapping(
    value: PilotExactTaskRemotePublicationStateObservation,
) -> dict[str, Any]:
    result = value.to_dict()
    result.pop("observed_at_utc")
    return result


def _require_live_observation(
    value: Any,
) -> tuple[PilotExactTaskRemotePublicationStateObservation, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskRemotePublicationStateObservation:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "exact ADR-DC-050 remote state observation is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationStateObservation.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-050 observation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-050 observation identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.target_attestation_verified is not True
        or value.fresh_local_commit_revalidated is not True
        or value.remote_state_observed is not True
        or value.remote_destination_ref_absent is not True
        or value.expected_old_remote_sha_bound is not True
        or value.create_only_remote_ref_required is not True
        or value.remote_write_reservation_required is not True
        or value.remote_branch_compare_and_swap_required is not True
        or value.no_force_push_required is not True
        or value.separate_pr_mutation_authorization_required is not True
        or value.remote_publication_authorization_consumed is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.expected_old_remote_sha
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA
        or _REF.fullmatch(value.destination_ref) is None
    ):
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "remote-write reservation requires one live inert ADR-DC-050 observation"
        )
    inputs = state_boundary._get_live_remote_publication_state_observation_inputs(
        value
    )
    if inputs is None:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-050 live observation provenance is unavailable"
        )
    attestation = inputs.get("remote_publication_target_attestation")
    if (
        attestation is None
        or getattr(attestation, "sha256", None) != value.target_attestation_sha256
        or getattr(attestation, "target_attestation_authenticated", None) is not True
        or getattr(attestation, "remote_publication_nonce_sha256", None)
        != value.remote_publication_nonce_sha256
        or getattr(attestation, "predicted_commit_sha", None)
        != value.predicted_commit_sha
        or getattr(attestation, "destination_ref", None) != value.destination_ref
    ):
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-050 observation lost exact live target provenance"
        )
    return value, inputs


def _require_reservation_window(
    observation: PilotExactTaskRemotePublicationStateObservation,
    *,
    at_utc: str,
) -> datetime:
    at = _utc(at_utc, name="remote-write reservation time")
    observed = _utc(observation.observed_at_utc, name="ADR-DC-050 observed_at_utc")
    if at < observed:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "system clock moved backwards after ADR-DC-050 observation"
        )
    if (
        at - observed
    ).total_seconds() > PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_MAX_OBSERVATION_AGE_SECONDS:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-050 observation is too old for remote-write reservation"
        )

    live = state_boundary._get_live_remote_publication_state_observation_inputs(
        observation
    )
    if live is None:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-050 live provenance disappeared before reservation"
        )
    attestation = live.get("remote_publication_target_attestation")
    proof = None
    if attestation is not None:
        target_inputs = target_boundary._get_live_remote_publication_target_attestation_inputs(
            attestation
        )
        if target_inputs is not None:
            proof = target_inputs.get("remote_publication_authorization_proof")
    if proof is None:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "live human remote-publication proof is unavailable"
        )
    authorized = _utc(
        proof.authorization.authorized_at_utc,
        name="remote authorization authorized_at_utc",
    )
    expires = _utc(
        proof.authorization.expires_at_utc,
        name="remote authorization expires_at_utc",
    )
    if at < authorized or at > expires:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "human remote-publication authorization is not valid for reservation now"
        )
    return at


def _fresh_observation(
    supplied: PilotExactTaskRemotePublicationStateObservation,
    *,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationStateObservation:
    inputs = state_boundary._get_live_remote_publication_state_observation_inputs(
        supplied
    )
    if inputs is None:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-050 live provenance is unavailable for fresh observation"
        )
    attestation = inputs.get("remote_publication_target_attestation")
    if attestation is None:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "ADR-DC-049 live target attestation is unavailable"
        )
    try:
        fresh = state_boundary._observe_verified_pilot_exact_task_remote_publication_state(
            target_attestation=attestation,
            now_provider=now_provider,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "fresh ADR-DC-050 remote state observation failed"
        ) from exc
    if _stable_observation_mapping(fresh) != _stable_observation_mapping(supplied):
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "fresh remote state semantics differ from supplied ADR-DC-050 observation"
        )
    return fresh


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationWriteReservationReceipt:
    ledger_root_path_sha256: str
    reservation_key_sha256: str
    state_observation_sha256: str
    fresh_state_observation_sha256: str
    target_attestation_sha256: str
    authorization_proof_sha256: str
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    predicted_commit_sha: str
    target_policy_sha256: str
    canonical_remote_url: str
    destination_ref: str
    expected_old_remote_sha: str
    supplied_observed_at_utc: str
    fresh_observed_at_utc: str
    reserved_at_utc: str
    host_replay_guard_committed: bool = True
    fresh_remote_state_revalidated: bool = True
    remote_destination_ref_absent: bool = True
    create_only_remote_ref_required: bool = True
    remote_publication_authorization_consumed: bool = True
    remote_write_slot_reserved: bool = True
    remote_write_transaction_required: bool = True
    fresh_remote_state_revalidation_before_write_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_SCHEMA:
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation schema is unsupported"
            )
        if (
            self.authority
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_AUTHORITY
            or self.ledger_scope
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_LEDGER_SCOPE
        ):
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation authority/scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "reservation_key_sha256",
            "state_observation_sha256",
            "fresh_state_observation_sha256",
            "target_attestation_sha256",
            "authorization_proof_sha256",
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "remote_publication_nonce_sha256",
            "target_policy_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(
            self.expected_old_remote_sha,
            name="expected_old_remote_sha",
            allow_zero=True,
        )
        if (
            self.reservation_key_sha256 != self.remote_publication_nonce_sha256
            or self.expected_old_remote_sha
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA
            or self.canonical_remote_url != "https://github.com/Ternedal/ModelRig.git"
            or _REF.fullmatch(self.destination_ref) is None
            or not self.destination_ref.endswith(self.remote_publication_nonce_sha256)
        ):
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation target binding is invalid"
            )
        supplied = _utc(self.supplied_observed_at_utc, name="supplied_observed_at_utc")
        fresh = _utc(self.fresh_observed_at_utc, name="fresh_observed_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if fresh < supplied or reserved < fresh:
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation timestamps are not monotonic"
            )
        if (
            reserved - fresh
        ).total_seconds() > PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_MAX_OBSERVATION_AGE_SECONDS:
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "fresh remote observation is too old for committed reservation"
            )
        required_true = (
            "host_replay_guard_committed",
            "fresh_remote_state_revalidated",
            "remote_destination_ref_absent",
            "create_only_remote_ref_required",
            "remote_publication_authorization_consumed",
            "remote_write_slot_reserved",
            "remote_write_transaction_required",
            "fresh_remote_state_revalidation_before_write_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        )
        forced_false = (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation cannot grant mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def reservation_authenticated(self) -> bool:
        return _get_live_remote_publication_write_reservation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationWriteReservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskRemotePublicationWriteReservationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _path(self, nonce_sha256: str) -> Path:
        nonce = _hex64(nonce_sha256, name="remote_publication_nonce_sha256")
        return self.root / f"{nonce}.json"

    def reserve(
        self,
        receipt: PilotExactTaskRemotePublicationWriteReservationReceipt,
    ) -> tuple[Path, bytes]:
        if (
            type(receipt) is not PilotExactTaskRemotePublicationWriteReservationReceipt
            or receipt.ledger_root_path_sha256 != self.root_sha256
            or receipt.reservation_key_sha256 != receipt.remote_publication_nonce_sha256
        ):
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "reservation receipt does not belong to this ledger"
            )
        path = self._path(receipt.remote_publication_nonce_sha256)
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-write reservation receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "remote-publication nonce is already reserved or ledger write failed"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskRemotePublicationWriteReservationError(
                "durable remote-write reservation could not be read back exactly"
            )
        return path, payload


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            PilotExactTaskRemotePublicationStateObservation,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: PilotExactTaskRemotePublicationWriteReservationReceipt,
        fresh_observation: PilotExactTaskRemotePublicationStateObservation,
        *,
        path: Path,
        payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            fresh_observation,
            path,
            payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, observation, path, payload = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or observation.observation_authenticated is not True
            or receipt.sha256 != digest
            or observation.sha256 != receipt.fresh_state_observation_sha256
            or observation.remote_publication_nonce_sha256
            != receipt.remote_publication_nonce_sha256
            or observation.destination_ref != receipt.destination_ref
            or _read_bound_file(path) != payload
        ):
            return None
        return MappingProxyType(
            {"remote_publication_state_observation": observation}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_write_reservation_authenticated,
    _get_live_remote_publication_write_reservation_inputs,
) = _live_registry()


def _reserve_verified_pilot_exact_task_remote_publication_write(
    *,
    state_observation: PilotExactTaskRemotePublicationStateObservation,
    ledger: _PilotExactTaskRemotePublicationWriteReservationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationWriteReservationReceipt:
    supplied, _inputs = _require_live_observation(state_observation)
    started_at = now_provider()
    _require_reservation_window(supplied, at_utc=started_at)

    fresh = _fresh_observation(supplied, now_provider=now_provider)
    reserved_at = now_provider()
    _require_reservation_window(fresh, at_utc=reserved_at)

    if not isinstance(ledger, _PilotExactTaskRemotePublicationWriteReservationLedger):
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "exact remote-write reservation ledger is required"
        )

    receipt = PilotExactTaskRemotePublicationWriteReservationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        reservation_key_sha256=fresh.remote_publication_nonce_sha256,
        state_observation_sha256=supplied.sha256,
        fresh_state_observation_sha256=fresh.sha256,
        target_attestation_sha256=fresh.target_attestation_sha256,
        authorization_proof_sha256=fresh.authorization_proof_sha256,
        local_commit_publication_requirements_sha256=(
            fresh.local_commit_publication_requirements_sha256
        ),
        local_commit_write_transaction_sha256=(
            fresh.local_commit_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=fresh.remote_publication_nonce_sha256,
        predicted_commit_sha=fresh.predicted_commit_sha,
        target_policy_sha256=fresh.target_policy_sha256,
        canonical_remote_url=fresh.canonical_remote_url,
        destination_ref=fresh.destination_ref,
        expected_old_remote_sha=fresh.expected_old_remote_sha,
        supplied_observed_at_utc=supplied.observed_at_utc,
        fresh_observed_at_utc=fresh.observed_at_utc,
        reserved_at_utc=reserved_at,
    )
    path, payload = ledger.reserve(receipt)
    _mark_remote_publication_write_reservation_authenticated(
        receipt,
        fresh,
        path=path,
        payload=payload,
    )
    if receipt.reservation_authenticated is not True:
        raise PilotExactTaskRemotePublicationWriteReservationError(
            "remote-write reservation lost durable live provenance"
        )
    return receipt


def reserve_pilot_exact_task_remote_publication_write(
    state_observation: PilotExactTaskRemotePublicationStateObservation,
) -> PilotExactTaskRemotePublicationWriteReservationReceipt:
    """Durably consume one signed publication nonce without performing a push."""
    root = _canonical_ledger_root()
    ledger = _PilotExactTaskRemotePublicationWriteReservationLedger(root)
    return _reserve_verified_pilot_exact_task_remote_publication_write(
        state_observation=state_observation,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_RESERVATION_MAX_OBSERVATION_AGE_SECONDS",
    "PilotExactTaskRemotePublicationWriteReservationError",
    "PilotExactTaskRemotePublicationWriteReservationReceipt",
    "reserve_pilot_exact_task_remote_publication_write",
]
