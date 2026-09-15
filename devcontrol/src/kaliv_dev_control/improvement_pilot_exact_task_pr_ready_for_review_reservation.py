"""ADR-DC-061 durable replay-safe reservation for one exact ready-for-review handoff.

The boundary accepts one live ADR-DC-060 human authorization proof, freshly
re-verifies the detached signature through the host-pinned production verifier,
then durably burns the signed ready-for-review nonce in a create-once host
ledger. No GitHub read or mutation occurs here.
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
from . import improvement_pilot_exact_task_pr_ready_for_review_authorization as auth_boundary
from . import improvement_pilot_exact_task_pr_review_handoff_requirements as requirements_boundary
from .improvement_pilot_exact_task_pr_ready_for_review_authorization import (
    PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskPrReadyAuthorizationProof,
)

PILOT_EXACT_TASK_PR_READY_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-reservation/v1"
)
PILOT_EXACT_TASK_PR_READY_RESERVATION_AUTHORITY = (
    "host-reserved-one-dc-l16-exact-pr-ready-for-review-slot-only"
)
PILOT_EXACT_TASK_PR_READY_RESERVATION_LEDGER_SCOPE = (
    "canonical-host-pr-ready-for-review-v1"
)
PILOT_EXACT_TASK_PR_READY_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-ready-for-review-reservation-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-ready-for-review-reservation-ledger-v1"
)


class PilotExactTaskPrReadyReservationError(ValueError):
    """The exact ready-for-review reservation is replayed, stale, drifted, or unsafe."""


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
        raise PilotExactTaskPrReadyReservationError(
            "ready-for-review reservation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReadyReservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReadyReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReadyReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReadyReservationError(f"{name} is invalid") from exc


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
        raise PilotExactTaskPrReadyReservationError(
            "ready-for-review reservation ledger root is unsafe"
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
        raise PilotExactTaskPrReadyReservationError(
            "canonical ready-for-review reservation ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPrReadyReservationError(
        "ready-for-review reservation platform is unsupported"
    )


def _stable_proof_mapping(value: PilotExactTaskPrReadyAuthorizationProof) -> dict[str, Any]:
    result = value.to_dict()
    result.pop("verified_at_utc")
    return result


def _require_live_proof(
    value: Any,
) -> tuple[PilotExactTaskPrReadyAuthorizationProof, Any]:
    if type(value) is not PilotExactTaskPrReadyAuthorizationProof:
        raise PilotExactTaskPrReadyReservationError(
            "exact ADR-DC-060 ready-for-review authorization proof is required"
        )
    try:
        replayed = PilotExactTaskPrReadyAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyReservationError(
            "ADR-DC-060 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReadyReservationError(
            "ADR-DC-060 proof identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_READY_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_ready_for_review_authorization_verified is not True
        or value.one_shot_ready_for_review_required is not True
        or value.fresh_pr_state_revalidation_before_ready_required is not True
        or value.reviewer_mutation_separate_authority_required is not True
        or value.label_mutation_separate_authority_required is not True
        or value.merge_separate_authority_required is not True
        or value.ready_for_review_authorization_consumed is not False
        or value.ready_for_review_authorized is not False
        or value.ready_for_review_performed is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrReadyReservationError(
            "ready reservation requires one live inert ADR-DC-060 proof"
        )
    requirements = value.authorization.review_handoff_requirements
    if (
        getattr(requirements, "requirements_authenticated", None) is not True
        or requirements.sha256 != value.review_handoff_requirements_sha256
        or requirements.pr_create_transaction_sha256
        != value.pr_create_transaction_sha256
        or requirements.predicted_commit_sha != value.predicted_commit_sha
        or requirements.review_handoff_plan_sha256
        != value.review_handoff_plan_sha256
        or requirements.pr_mutation_nonce_sha256
        != value.authorization.pr_mutation_nonce_sha256
    ):
        raise PilotExactTaskPrReadyReservationError(
            "ADR-DC-060 proof lost live review-handoff requirements"
        )
    if (
        requirements_boundary._get_live_pr_review_handoff_requirements_inputs(
            requirements
        )
        is None
    ):
        raise PilotExactTaskPrReadyReservationError(
            "ADR-DC-059 live review-handoff provenance is unavailable"
        )
    return value, requirements


def _require_fresh_proof_identity(
    supplied: PilotExactTaskPrReadyAuthorizationProof,
    fresh: PilotExactTaskPrReadyAuthorizationProof,
) -> None:
    _require_live_proof(supplied)
    _require_live_proof(fresh)
    if _stable_proof_mapping(supplied) != _stable_proof_mapping(fresh):
        raise PilotExactTaskPrReadyReservationError(
            "fresh ready authorization proof semantics differ from supplied proof"
        )


def _require_reservation_window(
    proof: PilotExactTaskPrReadyAuthorizationProof,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="ready reservation time")
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
        raise PilotExactTaskPrReadyReservationError(
            "human ready authorization is not valid for reservation now"
        )
    if (
        at - verified
    ).total_seconds() > PILOT_EXACT_TASK_PR_READY_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS:
        raise PilotExactTaskPrReadyReservationError(
            "fresh ready authorization proof is too old for reservation"
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReadyReservationReceipt:
    ledger_root_path_sha256: str
    reservation_key_sha256: str
    supplied_authorization_proof_sha256: str
    fresh_authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    review_handoff_plan_sha256: str
    pr_mutation_nonce_sha256: str
    ready_for_review_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    base_branch: str
    head_branch: str
    fresh_verified_at_utc: str
    reserved_at_utc: str
    host_replay_guard_committed: bool = True
    human_ready_for_review_authorization_freshly_verified: bool = True
    ready_for_review_authorization_consumed: bool = True
    ready_for_review_slot_reserved: bool = True
    fresh_pr_state_revalidation_before_ready_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_READY_RESERVATION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_READY_RESERVATION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_READY_RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_READY_RESERVATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_READY_RESERVATION_AUTHORITY
            or self.ledger_scope != PILOT_EXACT_TASK_PR_READY_RESERVATION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation schema/authority/scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "reservation_key_sha256",
            "supplied_authorization_proof_sha256",
            "fresh_authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "review_handoff_requirements_sha256",
            "pr_create_transaction_sha256",
            "review_handoff_plan_sha256",
            "pr_mutation_nonce_sha256",
            "ready_for_review_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.reservation_key_sha256 != self.ready_for_review_nonce_sha256
            or self.ready_for_review_nonce_sha256 == self.pr_mutation_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation target/nonce binding is invalid"
            )
        fresh = _utc(self.fresh_verified_at_utc, name="fresh_verified_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if reserved < fresh or (
            reserved - fresh
        ).total_seconds() > PILOT_EXACT_TASK_PR_READY_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS:
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation timestamps are invalid"
            )
        required_true = (
            "host_replay_guard_committed",
            "human_ready_for_review_authorization_freshly_verified",
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_reserved",
            "fresh_pr_state_revalidation_before_ready_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorized",
            "ready_for_review_performed",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation cannot grant GitHub mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def reservation_authenticated(self) -> bool:
        return _get_live_pr_ready_reservation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReadyReservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskPrReadyReservationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _path(self, nonce_sha256: str) -> Path:
        return self.root / (
            f"{_hex64(nonce_sha256, name='ready_for_review_nonce_sha256')}.json"
        )

    def reserve(
        self,
        receipt: PilotExactTaskPrReadyReservationReceipt,
    ) -> tuple[Path, bytes]:
        if (
            type(receipt) is not PilotExactTaskPrReadyReservationReceipt
            or receipt.ledger_root_path_sha256 != self.root_sha256
            or receipt.reservation_key_sha256
            != receipt.ready_for_review_nonce_sha256
        ):
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation receipt does not belong to this ledger"
            )
        path = self._path(receipt.ready_for_review_nonce_sha256)
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPrReadyReservationError(
                "ready reservation receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrReadyReservationError(
                "ready-for-review nonce is already reserved or ledger write failed"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskPrReadyReservationError(
                "durable ready reservation could not be read back exactly"
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
        receipt: PilotExactTaskPrReadyReservationReceipt,
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
            or requirements.sha256 != receipt.review_handoff_requirements_sha256
            or receipt.sha256 != digest
            or _read_bound_file(path) != payload
        ):
            return None
        return MappingProxyType(
            {"review_handoff_requirements": requirements}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_pr_ready_reservation_authenticated,
    _get_live_pr_ready_reservation_inputs,
) = _live_registry()


def _reserve_verified_pilot_exact_task_pr_ready_for_review(
    *,
    supplied_authorization_proof: PilotExactTaskPrReadyAuthorizationProof,
    fresh_authorization_proof: PilotExactTaskPrReadyAuthorizationProof,
    ledger: _PilotExactTaskPrReadyReservationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReadyReservationReceipt:
    supplied, requirements = _require_live_proof(supplied_authorization_proof)
    fresh, fresh_requirements = _require_live_proof(fresh_authorization_proof)
    if fresh_requirements is not requirements:
        raise PilotExactTaskPrReadyReservationError(
            "fresh ready proof is not bound to the supplied live requirements"
        )
    _require_fresh_proof_identity(supplied, fresh)
    reserved_at = now_provider()
    _require_reservation_window(fresh, at_utc=reserved_at)
    if not isinstance(ledger, _PilotExactTaskPrReadyReservationLedger):
        raise PilotExactTaskPrReadyReservationError(
            "exact ready-for-review reservation ledger is required"
        )

    receipt = PilotExactTaskPrReadyReservationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        reservation_key_sha256=fresh.ready_for_review_nonce_sha256,
        supplied_authorization_proof_sha256=supplied.sha256,
        fresh_authorization_proof_sha256=fresh.sha256,
        authorization_sha256=fresh.authorization_sha256,
        authorization_signature_sha256=fresh.signature_sha256,
        review_handoff_requirements_sha256=fresh.review_handoff_requirements_sha256,
        pr_create_transaction_sha256=fresh.pr_create_transaction_sha256,
        predicted_commit_sha=fresh.predicted_commit_sha,
        review_handoff_plan_sha256=fresh.review_handoff_plan_sha256,
        pr_mutation_nonce_sha256=fresh.authorization.pr_mutation_nonce_sha256,
        ready_for_review_nonce_sha256=fresh.ready_for_review_nonce_sha256,
        repository=requirements.repository,
        pull_request_number=requirements.pull_request_number,
        pull_request_api_url=requirements.pull_request_api_url,
        pull_request_html_url=requirements.pull_request_html_url,
        base_branch=requirements.base_branch,
        head_branch=requirements.head_branch,
        fresh_verified_at_utc=fresh.verified_at_utc,
        reserved_at_utc=reserved_at,
    )
    path, payload = ledger.reserve(receipt)
    _mark_pr_ready_reservation_authenticated(
        receipt,
        requirements,
        path=path,
        payload=payload,
    )
    if receipt.reservation_authenticated is not True:
        raise PilotExactTaskPrReadyReservationError(
            "ready reservation lost durable live provenance"
        )
    return receipt


def reserve_pilot_exact_task_pr_ready_for_review(
    authorization_proof: PilotExactTaskPrReadyAuthorizationProof,
    authorization_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskPrReadyReservationReceipt:
    """Freshly verify and consume one signed ready-for-review nonce."""
    supplied, requirements = _require_live_proof(authorization_proof)
    try:
        fresh = auth_boundary.verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=requirements,
            authorization=supplied.authorization,
            signature=authorization_signature,
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyReservationError(
            "fresh host-pinned ADR-DC-060 signature verification failed"
        ) from exc
    _require_fresh_proof_identity(supplied, fresh)
    ledger = _PilotExactTaskPrReadyReservationLedger(_canonical_ledger_root())
    return _reserve_verified_pilot_exact_task_pr_ready_for_review(
        supplied_authorization_proof=supplied,
        fresh_authorization_proof=fresh,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_READY_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_READY_RESERVATION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_READY_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS",
    "PilotExactTaskPrReadyReservationError",
    "PilotExactTaskPrReadyReservationReceipt",
    "reserve_pilot_exact_task_pr_ready_for_review",
]
