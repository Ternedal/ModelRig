"""ADR-DC-069 durable replay-safe reservation for one exact reviewer request.

Accepts one live ADR-DC-068 human authorization proof, freshly re-verifies the
detached signature through the host-pinned production verifier, then durably
burns the signed reviewer-request nonce in a create-once host ledger. No GitHub
read or mutation occurs here.
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
from . import improvement_pilot_exact_task_pr_reviewer_request_authorization as auth_boundary
from . import improvement_pilot_exact_task_pr_reviewer_target_attestation as target_boundary
from .improvement_pilot_exact_task_pr_reviewer_request_authorization import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskPrReviewerRequestAuthorizationProof,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-reservation/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_AUTHORITY = (
    "host-reserved-one-dc-l16-exact-pr-reviewer-request-slot-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_LEDGER_SCOPE = (
    "canonical-host-pr-reviewer-request-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-reviewer-request-reservation-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-reviewer-request-reservation-ledger-v1"
)


class PilotExactTaskPrReviewerRequestReservationError(ValueError):
    """Exact reviewer-request reservation is replayed, stale, drifted, or unsafe."""


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
        raise PilotExactTaskPrReviewerRequestReservationError(
            "reviewer-request reservation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerRequestReservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerRequestReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestReservationError(f"{name} is invalid") from exc


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
        raise PilotExactTaskPrReviewerRequestReservationError(
            "reviewer-request reservation ledger root is unsafe"
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
        raise PilotExactTaskPrReviewerRequestReservationError(
            "canonical reviewer-request reservation ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPrReviewerRequestReservationError(
        "reviewer-request reservation platform is unsupported"
    )


def _stable_proof_mapping(
    value: PilotExactTaskPrReviewerRequestAuthorizationProof,
) -> dict[str, Any]:
    result = value.to_dict()
    result.pop("verified_at_utc")
    return result


def _require_live_proof(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerRequestAuthorizationProof, Any]:
    if type(value) is not PilotExactTaskPrReviewerRequestAuthorizationProof:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "exact ADR-DC-068 reviewer-request authorization proof is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "ADR-DC-068 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "ADR-DC-068 proof identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_reviewer_request_authorization_verified is not True
        or value.one_shot_reviewer_request_required is not True
        or value.reviewer_identity_observation_required is not True
        or value.reviewer_requestability_observation_required is not True
        or value.fresh_pr_state_revalidation_before_reviewer_request_required is not True
        or value.reviewer_request_transaction_required is not True
        or value.team_reviewers_forbidden is not True
        or value.self_review_forbidden is not True
        or value.reviewer_request_authorization_consumed is not False
        or value.reviewer_mutation_authorized is not False
        or value.reviewer_request_performed is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrReviewerRequestReservationError(
            "reviewer-request reservation requires one live inert ADR-DC-068 proof"
        )
    target = value.authorization.reviewer_target_attestation
    if (
        getattr(target, "attestation_authenticated", None) is not True
        or target.sha256 != value.reviewer_target_attestation_sha256
        or target.reviewer_handoff_requirements_sha256
        != value.reviewer_handoff_requirements_sha256
        or target.ready_transaction_sha256 != value.ready_transaction_sha256
        or target.predicted_commit_sha != value.predicted_commit_sha
        or target.reviewer_handoff_plan_sha256 != value.reviewer_handoff_plan_sha256
        or target.reviewer_target_policy_sha256 != value.reviewer_target_policy_sha256
        or target.reviewer_login != value.reviewer_login
        or target.reviewer_user_id != value.reviewer_user_id
    ):
        raise PilotExactTaskPrReviewerRequestReservationError(
            "ADR-DC-068 proof lost live exact reviewer-target provenance"
        )
    if target_boundary._get_live_pr_reviewer_target_attestation_inputs(target) is None:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "ADR-DC-067 live reviewer-target provenance is unavailable"
        )
    return value, target


def _require_fresh_proof_identity(
    supplied: PilotExactTaskPrReviewerRequestAuthorizationProof,
    fresh: PilotExactTaskPrReviewerRequestAuthorizationProof,
) -> None:
    _require_live_proof(supplied)
    _require_live_proof(fresh)
    if _stable_proof_mapping(supplied) != _stable_proof_mapping(fresh):
        raise PilotExactTaskPrReviewerRequestReservationError(
            "fresh reviewer-request proof semantics differ from supplied proof"
        )


def _require_reservation_window(
    proof: PilotExactTaskPrReviewerRequestAuthorizationProof,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="reviewer-request reservation time")
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
        raise PilotExactTaskPrReviewerRequestReservationError(
            "human reviewer-request authorization is not valid for reservation now"
        )
    if (
        at - verified
    ).total_seconds() > PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "fresh reviewer-request proof is too old for reservation"
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestReservationReceipt:
    ledger_root_path_sha256: str
    reservation_key_sha256: str
    supplied_authorization_proof_sha256: str
    fresh_authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    ready_transaction_sha256: str
    predicted_commit_sha: str
    reviewer_handoff_plan_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    reviewer_login: str
    reviewer_user_id: int
    ready_for_review_nonce_sha256: str
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    fresh_verified_at_utc: str
    reserved_at_utc: str
    host_replay_guard_committed: bool = True
    human_reviewer_request_authorization_freshly_verified: bool = True
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_reserved: bool = True
    reviewer_identity_observation_required: bool = True
    reviewer_requestability_observation_required: bool = True
    fresh_pr_state_revalidation_before_reviewer_request_required: bool = True
    reviewer_request_transaction_required: bool = True
    team_reviewers_forbidden: bool = True
    self_review_forbidden: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    reviewer_mutation_authorized: bool = False
    reviewer_request_performed: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_AUTHORITY
            or self.ledger_scope
            != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation schema/authority/scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "reservation_key_sha256",
            "supplied_authorization_proof_sha256",
            "fresh_authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "ready_transaction_sha256",
            "reviewer_handoff_plan_sha256",
            "reviewer_target_policy_sha256",
            "ready_for_review_nonce_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.reservation_key_sha256 != self.reviewer_request_nonce_sha256
            or self.reviewer_request_nonce_sha256 == self.ready_for_review_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or isinstance(self.reviewer_target_policy_epoch, bool)
            or not isinstance(self.reviewer_target_policy_epoch, int)
            or self.reviewer_target_policy_epoch < 1
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation target/nonce binding is invalid"
            )
        fresh = _utc(self.fresh_verified_at_utc, name="fresh_verified_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if reserved < fresh or (
            reserved - fresh
        ).total_seconds() > PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS:
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation timestamps are invalid"
            )
        required_true = (
            "host_replay_guard_committed",
            "human_reviewer_request_authorization_freshly_verified",
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation cannot grant GitHub mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def reservation_authenticated(self) -> bool:
        return _get_live_pr_reviewer_request_reservation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerRequestReservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskPrReviewerRequestReservationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _path(self, nonce_sha256: str) -> Path:
        return self.root / (
            f"{_hex64(nonce_sha256, name='reviewer_request_nonce_sha256')}.json"
        )

    def reserve(
        self,
        receipt: PilotExactTaskPrReviewerRequestReservationReceipt,
    ) -> tuple[Path, bytes]:
        if (
            type(receipt) is not PilotExactTaskPrReviewerRequestReservationReceipt
            or receipt.ledger_root_path_sha256 != self.root_sha256
            or receipt.reservation_key_sha256 != receipt.reviewer_request_nonce_sha256
        ):
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation receipt does not belong to this ledger"
            )
        path = self._path(receipt.reviewer_request_nonce_sha256)
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request reservation receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrReviewerRequestReservationError(
                "reviewer-request nonce is already reserved or ledger write failed"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskPrReviewerRequestReservationError(
                "durable reviewer-request reservation could not be read back exactly"
            )
        return path, payload


_live_records: dict[
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


def _mark_pr_reviewer_request_reservation_authenticated(
    receipt: PilotExactTaskPrReviewerRequestReservationReceipt,
    target: Any,
    *,
    path: Path,
    payload: bytes,
) -> None:
    key = id(receipt)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        receipt.sha256,
        weakref.ref(receipt, cleanup),
        weakref.ref(target),
        path,
        payload,
    )


def _get_live_pr_reviewer_request_reservation_inputs(receipt: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(receipt))
    if entry is None:
        return None
    pid, digest, receipt_ref, target_ref, path, payload = entry
    target = target_ref()
    if (
        pid != os.getpid()
        or receipt_ref() is not receipt
        or target is None
        or getattr(target, "attestation_authenticated", None) is not True
        or target.sha256 != receipt.reviewer_target_attestation_sha256
        or receipt.sha256 != digest
        or _read_bound_file(path) != payload
    ):
        return None
    return MappingProxyType({"reviewer_target_attestation": target})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


def _reserve_verified_pilot_exact_task_pr_reviewer_request(
    *,
    supplied_authorization_proof: PilotExactTaskPrReviewerRequestAuthorizationProof,
    fresh_authorization_proof: PilotExactTaskPrReviewerRequestAuthorizationProof,
    ledger: _PilotExactTaskPrReviewerRequestReservationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerRequestReservationReceipt:
    supplied, target = _require_live_proof(supplied_authorization_proof)
    fresh, fresh_target = _require_live_proof(fresh_authorization_proof)
    if fresh_target is not target:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "fresh reviewer-request proof is not bound to supplied live target"
        )
    _require_fresh_proof_identity(supplied, fresh)
    reserved_at = now_provider()
    _require_reservation_window(fresh, at_utc=reserved_at)
    if not isinstance(ledger, _PilotExactTaskPrReviewerRequestReservationLedger):
        raise PilotExactTaskPrReviewerRequestReservationError(
            "exact reviewer-request reservation ledger is required"
        )

    receipt = PilotExactTaskPrReviewerRequestReservationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        reservation_key_sha256=fresh.reviewer_request_nonce_sha256,
        supplied_authorization_proof_sha256=supplied.sha256,
        fresh_authorization_proof_sha256=fresh.sha256,
        authorization_sha256=fresh.authorization_sha256,
        authorization_signature_sha256=fresh.signature_sha256,
        reviewer_target_attestation_sha256=fresh.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=fresh.reviewer_handoff_requirements_sha256,
        ready_transaction_sha256=fresh.ready_transaction_sha256,
        predicted_commit_sha=fresh.predicted_commit_sha,
        reviewer_handoff_plan_sha256=fresh.reviewer_handoff_plan_sha256,
        reviewer_target_policy_sha256=fresh.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=fresh.authorization.reviewer_target_policy_epoch,
        reviewer_login=fresh.reviewer_login,
        reviewer_user_id=fresh.reviewer_user_id,
        ready_for_review_nonce_sha256=fresh.authorization.ready_for_review_nonce_sha256,
        reviewer_request_nonce_sha256=fresh.reviewer_request_nonce_sha256,
        repository=target.repository,
        pull_request_number=target.pull_request_number,
        pull_request_api_url=target.pull_request_api_url,
        pull_request_html_url=target.pull_request_html_url,
        pull_request_node_id_sha256=target.pull_request_node_id_sha256,
        base_branch=target.base_branch,
        head_branch=target.head_branch,
        fresh_verified_at_utc=fresh.verified_at_utc,
        reserved_at_utc=reserved_at,
    )
    path, payload = ledger.reserve(receipt)
    _mark_pr_reviewer_request_reservation_authenticated(
        receipt,
        target,
        path=path,
        payload=payload,
    )
    if receipt.reservation_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "reviewer-request reservation lost durable live provenance"
        )
    return receipt


def reserve_pilot_exact_task_pr_reviewer_request(
    authorization_proof: PilotExactTaskPrReviewerRequestAuthorizationProof,
    authorization_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskPrReviewerRequestReservationReceipt:
    """Freshly verify and consume one signed reviewer-request nonce."""
    supplied, target = _require_live_proof(authorization_proof)
    try:
        fresh = auth_boundary.verify_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target,
            authorization=supplied.authorization,
            signature=authorization_signature,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestReservationError(
            "fresh host-pinned ADR-DC-068 signature verification failed"
        ) from exc
    _require_fresh_proof_identity(supplied, fresh)
    ledger = _PilotExactTaskPrReviewerRequestReservationLedger(_canonical_ledger_root())
    return _reserve_verified_pilot_exact_task_pr_reviewer_request(
        supplied_authorization_proof=supplied,
        fresh_authorization_proof=fresh,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_RESERVATION_MAX_FRESH_PROOF_AGE_SECONDS",
    "PilotExactTaskPrReviewerRequestReservationError",
    "PilotExactTaskPrReviewerRequestReservationReceipt",
    "reserve_pilot_exact_task_pr_reviewer_request",
]
