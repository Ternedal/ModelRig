"""Replay-safe one-shot consumption model for ADR-DC-025.

This module consumes an already verified ADR-DC-024 pilot-start authorization
into host-local replay state and returns a receipt.  It deliberately does not
start a product pilot, execute a task, enable local commits, or grant any remote
publication/activation authority.

The public production facade installs the host-controlled ledger and performs
fresh upstream cryptographic verification.  The private seams here exist for
deterministic adversarial tests only.
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
from typing import Any, Callable, Mapping

from ._improvement_pilot_start_authorization_impl import (
    PilotStartAuthorizationProof,
)
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    unlink_durable,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_START_CONSUMPTION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-start-consumption-receipt/v1"
)
PILOT_START_CONSUMPTION_AUTHORITY = (
    "host-consumed-dc-l16-pilot-start-authorization-only"
)
PILOT_START_CONSUMPTION_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_ARTIFACT_BYTES = 512 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotStartConsumptionError(ValueError):
    """Pilot-start authorization could not be safely consumed."""


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
        raise PilotStartConsumptionError(
            "pilot-start consumption receipt is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotStartConsumptionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotStartConsumptionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotStartConsumptionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _safe_ledger_root(path: Path) -> Path:
    root = Path(path)
    if (
        not root.is_absolute()
        or not root.is_dir()
        or _has_linkish_component(root)
    ):
        raise PilotStartConsumptionError(
            "pilot-start consumption ledger must be an existing absolute link-free directory"
        )
    return root.resolve()


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.fspath(path))).hexdigest()


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


def _stable_proof_fields(proof: PilotStartAuthorizationProof) -> dict[str, Any]:
    if type(proof) is not PilotStartAuthorizationProof:
        raise PilotStartConsumptionError(
            "exact ADR-DC-024 PilotStartAuthorizationProof is required"
        )
    # Round-trip the complete proof before reading any authority-bearing fields.
    try:
        replayed = PilotStartAuthorizationProof.from_mapping(proof.to_dict())
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotStartConsumptionError(
            "ADR-DC-024 proof replay validation failed"
        ) from exc
    if replayed != proof:
        raise PilotStartConsumptionError("ADR-DC-024 proof replay identity mismatch")
    return {
        "authorization_sha256": proof.authorization_sha256,
        "signature_sha256": proof.signature_sha256,
        "key_id": proof.key_id,
        "issuer_actor_id": proof.issuer_actor_id,
        "issuer_system_id": proof.issuer_system_id,
        "authorization": proof.authorization,
        "preflight_proof_sha256": proof.preflight_proof_sha256,
        "attestation_sha256": proof.attestation_sha256,
        "packet_sha256": proof.packet_sha256,
        "selection_proof_sha256": proof.selection_proof_sha256,
        "candidate_proof_sha256": proof.candidate_proof_sha256,
        "requirements_sha256": proof.requirements_sha256,
        "trial_scope_sha256": proof.trial_scope_sha256,
        "start_nonce_sha256": proof.start_nonce_sha256,
        "one_shot_start_required": proof.one_shot_start_required,
        "start_consumed": proof.start_consumed,
        "integration_ready": proof.integration_ready,
        "pilot_start_authorized": proof.pilot_start_authorized,
        "product_pilot_started": proof.product_pilot_started,
        "local_commit_authorized": proof.local_commit_authorized,
        "remote_write_authorized": proof.remote_write_authorized,
        "push_authorized": proof.push_authorized,
        "pr_mutation_authorized": proof.pr_mutation_authorized,
        "merge_authorized": proof.merge_authorized,
        "release_authorized": proof.release_authorized,
        "deploy_authorized": proof.deploy_authorized,
        "production_activation_authorized": proof.production_activation_authorized,
        "authority": proof.authority,
    }


def require_fresh_proof_identity(
    supplied: PilotStartAuthorizationProof,
    fresh: PilotStartAuthorizationProof,
) -> None:
    """Require fresh verification to reproduce all stable ADR-DC-024 semantics.

    ``verified_at_utc`` is intentionally excluded: a fresh cryptographic
    verification has a new verification timestamp while the signed authorization
    identity and authority semantics must remain byte/field identical.
    """

    supplied_fields = _stable_proof_fields(supplied)
    fresh_fields = _stable_proof_fields(fresh)
    for name, expected in supplied_fields.items():
        if fresh_fields[name] != expected:
            raise PilotStartConsumptionError(
                f"fresh ADR-DC-024 proof identity mismatch: {name}"
            )


_RECEIPT_FIELDS = {
    "schema",
    "ledger_scope",
    "ledger_root_path_sha256",
    "authorization_proof",
    "authorization_proof_sha256",
    "fresh_authorization_proof_sha256",
    "authorization_sha256",
    "authorization_signature_sha256",
    "preflight_signature_sha256",
    "start_nonce_sha256",
    "fresh_verified_at_utc",
    "consumed_at_utc",
    "host_replay_guard_committed",
    "global_replay_safe",
    "one_shot_start_required",
    "start_consumed",
    "start_receipt_issued",
    "pilot_start_authorized",
    "task_execution_authorized",
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
class PilotStartConsumptionReceipt:
    ledger_root_path_sha256: str
    authorization_proof: PilotStartAuthorizationProof
    authorization_proof_sha256: str
    fresh_authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    preflight_signature_sha256: str
    start_nonce_sha256: str
    fresh_verified_at_utc: str
    consumed_at_utc: str
    ledger_scope: str = PILOT_START_CONSUMPTION_LEDGER_SCOPE
    host_replay_guard_committed: bool = True
    global_replay_safe: bool = False
    one_shot_start_required: bool = True
    start_consumed: bool = True
    start_receipt_issued: bool = True
    pilot_start_authorized: bool = True
    task_execution_authorized: bool = False
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
    authority: str = PILOT_START_CONSUMPTION_AUTHORITY
    schema: str = PILOT_START_CONSUMPTION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
            or self.ledger_scope != PILOT_START_CONSUMPTION_LEDGER_SCOPE
        ):
            raise PilotStartConsumptionError(
                "pilot-start consumption receipt schema/ledger scope is unsupported"
            )
        if type(self.authorization_proof) is not PilotStartAuthorizationProof:
            raise PilotStartConsumptionError("exact ADR-DC-024 proof is required")
        replayed = PilotStartAuthorizationProof.from_mapping(
            self.authorization_proof.to_dict()
        )
        if replayed != self.authorization_proof:
            raise PilotStartConsumptionError(
                "pilot-start consumption proof replay identity mismatch"
            )
        for name, value in (
            ("ledger_root_path_sha256", self.ledger_root_path_sha256),
            ("authorization_proof_sha256", self.authorization_proof_sha256),
            ("fresh_authorization_proof_sha256", self.fresh_authorization_proof_sha256),
            ("authorization_sha256", self.authorization_sha256),
            ("authorization_signature_sha256", self.authorization_signature_sha256),
            ("preflight_signature_sha256", self.preflight_signature_sha256),
            ("start_nonce_sha256", self.start_nonce_sha256),
        ):
            _hex64(value, name=name)
        if self.authorization_proof_sha256 != self.authorization_proof.sha256:
            raise PilotStartConsumptionError(
                "pilot-start consumption supplied proof hash mismatch"
            )
        if self.authorization_sha256 != self.authorization_proof.authorization_sha256:
            raise PilotStartConsumptionError(
                "pilot-start consumption authorization hash mismatch"
            )
        if (
            self.authorization_signature_sha256
            != self.authorization_proof.signature_sha256
        ):
            raise PilotStartConsumptionError(
                "pilot-start consumption human signature hash mismatch"
            )
        if self.start_nonce_sha256 != self.authorization_proof.start_nonce_sha256:
            raise PilotStartConsumptionError(
                "pilot-start consumption nonce binding mismatch"
            )
        fresh_verified = _utc(
            self.fresh_verified_at_utc,
            name="fresh_verified_at_utc",
        )
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        expires = _utc(
            self.authorization_proof.authorization.expires_at_utc,
            name="expires_at_utc",
        )
        if consumed < fresh_verified or consumed > expires:
            raise PilotStartConsumptionError(
                "pilot-start authorization was not consumed inside its fresh validity window"
            )
        if (
            self.host_replay_guard_committed is not True
            or self.global_replay_safe is not False
            or self.one_shot_start_required is not True
            or self.start_consumed is not True
            or self.start_receipt_issued is not True
            or self.pilot_start_authorized is not True
            or self.task_execution_authorized is not False
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
            or self.authority != PILOT_START_CONSUMPTION_AUTHORITY
        ):
            raise PilotStartConsumptionError(
                "pilot-start consumption receipt authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotStartConsumptionReceipt":
        if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
            raise PilotStartConsumptionError(
                "pilot-start consumption receipt fields mismatch"
            )
        data = dict(value)
        proof = data.get("authorization_proof")
        if not isinstance(proof, Mapping):
            raise PilotStartConsumptionError(
                "pilot-start consumption authorization proof must be an object"
            )
        data["authorization_proof"] = PilotStartAuthorizationProof.from_mapping(proof)
        return cls(**data)

    @property
    def transaction_authenticated(self) -> bool:
        """Live transaction provenance; omitted from serialized receipt state."""
        return _is_transaction_authenticated(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ledger_scope": self.ledger_scope,
            "ledger_root_path_sha256": self.ledger_root_path_sha256,
            "authorization_proof": self.authorization_proof.to_dict(),
            "authorization_proof_sha256": self.authorization_proof_sha256,
            "fresh_authorization_proof_sha256": self.fresh_authorization_proof_sha256,
            "authorization_sha256": self.authorization_sha256,
            "authorization_signature_sha256": self.authorization_signature_sha256,
            "preflight_signature_sha256": self.preflight_signature_sha256,
            "start_nonce_sha256": self.start_nonce_sha256,
            "fresh_verified_at_utc": self.fresh_verified_at_utc,
            "consumed_at_utc": self.consumed_at_utc,
            "host_replay_guard_committed": self.host_replay_guard_committed,
            "global_replay_safe": self.global_replay_safe,
            "one_shot_start_required": self.one_shot_start_required,
            "start_consumed": self.start_consumed,
            "start_receipt_issued": self.start_receipt_issued,
            "pilot_start_authorized": self.pilot_start_authorized,
            "task_execution_authorized": self.task_execution_authorized,
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


class _PilotStartConsumptionLedger:
    """Private create-once host-local replay state keyed by signed start nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, nonce: str) -> tuple[Path, Path, Path]:
        digest = _hex64(nonce, name="start_nonce_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def _lock_payload(
        self,
        *,
        nonce: str,
        authorization_sha256: str,
        signature_sha256: str,
    ) -> bytes:
        return _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-pilot-start-consumption-lock/v1",
                "ledger_scope": PILOT_START_CONSUMPTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "start_nonce_sha256": _hex64(nonce, name="start_nonce_sha256"),
                "authorization_sha256": _hex64(
                    authorization_sha256, name="authorization_sha256"
                ),
                "authorization_signature_sha256": _hex64(
                    signature_sha256, name="authorization_signature_sha256"
                ),
            }
        ).encode("utf-8")

    def acquire(
        self,
        *,
        nonce: str,
        authorization_sha256: str,
        signature_sha256: str,
    ) -> bytes:
        final, pending, lock = self._paths(nonce)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotStartConsumptionError(
                "pilot-start authorization nonce was already consumed or requires recovery"
            )
        marker = self._lock_payload(
            nonce=nonce,
            authorization_sha256=authorization_sha256,
            signature_sha256=signature_sha256,
        )
        try:
            create_once_file(lock, marker)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotStartConsumptionError(
                "pilot-start authorization could not be durably reserved"
            ) from exc
        return marker

    def commit(
        self,
        *,
        receipt: PilotStartConsumptionReceipt,
        lock_payload: bytes,
    ) -> PilotStartConsumptionReceipt:
        final, pending, lock = self._paths(receipt.start_nonce_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotStartConsumptionError(
                "pilot-start replay marker changed before receipt commit"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PilotStartConsumptionError(
                "pilot-start consumption receipt state already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotStartConsumptionError(
                "pilot-start consumption receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            observed = _read_bound_file(final)
            if observed != payload:
                raise PilotStartConsumptionError(
                    "pilot-start consumption receipt read-back mismatch"
                )
            parsed = PilotStartConsumptionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotStartConsumptionError(
                    "pilot-start consumption receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotStartConsumptionError(
                    "pilot-start replay marker changed before provenance registration"
                )
            _mark_transaction_authenticated(
                parsed,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.transaction_authenticated is not True:
                raise PilotStartConsumptionError(
                    "pilot-start consumption lost live transaction provenance"
                )
            return parsed
        except Exception as exc:
            raise PilotStartConsumptionError(
                "pilot-start authorization is durably consumed but receipt requires recovery"
            ) from exc


def _consume_verified_pilot_start_authorization(
    *,
    supplied_proof: PilotStartAuthorizationProof,
    fresh_proof: PilotStartAuthorizationProof,
    preflight_signature_sha256: str,
    ledger: _PilotStartConsumptionLedger,
    now_provider: Callable[[], str],
) -> PilotStartConsumptionReceipt:
    """Consume one freshly reverified authorization; deterministic test seam."""

    if type(ledger) is not _PilotStartConsumptionLedger:
        raise PilotStartConsumptionError(
            "exact pilot-start consumption ledger is required"
        )
    require_fresh_proof_identity(supplied_proof, fresh_proof)
    preflight_signature_digest = _hex64(
        preflight_signature_sha256,
        name="preflight_signature_sha256",
    )
    consumed_at = now_provider()
    consumed = _utc(consumed_at, name="consumed_at_utc")
    fresh_verified = _utc(fresh_proof.verified_at_utc, name="fresh verified time")
    expires = _utc(
        supplied_proof.authorization.expires_at_utc,
        name="authorization expiry",
    )
    if consumed < fresh_verified or consumed > expires:
        raise PilotStartConsumptionError(
            "pilot-start authorization is stale at consume time"
        )

    marker = ledger.acquire(
        nonce=supplied_proof.start_nonce_sha256,
        authorization_sha256=supplied_proof.authorization_sha256,
        signature_sha256=supplied_proof.signature_sha256,
    )

    # Re-check time after the irreversible one-shot marker exists.  A boundary
    # crossing here fails closed and leaves recovery state rather than reviving
    # the authorization.
    committed_at = now_provider()
    committed = _utc(committed_at, name="consumed_at_utc")
    if committed < fresh_verified or committed > expires:
        raise PilotStartConsumptionError(
            "pilot-start authorization expired after durable consume reservation"
        )

    receipt = PilotStartConsumptionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        authorization_proof=supplied_proof,
        authorization_proof_sha256=supplied_proof.sha256,
        fresh_authorization_proof_sha256=fresh_proof.sha256,
        authorization_sha256=supplied_proof.authorization_sha256,
        authorization_signature_sha256=supplied_proof.signature_sha256,
        preflight_signature_sha256=preflight_signature_digest,
        start_nonce_sha256=supplied_proof.start_nonce_sha256,
        fresh_verified_at_utc=fresh_proof.verified_at_utc,
        consumed_at_utc=committed_at,
    )
    return ledger.commit(receipt=receipt, lock_payload=marker)


def consume_pilot_start_authorization(
    *,
    authorization_proof: PilotStartAuthorizationProof,
    preflight_signature: Any,
    authorization_signature: Any,
) -> PilotStartConsumptionReceipt:
    """Production facade replaces this compatibility surface at import time."""
    raise PilotStartConsumptionError(
        "pilot-start consumption is unavailable outside the production facade"
    )


__all__ = [
    "PILOT_START_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_START_CONSUMPTION_AUTHORITY",
    "PILOT_START_CONSUMPTION_LEDGER_SCOPE",
    "PilotStartConsumptionError",
    "PilotStartConsumptionReceipt",
    "consume_pilot_start_authorization",
]
