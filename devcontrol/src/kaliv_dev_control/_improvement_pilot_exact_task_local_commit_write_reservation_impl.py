"""ADR-DC-045 replay-safe reservation implementation for one exact local commit write.

Private implementation/test seam. The public facade host-pins fresh ADR-DC-044
signature verification before entering the reservation transaction.
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
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .durable_publication import DurablePublicationError, create_once_file, unlink_durable
from .improvement_pilot_exact_task_local_commit_authorization import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY,
    PilotExactTaskLocalCommitAuthorizationProof,
)
from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY,
    PilotExactTaskLocalCommitObjectIdentity,
)
from . import improvement_pilot_exact_task_local_commit_write_requirements as requirements_boundary
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-write-reservation-receipt/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY = (
    "host-reserved-one-dc-l16-exact-local-commit-write-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-local-commit-write-reservation-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-local-commit-write-reservation-ledger-v1"
)


class PilotExactTaskLocalCommitWriteReservationError(ValueError):
    """The exact local-write reservation is replayed, drifted, or unsafe."""


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
        raise PilotExactTaskLocalCommitWriteReservationError(
            "local-write reservation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskLocalCommitWriteReservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskLocalCommitWriteReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitWriteReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskLocalCommitWriteReservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _require_authorization_proof(value: Any) -> PilotExactTaskLocalCommitAuthorizationProof:
    if type(value) is not PilotExactTaskLocalCommitAuthorizationProof:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "exact ADR-DC-044 local commit authorization proof is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitAuthorizationProof.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "ADR-DC-044 authorization proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "ADR-DC-044 authorization proof identity mismatch"
        )
    authorization = value.authorization
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_PROOF_AUTHORITY
        or value.human_local_commit_authorization_verified is not True
        or value.one_shot_local_write_required is not True
        or value.local_write_authorization_consumed is not False
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.local_commit_created is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.local_write_nonce_sha256 == value.execution_nonce_sha256
        or authorization.local_write_nonce_sha256 != value.local_write_nonce_sha256
        or authorization.local_commit_object_identity_sha256
        != value.local_commit_object_identity_sha256
        or authorization.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitWriteReservationError(
            "local-write reservation requires one inert verified ADR-DC-044 proof"
        )
    return value


def require_fresh_authorization_proof_identity(
    supplied: PilotExactTaskLocalCommitAuthorizationProof,
    fresh: PilotExactTaskLocalCommitAuthorizationProof,
) -> None:
    """Fresh signature verification must reproduce every stable ADR-DC-044 semantic."""
    left = _require_authorization_proof(supplied).to_dict()
    right = _require_authorization_proof(fresh).to_dict()
    left.pop("verified_at_utc")
    right.pop("verified_at_utc")
    if left != right:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "fresh ADR-DC-044 proof identity does not match supplied proof"
        )


def _require_live_identity(value: Any) -> PilotExactTaskLocalCommitObjectIdentity:
    if type(value) is not PilotExactTaskLocalCommitObjectIdentity:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "exact live ADR-DC-042 local commit object identity is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitObjectIdentity.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "ADR-DC-042 identity replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitWriteReservationError("ADR-DC-042 identity replay mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY
        or value.identity_authenticated is not True
        or value.local_commit_plan_authenticated is not True
        or value.fresh_workspace_snapshot_matched is not True
        or value.index_manifest_bound is not True
        or value.root_tree_identity_materialized is not True
        or value.commit_object_identity_materialized is not True
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.local_commit_created is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitWriteReservationError(
            "reservation requires one live inert ADR-DC-042 identity"
        )
    return value


def _require_proof_identity_binding(
    proof: PilotExactTaskLocalCommitAuthorizationProof,
    identity: PilotExactTaskLocalCommitObjectIdentity,
) -> None:
    requirements = proof.authorization.local_commit_write_requirements
    if (
        proof.local_commit_object_identity_sha256 != identity.sha256
        or requirements.local_commit_object_identity_sha256 != identity.sha256
        or requirements.local_commit_plan_sha256 != identity.local_commit_plan_sha256
        or requirements.post_execution_evaluation_sha256 != identity.post_execution_evaluation_sha256
        or requirements.execution_transaction_sha256 != identity.execution_transaction_sha256
        or requirements.tier_a_receipt_sha256 != identity.tier_a_receipt_sha256
        or requirements.execution_nonce_sha256 != identity.execution_nonce_sha256
        or requirements.development_task_sha256 != identity.development_task_sha256
        or requirements.task_id != identity.task_id
        or requirements.repository != identity.repository
        or requirements.base_sha != identity.base_sha
        or requirements.candidate_patch_sha256 != identity.candidate_patch_sha256
        or requirements.candidate_numstat_sha256 != identity.candidate_numstat_sha256
        or requirements.scope_policy_sha256 != identity.scope_policy_sha256
        or requirements.index_manifest_sha256 != identity.index_manifest_sha256
        or requirements.root_tree_sha != identity.root_tree_sha
        or requirements.commit_payload_sha256 != identity.commit_payload_sha256
        or requirements.predicted_commit_sha != identity.predicted_commit_sha
        or requirements.commit_subject_sha256 != identity.commit_subject_sha256
        or proof.predicted_commit_sha != identity.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitWriteReservationError(
            "ADR-DC-044 proof is not bound to the exact live ADR-DC-042 identity"
        )
    try:
        rematerialized = requirements_boundary.materialize_pilot_exact_task_local_commit_write_requirements(
            identity
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "live ADR-DC-043 requirements re-materialization failed"
        ) from exc
    if rematerialized != requirements or rematerialized.sha256 != proof.local_commit_write_requirements_sha256:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "ADR-DC-044 proof requirements no longer match live ADR-DC-042 provenance"
        )


def _fresh_identity_revalidation(
    identity: PilotExactTaskLocalCommitObjectIdentity,
) -> Mapping[str, Any]:
    inputs = identity_boundary._get_live_local_commit_object_identity_inputs(identity)
    if inputs is None:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "ADR-DC-042 live identity inputs are unavailable"
        )
    plan = inputs.get("local_commit_plan")
    if plan is None or getattr(plan, "sha256", None) != identity.local_commit_plan_sha256:
        raise PilotExactTaskLocalCommitWriteReservationError("ADR-DC-042 live plan provenance changed")
    try:
        snapshot = identity_boundary._fresh_workspace_snapshot(inputs)
        identity_boundary._require_snapshot_matches_plan(plan, snapshot)
        object_format = identity_boundary._read_object_format(inputs)
        index_payload = identity_boundary._read_index_manifest(inputs)
        entries = identity_boundary._parse_index_manifest(index_payload)
        root_tree_sha = identity_boundary._root_tree_sha(entries)
        commit_payload = identity_boundary._commit_payload(
            tree_sha=root_tree_sha,
            parent_sha=identity.base_sha,
            subject=identity.commit_subject,
            epoch_seconds=identity.commit_epoch_seconds,
        )
        predicted_commit_sha = identity_boundary._git_sha1("commit", commit_payload)
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "fresh ADR-DC-042 workspace/object revalidation failed"
        ) from exc
    if (
        object_format != identity.object_format
        or hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256
        or len(entries) != identity.index_entry_count
        or root_tree_sha != identity.root_tree_sha
        or hashlib.sha256(commit_payload).hexdigest() != identity.commit_payload_sha256
        or predicted_commit_sha != identity.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitWriteReservationError(
            "workspace/index/tree/commit identity drifted after ADR-DC-042"
        )
    return inputs


def _authorization_window_allows_reservation(
    proof: PilotExactTaskLocalCommitAuthorizationProof,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="reservation time")
    verified = _utc(proof.verified_at_utc, name="authorization verified_at_utc")
    authorized = _utc(proof.authorization.authorized_at_utc, name="authorization authorized_at_utc")
    expires = _utc(proof.authorization.expires_at_utc, name="authorization expires_at_utc")
    if at < verified or at < authorized or at > expires:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "ADR-DC-044 authorization is not valid for reservation now"
        )


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], Path, bytes, Path, bytes]] = {}

    def mark(
        receipt: Any,
        identity: PilotExactTaskLocalCommitObjectIdentity,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(identity),
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, identity_ref, final_path, final_payload, lock_path, lock_payload = entry
        identity = identity_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or identity is None
            or identity.identity_authenticated is not True
            or identity.sha256 != receipt.local_commit_object_identity_sha256
            or receipt.sha256 != digest
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
        ):
            return None
        inputs = identity_boundary._get_live_local_commit_object_identity_inputs(identity)
        if inputs is None:
            return None
        result = dict(inputs)
        result["local_commit_object_identity"] = identity
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_local_commit_write_reservation_authenticated, _get_live_local_commit_write_reservation_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitWriteReservationReceipt:
    ledger_root_path_sha256: str
    reservation_key_sha256: str
    authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    local_commit_write_requirements_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    predicted_commit_sha: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    fresh_revalidated_at_utc: str
    reserved_at_utc: str
    host_replay_guard_committed: bool = True
    authorization_proof_verified: bool = True
    fresh_live_identity_revalidated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    index_manifest_revalidated: bool = True
    root_tree_revalidated: bool = True
    commit_payload_revalidated: bool = True
    local_write_reserved: bool = True
    one_shot_local_write_required: bool = True
    local_write_authorization_consumed: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_SCHEMA:
            raise PilotExactTaskLocalCommitWriteReservationError("local-write reservation schema is unsupported")
        if self.ledger_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE:
            raise PilotExactTaskLocalCommitWriteReservationError("local-write reservation ledger scope is unsupported")
        for name in (
            "ledger_root_path_sha256",
            "reservation_key_sha256",
            "authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "local_commit_write_requirements_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if self.reservation_key_sha256 != self.local_write_nonce_sha256:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "reservation key must be the exact human-signed local-write nonce"
            )
        if self.local_write_nonce_sha256 == self.execution_nonce_sha256:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation nonce must differ from execution nonce"
            )
        fresh = _utc(self.fresh_revalidated_at_utc, name="fresh_revalidated_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if reserved < fresh:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation predates fresh revalidation"
            )
        required_true = (
            "host_replay_guard_committed",
            "authorization_proof_verified",
            "fresh_live_identity_revalidated",
            "fresh_workspace_snapshot_matched",
            "index_manifest_revalidated",
            "root_tree_revalidated",
            "commit_payload_revalidated",
            "local_write_reserved",
            "one_shot_local_write_required",
            "local_write_authorization_consumed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitWriteReservationError("local-write reservation evidence is incomplete")
        forced_false = (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
            "integration_ready",
            "product_pilot_started",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation cannot grant Git/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY:
            raise PilotExactTaskLocalCommitWriteReservationError("local-write reservation authority is unsupported")

    @property
    def reservation_authenticated(self) -> bool:
        return _get_live_local_commit_write_reservation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskLocalCommitWriteReservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(cls, text: str) -> "PilotExactTaskLocalCommitWriteReservationReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskLocalCommitWriteReservationLedger:
    """Permanent create-once reservation keyed by the signed local-write nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="reservation_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def acquire(
        self,
        *,
        proof: PilotExactTaskLocalCommitAuthorizationProof,
        identity: PilotExactTaskLocalCommitObjectIdentity,
    ) -> bytes:
        key = proof.local_write_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskLocalCommitWriteReservationError(
                "exact local-write nonce was already reserved or requires recovery"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-local-commit-write-reservation-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "reservation_key_sha256": key,
                "authorization_proof_sha256": proof.sha256,
                "authorization_sha256": proof.authorization_sha256,
                "authorization_signature_sha256": proof.signature_sha256,
                "local_commit_write_requirements_sha256": proof.local_commit_write_requirements_sha256,
                "local_commit_object_identity_sha256": identity.sha256,
                "execution_nonce_sha256": proof.execution_nonce_sha256,
                "local_write_nonce_sha256": proof.local_write_nonce_sha256,
                "predicted_commit_sha": proof.predicted_commit_sha,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "exact local-write nonce could not be durably reserved"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskLocalCommitWriteReservationReceipt,
        identity: PilotExactTaskLocalCommitObjectIdentity,
        lock_payload: bytes,
    ) -> PilotExactTaskLocalCommitWriteReservationReceipt:
        final, pending, lock = self._paths(receipt.reservation_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation marker changed before commit"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation receipt state already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskLocalCommitWriteReservationError(
                    "local-write reservation receipt read-back mismatch"
                )
            parsed = PilotExactTaskLocalCommitWriteReservationReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskLocalCommitWriteReservationError(
                    "local-write reservation receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskLocalCommitWriteReservationError(
                    "local-write marker changed before provenance registration"
                )
            _mark_local_commit_write_reservation_authenticated(
                parsed,
                identity,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.reservation_authenticated is not True:
                raise PilotExactTaskLocalCommitWriteReservationError(
                    "local-write reservation lost live durable provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskLocalCommitWriteReservationError):
                raise
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation is durable but receipt requires recovery"
            ) from exc


def _reserve_verified_exact_task_local_commit_write(
    *,
    authorization_proof: PilotExactTaskLocalCommitAuthorizationProof,
    local_commit_object_identity: PilotExactTaskLocalCommitObjectIdentity,
    ledger: _PilotExactTaskLocalCommitWriteReservationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskLocalCommitWriteReservationReceipt:
    proof = _require_authorization_proof(authorization_proof)
    identity = _require_live_identity(local_commit_object_identity)
    if type(ledger) is not _PilotExactTaskLocalCommitWriteReservationLedger:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "local-write reservation ledger is required"
        )
    _require_proof_identity_binding(proof, identity)
    _fresh_identity_revalidation(identity)
    fresh_at = now_provider()
    _authorization_window_allows_reservation(proof, fresh_at)
    fresh_time = _utc(fresh_at, name="fresh_revalidated_at_utc")
    marker = ledger.acquire(proof=proof, identity=identity)
    _fresh_identity_revalidation(identity)
    reserved_at = now_provider()
    _authorization_window_allows_reservation(proof, reserved_at)
    reserved_time = _utc(reserved_at, name="reserved_at_utc")
    if reserved_time < fresh_time:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "system clock moved backwards during local-write reservation"
        )
    receipt = PilotExactTaskLocalCommitWriteReservationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        reservation_key_sha256=proof.local_write_nonce_sha256,
        authorization_proof_sha256=proof.sha256,
        authorization_sha256=proof.authorization_sha256,
        authorization_signature_sha256=proof.signature_sha256,
        local_commit_write_requirements_sha256=proof.local_commit_write_requirements_sha256,
        local_commit_object_identity_sha256=identity.sha256,
        execution_nonce_sha256=proof.execution_nonce_sha256,
        local_write_nonce_sha256=proof.local_write_nonce_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        index_manifest_sha256=identity.index_manifest_sha256,
        root_tree_sha=identity.root_tree_sha,
        commit_payload_sha256=identity.commit_payload_sha256,
        fresh_revalidated_at_utc=fresh_at,
        reserved_at_utc=reserved_at,
    )
    return ledger.commit(receipt=receipt, identity=identity, lock_payload=marker)


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskLocalCommitWriteReservationError(
                "local-write reservation ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitWriteReservationError(
            "canonical local-write reservation ledger is not host-admin controlled"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitWriteReservationError",
    "PilotExactTaskLocalCommitWriteReservationReceipt",
]
