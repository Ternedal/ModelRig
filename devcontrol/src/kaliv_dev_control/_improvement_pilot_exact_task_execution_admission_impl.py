"""Replay-safe admission for one exact ADR-DC-032-authorized task execution.

ADR-DC-033 is the first boundary allowed to consume the human-signed execution
nonce and issue a live one-shot task-execution admission.  It does not execute a
task.  The durable receipt is historical evidence; only the exact receipt object
returned by the successful host-local transaction carries process-local
transaction provenance for a later, separate executor-consumption boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ._improvement_pilot_start_consumption_impl import (
    _path_sha256,
    _safe_ledger_root,
)
from .durable_publication import DurablePublicationError, create_once_file, unlink_durable
from .improvement_pilot_exact_task_execution_revalidation_attestation import (
    PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY,
    PilotExactTaskExecutionRevalidationAttestationProof,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-execution-admission-receipt/v1"
)
PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY = (
    "host-admitted-one-dc-l16-exact-task-execution-only"
)
PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE = "canonical-host-local-v1"
PILOT_EXACT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS = 300
_MAX_ARTIFACT_BYTES = 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_RECEIPT_FIELDS = {
    "schema",
    "ledger_scope",
    "ledger_root_path_sha256",
    "admission_key_sha256",
    "revalidation_attestation_proof",
    "revalidation_attestation_proof_sha256",
    "revalidation_attestation_sha256",
    "revalidation_attestation_signature_sha256",
    "packet_sha256",
    "execution_authorization_proof_sha256",
    "execution_authorization_signature_sha256",
    "admission_attestation_proof_sha256",
    "admission_attestation_signature_sha256",
    "start_receipt_sha256",
    "execution_nonce_sha256",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed_by_human_scope",
    "fresh_verified_at_utc",
    "admitted_at_utc",
    "host_replay_guard_committed",
    "execution_authorization_consumed",
    "one_shot_execution_required",
    "task_execution_admission_observed",
    "task_execution_authorized",
    "task_execution_started",
    "execution_consumed",
    "integration_ready",
    "product_pilot_started",
    "local_commit_authorized",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
    "authority",
}


class PilotExactTaskExecutionAdmissionError(ValueError):
    """Exact-task execution admission is stale, replayed or unsafe."""


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
        raise PilotExactTaskExecutionAdmissionError(
            "exact-task execution admission is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotExactTaskExecutionAdmissionError(f"{name} is invalid")
    if value == "0" * 64:
        raise PilotExactTaskExecutionAdmissionError(f"{name} must not be a placeholder")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskExecutionAdmissionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskExecutionAdmissionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskExecutionAdmissionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _read_bound_file(path: Path) -> bytes | None:
    """Read one ADR-DC-033 artifact using this boundary's own byte budget."""
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


def _require_satisfied_revalidation_proof(
    value: Any,
) -> PilotExactTaskExecutionRevalidationAttestationProof:
    if type(value) is not PilotExactTaskExecutionRevalidationAttestationProof:
        raise PilotExactTaskExecutionAdmissionError(
            "exact ADR-DC-032 PilotExactTaskExecutionRevalidationAttestationProof is required"
        )
    try:
        replayed = PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskExecutionAdmissionError(
            "ADR-DC-032 proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskExecutionAdmissionError(
            "ADR-DC-032 proof replay identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_PROOF_AUTHORITY
        or value.host_attestation_verified is not True
        or value.execution_revalidation_observed is not True
        or value.execution_revalidation_satisfied is not True
        or value.task_execution_admission_observed is not False
        or value.task_execution_authorized is not False
        or value.task_execution_started is not False
        or value.integration_ready is not False
        or value.product_pilot_started is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskExecutionAdmissionError(
            "execution admission requires one fully satisfied inert ADR-DC-032 proof"
        )
    return value


def _stable_proof_fields(
    proof: PilotExactTaskExecutionRevalidationAttestationProof,
) -> dict[str, Any]:
    exact = _require_satisfied_revalidation_proof(proof)
    return {
        "attestation_sha256": exact.attestation_sha256,
        "signature_sha256": exact.signature_sha256,
        "key_id": exact.key_id,
        "issuer_actor_id": exact.issuer_actor_id,
        "issuer_system_id": exact.issuer_system_id,
        "attestation": exact.attestation,
        "packet_sha256": exact.packet_sha256,
        "execution_authorization_proof_sha256": exact.execution_authorization_proof_sha256,
        "execution_authorization_signature_sha256": exact.execution_authorization_signature_sha256,
        "admission_attestation_proof_sha256": exact.admission_attestation_proof_sha256,
        "admission_attestation_signature_sha256": exact.admission_attestation_signature_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "host_attestation_verified": exact.host_attestation_verified,
        "execution_revalidation_observed": exact.execution_revalidation_observed,
        "execution_revalidation_satisfied": exact.execution_revalidation_satisfied,
        "task_execution_admission_observed": exact.task_execution_admission_observed,
        "task_execution_authorized": exact.task_execution_authorized,
        "task_execution_started": exact.task_execution_started,
        "integration_ready": exact.integration_ready,
        "product_pilot_started": exact.product_pilot_started,
        "local_commit_authorized": exact.local_commit_authorized,
        "remote_write_authorized": exact.remote_write_authorized,
        "push_authorized": exact.push_authorized,
        "pr_mutation_authorized": exact.pr_mutation_authorized,
        "merge_authorized": exact.merge_authorized,
        "release_authorized": exact.release_authorized,
        "deploy_authorized": exact.deploy_authorized,
        "production_activation_authorized": exact.production_activation_authorized,
        "authority": exact.authority,
    }


def require_fresh_revalidation_proof_identity(
    supplied: PilotExactTaskExecutionRevalidationAttestationProof,
    fresh: PilotExactTaskExecutionRevalidationAttestationProof,
) -> None:
    """Fresh production verification must reproduce every stable ADR-DC-032 semantic."""
    if _stable_proof_fields(supplied) != _stable_proof_fields(fresh):
        raise PilotExactTaskExecutionAdmissionError(
            "fresh ADR-DC-032 proof identity does not match supplied proof"
        )


def _scope(
    proof: PilotExactTaskExecutionRevalidationAttestationProof,
) -> dict[str, Any]:
    exact = _require_satisfied_revalidation_proof(proof)
    packet = exact.attestation.packet
    return {
        "packet_sha256": exact.packet_sha256,
        "execution_authorization_proof_sha256": (
            exact.execution_authorization_proof_sha256
        ),
        "execution_authorization_signature_sha256": (
            exact.execution_authorization_signature_sha256
        ),
        "admission_attestation_proof_sha256": exact.admission_attestation_proof_sha256,
        "admission_attestation_signature_sha256": (
            exact.admission_attestation_signature_sha256
        ),
        "start_receipt_sha256": packet.start_receipt_sha256,
        "execution_nonce_sha256": exact.execution_nonce_sha256,
        "selected_pilot_task_id": packet.selected_pilot_task_id,
        "workspace_root_path_sha256": packet.workspace_root_path_sha256,
        "local_commits_allowed_by_human_scope": (
            packet.local_commits_allowed_by_human_scope
        ),
    }


def _admission_key(
    proof: PilotExactTaskExecutionRevalidationAttestationProof,
) -> str:
    """Use the human-signed execution nonce itself as the create-once replay key.

    The nonce is the one-shot identity from ADR-DC-030.  Keying the ledger only
    by a larger authorization/task composite would allow the same signed nonce
    to acquire another slot after a separately issued authorization changed one
    of those surrounding identities.  Scope is still bound in the durable lock
    and receipt, but the nonce can be admitted at most once per canonical host
    ledger regardless of re-attestation or re-authorization.
    """
    exact = _require_satisfied_revalidation_proof(proof)
    return _hex64(exact.execution_nonce_sha256, name="execution_nonce_sha256")


def _transaction_registry():
    references: dict[
        int,
        tuple[int, str, Path, bytes, Path, bytes, weakref.ReferenceType[Any]],
    ] = {}

    def mark(
        value: Any,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        key = id(value)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            references.pop(key, None)

        references[key] = (
            os.getpid(),
            value.sha256,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            weakref.ref(value, cleanup),
        )

    def contains(value: Any) -> bool:
        entry = references.get(id(value))
        if entry is None:
            return False
        pid, digest, final_path, final_payload, lock_path, lock_payload, ref = entry
        if pid != os.getpid() or ref() is not value:
            return False
        try:
            if value.sha256 != digest:
                return False
        except (AttributeError, TypeError, ValueError):
            return False
        return (
            _read_bound_file(final_path) == final_payload
            and _read_bound_file(lock_path) == lock_payload
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=references.clear)
    return mark, contains


_mark_transaction_authenticated, _is_transaction_authenticated = _transaction_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskExecutionAdmissionReceipt:
    ledger_root_path_sha256: str
    admission_key_sha256: str
    revalidation_attestation_proof: PilotExactTaskExecutionRevalidationAttestationProof
    revalidation_attestation_proof_sha256: str
    revalidation_attestation_sha256: str
    revalidation_attestation_signature_sha256: str
    packet_sha256: str
    execution_authorization_proof_sha256: str
    execution_authorization_signature_sha256: str
    admission_attestation_proof_sha256: str
    admission_attestation_signature_sha256: str
    start_receipt_sha256: str
    execution_nonce_sha256: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed_by_human_scope: bool
    fresh_verified_at_utc: str
    admitted_at_utc: str
    ledger_scope: str = PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
    host_replay_guard_committed: bool = True
    execution_authorization_consumed: bool = True
    one_shot_execution_required: bool = True
    task_execution_admission_observed: bool = True
    task_execution_authorized: bool = True
    task_execution_started: bool = False
    execution_consumed: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA
            or self.ledger_scope != PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
        ):
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task admission receipt schema/ledger scope is unsupported"
            )
        proof = _require_satisfied_revalidation_proof(
            self.revalidation_attestation_proof
        )
        for name in (
            "ledger_root_path_sha256",
            "admission_key_sha256",
            "revalidation_attestation_proof_sha256",
            "revalidation_attestation_sha256",
            "revalidation_attestation_signature_sha256",
            "packet_sha256",
            "execution_authorization_proof_sha256",
            "execution_authorization_signature_sha256",
            "admission_attestation_proof_sha256",
            "admission_attestation_signature_sha256",
            "start_receipt_sha256",
            "execution_nonce_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _identifier(self.selected_pilot_task_id, name="selected_pilot_task_id")
        if type(self.local_commits_allowed_by_human_scope) is not bool:
            raise PilotExactTaskExecutionAdmissionError(
                "local_commits_allowed_by_human_scope must be boolean"
            )
        scope = _scope(proof)
        expected = {
            "admission_key_sha256": _admission_key(proof),
            "revalidation_attestation_proof_sha256": proof.sha256,
            "revalidation_attestation_sha256": proof.attestation_sha256,
            "revalidation_attestation_signature_sha256": proof.signature_sha256,
            **scope,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskExecutionAdmissionError(
                f"exact-task admission binding mismatch: {mismatch}"
            )
        fresh_verified = _utc(self.fresh_verified_at_utc, name="fresh_verified_at_utc")
        admitted = _utc(self.admitted_at_utc, name="admitted_at_utc")
        attested = _utc(proof.attestation.attested_at_utc, name="attested_at_utc")
        expires = _utc(
            proof.attestation.packet.execution_authorization_proof.authorization.expires_at_utc,
            name="execution authorization expires_at_utc",
        )
        if admitted < fresh_verified:
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task admission predates fresh ADR-DC-032 verification"
            )
        if admitted < attested or admitted > min(
            expires,
            attested + timedelta(seconds=PILOT_EXACT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS),
        ):
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task admission is outside the fresh authorization window"
            )
        if (
            self.host_replay_guard_committed is not True
            or self.execution_authorization_consumed is not True
            or self.one_shot_execution_required is not True
            or self.task_execution_admission_observed is not True
            or self.task_execution_authorized is not True
            or self.task_execution_started is not False
            or self.execution_consumed is not False
            or self.integration_ready is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
        ):
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task admission receipt authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskExecutionAdmissionReceipt":
        if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task admission receipt fields mismatch"
            )
        data = dict(value)
        proof = data.get("revalidation_attestation_proof")
        if not isinstance(proof, Mapping):
            raise PilotExactTaskExecutionAdmissionError(
                "revalidation attestation proof must be an object"
            )
        data["revalidation_attestation_proof"] = (
            PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(proof)
        )
        return cls(**data)

    @property
    def transaction_authenticated(self) -> bool:
        """Live process-local authority; intentionally absent from serialized state."""
        return _is_transaction_authenticated(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ledger_scope": self.ledger_scope,
            "ledger_root_path_sha256": self.ledger_root_path_sha256,
            "admission_key_sha256": self.admission_key_sha256,
            "revalidation_attestation_proof": self.revalidation_attestation_proof.to_dict(),
            "revalidation_attestation_proof_sha256": self.revalidation_attestation_proof_sha256,
            "revalidation_attestation_sha256": self.revalidation_attestation_sha256,
            "revalidation_attestation_signature_sha256": self.revalidation_attestation_signature_sha256,
            "packet_sha256": self.packet_sha256,
            "execution_authorization_proof_sha256": self.execution_authorization_proof_sha256,
            "execution_authorization_signature_sha256": self.execution_authorization_signature_sha256,
            "admission_attestation_proof_sha256": self.admission_attestation_proof_sha256,
            "admission_attestation_signature_sha256": self.admission_attestation_signature_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "selected_pilot_task_id": self.selected_pilot_task_id,
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed_by_human_scope": self.local_commits_allowed_by_human_scope,
            "fresh_verified_at_utc": self.fresh_verified_at_utc,
            "admitted_at_utc": self.admitted_at_utc,
            "host_replay_guard_committed": self.host_replay_guard_committed,
            "execution_authorization_consumed": self.execution_authorization_consumed,
            "one_shot_execution_required": self.one_shot_execution_required,
            "task_execution_admission_observed": self.task_execution_admission_observed,
            "task_execution_authorized": self.task_execution_authorized,
            "task_execution_started": self.task_execution_started,
            "execution_consumed": self.execution_consumed,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "local_commit_authorized": self.local_commit_authorized,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class _PilotExactTaskExecutionAdmissionLedger:
    """Private create-once replay ledger keyed by the signed execution nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="admission_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def acquire(
        self,
        *,
        proof: PilotExactTaskExecutionRevalidationAttestationProof,
    ) -> bytes:
        key = _admission_key(proof)
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskExecutionAdmissionError(
                "exact execution nonce was already admitted or requires recovery"
            )
        scope = _scope(proof)
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-execution-admission-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "admission_key_sha256": key,
                "execution_authorization_proof_sha256": scope[
                    "execution_authorization_proof_sha256"
                ],
                "start_receipt_sha256": scope["start_receipt_sha256"],
                "execution_nonce_sha256": scope["execution_nonce_sha256"],
                "selected_pilot_task_id": scope["selected_pilot_task_id"],
                "workspace_root_path_sha256": scope["workspace_root_path_sha256"],
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task execution admission could not be durably reserved"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskExecutionAdmissionReceipt,
        lock_payload: bytes,
    ) -> PilotExactTaskExecutionAdmissionReceipt:
        final, pending, lock = self._paths(receipt.admission_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task execution admission marker changed before commit"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task execution admission receipt state already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task execution admission receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskExecutionAdmissionError(
                    "exact-task execution admission receipt read-back mismatch"
                )
            parsed = PilotExactTaskExecutionAdmissionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskExecutionAdmissionError(
                    "exact-task execution admission receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskExecutionAdmissionError(
                    "exact-task execution admission marker changed before provenance registration"
                )
            _mark_transaction_authenticated(
                parsed,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.transaction_authenticated is not True:
                raise PilotExactTaskExecutionAdmissionError(
                    "exact-task execution admission lost live transaction provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskExecutionAdmissionError):
                raise
            raise PilotExactTaskExecutionAdmissionError(
                "exact-task execution admission is reserved but receipt requires recovery"
            ) from exc


def _admit_verified_exact_task_execution(
    *,
    supplied_proof: PilotExactTaskExecutionRevalidationAttestationProof,
    fresh_proof: PilotExactTaskExecutionRevalidationAttestationProof,
    ledger: _PilotExactTaskExecutionAdmissionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskExecutionAdmissionReceipt:
    if type(ledger) is not _PilotExactTaskExecutionAdmissionLedger:
        raise PilotExactTaskExecutionAdmissionError(
            "exact-task execution admission ledger is required"
        )
    require_fresh_revalidation_proof_identity(supplied_proof, fresh_proof)
    scope = _scope(supplied_proof)
    fresh_verified = _utc(fresh_proof.verified_at_utc, name="fresh verified time")
    attested = _utc(supplied_proof.attestation.attested_at_utc, name="attested_at_utc")
    expires = _utc(
        supplied_proof.attestation.packet.execution_authorization_proof.authorization.expires_at_utc,
        name="execution authorization expires_at_utc",
    )
    deadline = min(
        expires,
        attested + timedelta(seconds=PILOT_EXACT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS),
    )
    admitted_at = now_provider()
    admitted = _utc(admitted_at, name="admitted_at_utc")
    if admitted < fresh_verified or admitted < attested or admitted > deadline:
        raise PilotExactTaskExecutionAdmissionError(
            "exact-task execution admission proof is stale at reservation time"
        )

    marker = ledger.acquire(proof=supplied_proof)

    committed_at = now_provider()
    committed = _utc(committed_at, name="admitted_at_utc")
    if committed < fresh_verified or committed < attested or committed > deadline:
        raise PilotExactTaskExecutionAdmissionError(
            "exact-task execution admission became stale after durable reservation"
        )

    receipt = PilotExactTaskExecutionAdmissionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        admission_key_sha256=_admission_key(supplied_proof),
        revalidation_attestation_proof=supplied_proof,
        revalidation_attestation_proof_sha256=supplied_proof.sha256,
        revalidation_attestation_sha256=supplied_proof.attestation_sha256,
        revalidation_attestation_signature_sha256=supplied_proof.signature_sha256,
        packet_sha256=scope["packet_sha256"],
        execution_authorization_proof_sha256=scope[
            "execution_authorization_proof_sha256"
        ],
        execution_authorization_signature_sha256=scope[
            "execution_authorization_signature_sha256"
        ],
        admission_attestation_proof_sha256=scope[
            "admission_attestation_proof_sha256"
        ],
        admission_attestation_signature_sha256=scope[
            "admission_attestation_signature_sha256"
        ],
        start_receipt_sha256=scope["start_receipt_sha256"],
        execution_nonce_sha256=scope["execution_nonce_sha256"],
        selected_pilot_task_id=scope["selected_pilot_task_id"],
        workspace_root_path_sha256=scope["workspace_root_path_sha256"],
        local_commits_allowed_by_human_scope=scope[
            "local_commits_allowed_by_human_scope"
        ],
        fresh_verified_at_utc=fresh_proof.verified_at_utc,
        admitted_at_utc=committed_at,
    )
    return ledger.commit(receipt=receipt, lock_payload=marker)


def admit_pilot_exact_task_execution(
    *,
    revalidation_attestation_proof: PilotExactTaskExecutionRevalidationAttestationProof,
    revalidation_attestation_signature: Any,
    execution_authorization_signature: Any,
    admission_attestation_signature: Any,
) -> PilotExactTaskExecutionAdmissionReceipt:
    """Production facade replaces this compatibility surface at import time."""
    del (
        revalidation_attestation_proof,
        revalidation_attestation_signature,
        execution_authorization_signature,
        admission_attestation_signature,
    )
    raise PilotExactTaskExecutionAdmissionError(
        "exact-task execution admission is unavailable outside the production facade"
    )


__all__ = [
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY",
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_EXECUTION_ADMISSION_MAX_AGE_SECONDS",
    "PilotExactTaskExecutionAdmissionError",
    "PilotExactTaskExecutionAdmissionReceipt",
    "admit_pilot_exact_task_execution",
]
