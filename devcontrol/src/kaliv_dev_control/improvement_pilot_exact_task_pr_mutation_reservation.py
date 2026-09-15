"""ADR-DC-055 durable replay-safe reservation for one exact draft-PR mutation.

The boundary accepts one live ADR-DC-054 human authorization proof, freshly
re-verifies the exact detached signature through the host-pinned production
verifier, then durably burns the signed PR-mutation nonce in a create-once host
ledger. No GitHub PR read or mutation occurs here.
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
from .asymmetric_authority import DetachedEd25519AuthoritySignature
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_pr_mutation_authorization as auth_boundary
from . import improvement_pilot_exact_task_pr_mutation_requirements as requirements_boundary
from .improvement_pilot_exact_task_pr_mutation_authorization import (
    PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskPrMutationAuthorizationProof,
)

PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-mutation-reservation/v1"
)
PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_AUTHORITY = (
    "host-reserved-one-dc-l16-exact-draft-pr-mutation-slot-only"
)
PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_LEDGER_SCOPE = (
    "canonical-host-pr-mutation-v1"
)
PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-mutation-reservation-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-mutation-reservation-ledger-v1"
)


class PilotExactTaskPrMutationReservationError(ValueError):
    """The exact draft-PR reservation is replayed, stale, drifted, or unsafe."""


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
        raise PilotExactTaskPrMutationReservationError(
            "PR mutation reservation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrMutationReservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrMutationReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrMutationReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrMutationReservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _read_bound_file(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink():
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
    if not candidate.is_absolute() or not candidate.is_dir() or candidate.is_symlink():
        raise PilotExactTaskPrMutationReservationError(
            "PR mutation reservation ledger root is unsafe"
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
        raise PilotExactTaskPrMutationReservationError(
            "canonical PR mutation reservation ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPrMutationReservationError(
        "PR mutation reservation platform is unsupported"
    )


def _stable_proof_mapping(value: PilotExactTaskPrMutationAuthorizationProof) -> dict[str, Any]:
    result = value.to_dict()
    result.pop("verified_at_utc")
    return result


def _require_live_proof(
    value: Any,
) -> tuple[PilotExactTaskPrMutationAuthorizationProof, Any]:
    if type(value) is not PilotExactTaskPrMutationAuthorizationProof:
        raise PilotExactTaskPrMutationReservationError(
            "exact ADR-DC-054 PR authorization proof is required"
        )
    try:
        replayed = PilotExactTaskPrMutationAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrMutationReservationError(
            "ADR-DC-054 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrMutationReservationError(
            "ADR-DC-054 proof identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_MUTATION_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_pr_mutation_authorization_verified is not True
        or value.one_shot_pr_mutation_required is not True
        or value.create_new_draft_pull_request_required is not True
        or value.no_existing_open_pr_required is not True
        or value.ready_for_review_forbidden is not True
        or value.reviewer_mutation_forbidden is not True
        or value.label_mutation_forbidden is not True
        or value.pr_mutation_authorization_consumed is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.pull_request_created is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrMutationReservationError(
            "PR reservation requires one live inert ADR-DC-054 proof"
        )
    requirements = value.authorization.pr_mutation_requirements
    if (
        getattr(requirements, "requirements_authenticated", None) is not True
        or requirements.sha256 != value.pr_mutation_requirements_sha256
        or requirements.remote_write_transaction_sha256
        != value.remote_write_transaction_sha256
        or requirements.predicted_commit_sha != value.predicted_commit_sha
        or requirements.pr_plan_sha256 != value.pr_plan_sha256
    ):
        raise PilotExactTaskPrMutationReservationError(
            "ADR-DC-054 proof lost live deterministic PR requirements"
        )
    if requirements_boundary._get_live_pr_mutation_requirements_inputs(requirements) is None:
        raise PilotExactTaskPrMutationReservationError(
            "ADR-DC-054 live requirements provenance is unavailable"
        )
    return value, requirements


def _require_fresh_proof_identity(
    supplied: PilotExactTaskPrMutationAuthorizationProof,
    fresh: PilotExactTaskPrMutationAuthorizationProof,
) -> None:
    _require_live_proof(supplied)
    _require_live_proof(fresh)
    if _stable_proof_mapping(supplied) != _stable_proof_mapping(fresh):
        raise PilotExactTaskPrMutationReservationError(
            "fresh PR authorization proof semantics differ from supplied proof"
        )


def _require_reservation_window(
    proof: PilotExactTaskPrMutationAuthorizationProof,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="PR reservation time")
    verified = _utc(proof.verified_at_utc, name="proof verified_at_utc")
    authorized = _utc(
        proof.authorization.authorized_at_utc,
        name="authorization authorized_at_utc",
    )
    expires = _utc(
        proof.authorization.expires_at_utc,
        name="authorization expires_at_utc",
    )
    if at < verified or at < authorized or at > expires:
        raise PilotExactTaskPrMutationReservationError(
            "human PR authorization is not valid for reservation now"
        )
    if (
        at - verified
    ).total_seconds() > PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS:
        raise PilotExactTaskPrMutationReservationError(
            "fresh PR authorization proof is too old for reservation"
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrMutationReservationReceipt:
    ledger_root_path_sha256: str
    reservation_key_sha256: str
    supplied_authorization_proof_sha256: str
    fresh_authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    pr_mutation_requirements_sha256: str
    remote_write_transaction_sha256: str
    predicted_commit_sha: str
    pr_plan_sha256: str
    pr_mutation_nonce_sha256: str
    repository: str
    base_branch: str
    head_branch: str
    fresh_verified_at_utc: str
    reserved_at_utc: str
    host_replay_guard_committed: bool = True
    human_pr_mutation_authorization_freshly_verified: bool = True
    pr_mutation_authorization_consumed: bool = True
    pr_mutation_slot_reserved: bool = True
    no_existing_open_pr_observation_required: bool = True
    create_new_draft_pull_request_required: bool = True
    draft_pull_request_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_SCHEMA:
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation schema is unsupported"
            )
        if (
            self.authority != PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_AUTHORITY
            or self.ledger_scope != PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation authority/scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "reservation_key_sha256",
            "supplied_authorization_proof_sha256",
            "fresh_authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "pr_mutation_requirements_sha256",
            "remote_write_transaction_sha256",
            "pr_plan_sha256",
            "pr_mutation_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.reservation_key_sha256 != self.pr_mutation_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
        ):
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation target binding is invalid"
            )
        fresh = _utc(self.fresh_verified_at_utc, name="fresh_verified_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if reserved < fresh or (
            reserved - fresh
        ).total_seconds() > PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS:
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation timestamps are invalid"
            )
        required_true = (
            "host_replay_guard_committed",
            "human_pr_mutation_authorization_freshly_verified",
            "pr_mutation_authorization_consumed",
            "pr_mutation_slot_reserved",
            "no_existing_open_pr_observation_required",
            "create_new_draft_pull_request_required",
            "draft_pull_request_required",
        )
        forced_false = (
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation cannot grant GitHub mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def reservation_authenticated(self) -> bool:
        return _get_live_pr_mutation_reservation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrMutationReservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskPrMutationReservationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _path(self, nonce_sha256: str) -> Path:
        return self.root / f"{_hex64(nonce_sha256, name='pr_mutation_nonce_sha256')}.json"

    def reserve(
        self,
        receipt: PilotExactTaskPrMutationReservationReceipt,
    ) -> tuple[Path, bytes]:
        if (
            type(receipt) is not PilotExactTaskPrMutationReservationReceipt
            or receipt.ledger_root_path_sha256 != self.root_sha256
            or receipt.reservation_key_sha256 != receipt.pr_mutation_nonce_sha256
        ):
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation receipt does not belong to this ledger"
            )
        path = self._path(receipt.pr_mutation_nonce_sha256)
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPrMutationReservationError(
                "PR mutation reservation receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrMutationReservationError(
                "PR-mutation nonce is already reserved or ledger write failed"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskPrMutationReservationError(
                "durable PR mutation reservation could not be read back exactly"
            )
        return path, payload


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: PilotExactTaskPrMutationReservationReceipt,
        requirements: Any,
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
            weakref.ref(requirements),
            path,
            payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, requirements_ref, path, payload = entry
        requirements = requirements_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or requirements is None
            or getattr(requirements, "requirements_authenticated", None) is not True
            or requirements.sha256 != receipt.pr_mutation_requirements_sha256
            or receipt.sha256 != digest
            or _read_bound_file(path) != payload
        ):
            return None
        return MappingProxyType({"pr_mutation_requirements": requirements})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_pr_mutation_reservation_authenticated,
    _get_live_pr_mutation_reservation_inputs,
) = _live_registry()


def _reserve_verified_pilot_exact_task_pr_mutation(
    *,
    supplied_authorization_proof: PilotExactTaskPrMutationAuthorizationProof,
    fresh_authorization_proof: PilotExactTaskPrMutationAuthorizationProof,
    ledger: _PilotExactTaskPrMutationReservationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrMutationReservationReceipt:
    supplied, requirements = _require_live_proof(supplied_authorization_proof)
    fresh, fresh_requirements = _require_live_proof(fresh_authorization_proof)
    if fresh_requirements is not requirements:
        raise PilotExactTaskPrMutationReservationError(
            "fresh PR proof is not bound to the supplied live requirements"
        )
    _require_fresh_proof_identity(supplied, fresh)
    reserved_at = now_provider()
    _require_reservation_window(fresh, at_utc=reserved_at)
    if not isinstance(ledger, _PilotExactTaskPrMutationReservationLedger):
        raise PilotExactTaskPrMutationReservationError(
            "exact PR mutation reservation ledger is required"
        )

    receipt = PilotExactTaskPrMutationReservationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        reservation_key_sha256=fresh.pr_mutation_nonce_sha256,
        supplied_authorization_proof_sha256=supplied.sha256,
        fresh_authorization_proof_sha256=fresh.sha256,
        authorization_sha256=fresh.authorization_sha256,
        authorization_signature_sha256=fresh.signature_sha256,
        pr_mutation_requirements_sha256=fresh.pr_mutation_requirements_sha256,
        remote_write_transaction_sha256=fresh.remote_write_transaction_sha256,
        predicted_commit_sha=fresh.predicted_commit_sha,
        pr_plan_sha256=fresh.pr_plan_sha256,
        pr_mutation_nonce_sha256=fresh.pr_mutation_nonce_sha256,
        repository=requirements.repository,
        base_branch=requirements.base_branch,
        head_branch=requirements.head_branch,
        fresh_verified_at_utc=fresh.verified_at_utc,
        reserved_at_utc=reserved_at,
    )
    path, payload = ledger.reserve(receipt)
    _mark_pr_mutation_reservation_authenticated(
        receipt,
        requirements,
        path=path,
        payload=payload,
    )
    if receipt.reservation_authenticated is not True:
        raise PilotExactTaskPrMutationReservationError(
            "PR mutation reservation lost durable live provenance"
        )
    return receipt


def reserve_pilot_exact_task_pr_mutation(
    authorization_proof: PilotExactTaskPrMutationAuthorizationProof,
    authorization_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskPrMutationReservationReceipt:
    """Freshly verify and consume one signed PR-mutation nonce without GitHub mutation."""
    supplied, requirements = _require_live_proof(authorization_proof)
    try:
        fresh = auth_boundary.verify_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization=supplied.authorization,
            signature=authorization_signature,
        )
    except Exception as exc:
        raise PilotExactTaskPrMutationReservationError(
            "fresh host-pinned ADR-DC-054 signature verification failed"
        ) from exc
    _require_fresh_proof_identity(supplied, fresh)
    ledger = _PilotExactTaskPrMutationReservationLedger(_canonical_ledger_root())
    return _reserve_verified_pilot_exact_task_pr_mutation(
        supplied_authorization_proof=supplied,
        fresh_authorization_proof=fresh,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_MUTATION_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS",
    "PilotExactTaskPrMutationReservationError",
    "PilotExactTaskPrMutationReservationReceipt",
    "reserve_pilot_exact_task_pr_mutation",
]
