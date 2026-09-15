"""ADR-DC-046 durable consumption of one admitted exact local-commit authorization.

This boundary irreversibly consumes the live ADR-DC-045 one-shot authorization
on a separate host-local execution ledger after fresh workspace/object identity
revalidation. It deliberately performs no Git object/ref write and exposes no
generic Git command capability. A later fixed write boundary must require the
exact live receipt returned here.
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
from . import _improvement_pilot_exact_task_local_commit_authorization_admission_impl as _admission_impl
from . import improvement_pilot_exact_task_local_commit_authorization_admission as admission_boundary
from .improvement_pilot_exact_task_local_commit_authorization_admission import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_AUTHORITY,
    PilotExactTaskLocalCommitAuthorizationAdmissionReceipt,
)
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PilotExactTaskLocalCommitObjectIdentity,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-write-consumption-receipt/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY = (
    "host-consumed-one-dc-l16-exact-local-commit-authorization-for-fixed-write-boundary-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskLocalCommitWriteConsumptionError(ValueError):
    """The exact admitted local-commit authorization cannot be consumed safely."""


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
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "local-commit write consumption is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskLocalCommitWriteConsumptionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitWriteConsumptionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
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
    PilotExactTaskLocalCommitAuthorizationAdmissionReceipt,
    PilotExactTaskLocalCommitObjectIdentity,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskLocalCommitAuthorizationAdmissionReceipt:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "exact ADR-DC-045 local-commit authorization admission receipt is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitAuthorizationAdmissionReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "ADR-DC-045 admission receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "ADR-DC-045 admission receipt identity mismatch"
        )
    required_true = (
        "host_replay_guard_committed",
        "human_local_commit_authorization_verified",
        "local_commit_authorization_admitted",
        "one_shot_local_commit_required",
        "exact_object_identity_revalidated",
        "fresh_workspace_snapshot_matched",
    )
    forced_false = (
        "local_commit_authorization_consumed",
        "git_object_write_authorized",
        "local_ref_update_authorized",
        "local_commit_authorized",
        "local_commit_created",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_ADMISSION_AUTHORITY
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.admission_authenticated is not True
    ):
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "write consumption requires the live unconsumed ADR-DC-045 admission"
        )
    live = admission_boundary._get_live_local_commit_authorization_admission_inputs(
        value
    )
    if live is None:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "ADR-DC-045 live admission inputs are unavailable"
        )
    identity = live.get("object_identity")
    if type(identity) is not PilotExactTaskLocalCommitObjectIdentity:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "ADR-DC-045 live object identity is unavailable"
        )
    if (
        identity.identity_authenticated is not True
        or identity.sha256 != value.local_commit_object_identity_sha256
        or identity.local_commit_plan_sha256 != value.local_commit_plan_sha256
        or identity.development_task_sha256 != value.development_task_sha256
        or identity.task_id != value.task_id
        or identity.repository != value.repository
        or identity.base_sha != value.base_sha
        or identity.root_tree_sha != value.root_tree_sha
        or identity.predicted_commit_sha != value.predicted_commit_sha
        or identity.commit_payload_sha256 != value.commit_payload_sha256
        or identity.index_manifest_sha256 != value.index_manifest_sha256
        or identity.index_entry_count != value.index_entry_count
        or identity.commit_subject_sha256 != value.commit_subject_sha256
    ):
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "ADR-DC-045 live identity binding no longer matches the admission"
        )
    inputs = _admission_impl.identity_boundary._get_live_local_commit_object_identity_inputs(
        identity
    )
    if inputs is None:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "ADR-DC-042 live identity inputs are unavailable"
        )
    return value, identity, inputs


def _fresh_identity_check(
    admission: PilotExactTaskLocalCommitAuthorizationAdmissionReceipt,
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
):
    snapshot = _admission_impl._fresh_workspace_snapshot(inputs)
    _admission_impl._require_snapshot_matches_identity(identity, inputs, snapshot)
    _admission_impl._revalidate_object_identity(identity, inputs)
    if snapshot.sha256 != admission.pre_admission_workspace_snapshot_sha256:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "workspace no longer matches ADR-DC-045 admission evidence"
        )
    return snapshot


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            Path,
            bytes,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: Any,
        admission: PilotExactTaskLocalCommitAuthorizationAdmissionReceipt,
        identity: PilotExactTaskLocalCommitObjectIdentity,
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
            weakref.ref(receipt, cleanup),
            weakref.ref(admission),
            weakref.ref(identity),
            lock_path,
            lock_payload,
            receipt_path,
            receipt_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            admission_ref,
            identity_ref,
            lock_path,
            lock_payload,
            receipt_path,
            receipt_payload,
        ) = entry
        admission = admission_ref()
        identity = identity_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or admission is None
            or identity is None
            or admission.admission_authenticated is not True
            or identity.identity_authenticated is not True
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
            {"admission_receipt": admission, "object_identity": identity}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_write_consumption_authenticated,
    _get_live_local_commit_write_consumption_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitWriteConsumptionReceipt:
    ledger_root_path_sha256: str
    consumption_key_sha256: str
    admission_receipt: PilotExactTaskLocalCommitAuthorizationAdmissionReceipt
    admission_receipt_sha256: str
    authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    authorization_requirements_sha256: str
    requirements_key_sha256: str
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    root_tree_sha: str
    predicted_commit_sha: str
    commit_payload_sha256: str
    index_manifest_sha256: str
    index_entry_count: int
    commit_subject_sha256: str
    local_commit_nonce_sha256: str
    admitted_at_utc: str
    prepared_at_utc: str
    consumed_at_utc: str
    pre_consumption_workspace_snapshot_sha256: str
    post_lock_workspace_snapshot_sha256: str
    object_format: str
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE
    host_consumption_guard_committed: bool = True
    admission_authenticated_at_consumption: bool = True
    human_local_commit_authorization_verified: bool = True
    local_commit_authorization_admitted: bool = True
    local_commit_authorization_consumed: bool = True
    one_shot_local_commit_required: bool = True
    exact_object_identity_revalidated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    write_boundary_ready: bool = True
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
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_RECEIPT_SCHEMA
            or self.ledger_scope
            != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE
            or self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY
        ):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "local-commit write-consumption schema/scope/authority is unsupported"
            )
        if type(self.admission_receipt) is not PilotExactTaskLocalCommitAuthorizationAdmissionReceipt:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "exact ADR-DC-045 admission receipt is required"
            )
        try:
            replayed = PilotExactTaskLocalCommitAuthorizationAdmissionReceipt.from_mapping(
                self.admission_receipt.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "embedded ADR-DC-045 admission receipt replay failed"
            ) from exc
        if (
            replayed != self.admission_receipt
            or replayed.sha256 != self.admission_receipt_sha256
        ):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "embedded ADR-DC-045 admission identity mismatch"
            )
        for name in (
            "ledger_root_path_sha256",
            "consumption_key_sha256",
            "admission_receipt_sha256",
            "authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "authorization_requirements_sha256",
            "requirements_key_sha256",
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "development_task_sha256",
            "commit_payload_sha256",
            "index_manifest_sha256",
            "commit_subject_sha256",
            "local_commit_nonce_sha256",
            "pre_consumption_workspace_snapshot_sha256",
            "post_lock_workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitWriteConsumptionError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "repository is invalid"
            )
        if (
            isinstance(self.index_entry_count, bool)
            or not isinstance(self.index_entry_count, int)
            or self.index_entry_count < 1
            or self.index_entry_count > 1_000_000
        ):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "index_entry_count is invalid"
            )
        if self.object_format != "sha1":
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "object_format is unsupported"
            )
        admitted = _utc(self.admitted_at_utc, name="admitted_at_utc")
        prepared = _utc(self.prepared_at_utc, name="prepared_at_utc")
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        if not admitted <= prepared <= consumed:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "local-commit write-consumption timestamps are not monotonic"
            )
        source = self.admission_receipt
        expected = {
            "admission_receipt_sha256": source.sha256,
            "authorization_proof_sha256": source.authorization_proof_sha256,
            "authorization_sha256": source.authorization_sha256,
            "authorization_signature_sha256": source.authorization_signature_sha256,
            "authorization_requirements_sha256": source.authorization_requirements_sha256,
            "requirements_key_sha256": source.requirements_key_sha256,
            "local_commit_object_identity_sha256": source.local_commit_object_identity_sha256,
            "local_commit_plan_sha256": source.local_commit_plan_sha256,
            "development_task_sha256": source.development_task_sha256,
            "task_id": source.task_id,
            "repository": source.repository,
            "base_sha": source.base_sha,
            "root_tree_sha": source.root_tree_sha,
            "predicted_commit_sha": source.predicted_commit_sha,
            "commit_payload_sha256": source.commit_payload_sha256,
            "index_manifest_sha256": source.index_manifest_sha256,
            "index_entry_count": source.index_entry_count,
            "commit_subject_sha256": source.commit_subject_sha256,
            "local_commit_nonce_sha256": source.local_commit_nonce_sha256,
            "admitted_at_utc": source.admitted_at_utc,
            "object_format": source.object_format,
        }
        mismatch = next(
            (
                name
                for name, value in expected.items()
                if getattr(self, name) != value
            ),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                f"write-consumption receipt binding mismatch: {mismatch}"
            )
        if self.consumption_key_sha256 != self.local_commit_nonce_sha256:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "consumption key must equal the signed local-commit nonce"
            )
        if (
            self.pre_consumption_workspace_snapshot_sha256
            != source.pre_admission_workspace_snapshot_sha256
            or self.post_lock_workspace_snapshot_sha256
            != source.post_lock_workspace_snapshot_sha256
        ):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "write-consumption workspace binding mismatch"
            )
        required_true = (
            "host_consumption_guard_committed",
            "admission_authenticated_at_consumption",
            "human_local_commit_authorization_verified",
            "local_commit_authorization_admitted",
            "local_commit_authorization_consumed",
            "one_shot_local_commit_required",
            "exact_object_identity_revalidated",
            "fresh_workspace_snapshot_matched",
            "write_boundary_ready",
        )
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "required write-consumption evidence is not satisfied"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "write-consumption receipt cannot grant Git write/publication authority"
            )

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskLocalCommitWriteConsumptionReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "write-consumption receipt must be an object"
            )
        if set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "write-consumption receipt fields mismatch"
            )
        data = dict(value)
        embedded = data.get("admission_receipt")
        if not isinstance(embedded, Mapping):
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "admission_receipt must be an object"
            )
        data["admission_receipt"] = (
            PilotExactTaskLocalCommitAuthorizationAdmissionReceipt.from_mapping(
                embedded
            )
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.admission_receipt.to_dict()
                if name == "admission_receipt"
                else getattr(self, name)
            )
            for name in self.__dataclass_fields__
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def consumption_authenticated(self) -> bool:
        return _get_live_local_commit_write_consumption_inputs(self) is not None


class _PilotExactTaskLocalCommitWriteConsumptionLedger:
    """Create-once commit-execution ledger keyed by the signed local-commit nonce."""

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
        admission: PilotExactTaskLocalCommitAuthorizationAdmissionReceipt,
        identity: PilotExactTaskLocalCommitObjectIdentity,
    ) -> tuple[Path, bytes]:
        lock = self._lock_path(key)
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-local-commit-write-consumption-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "consumption_key_sha256": key,
                "admission_receipt_sha256": admission.sha256,
                "authorization_proof_sha256": admission.authorization_proof_sha256,
                "authorization_requirements_sha256": admission.authorization_requirements_sha256,
                "requirements_key_sha256": admission.requirements_key_sha256,
                "local_commit_object_identity_sha256": identity.sha256,
                "base_sha": identity.base_sha,
                "root_tree_sha": identity.root_tree_sha,
                "predicted_commit_sha": identity.predicted_commit_sha,
                "commit_payload_sha256": identity.commit_payload_sha256,
                "index_manifest_sha256": identity.index_manifest_sha256,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "local-commit authorization was already consumed or could not be durably consumed"
            ) from exc
        if _read_bound_file(lock) != payload:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "local-commit write-consumption lock read-back mismatch"
            )
        return lock, payload

    def publish(
        self,
        *,
        key: str,
        receipt: PilotExactTaskLocalCommitWriteConsumptionReceipt,
    ) -> tuple[Path, bytes]:
        path = self._receipt_path(key)
        payload = receipt.canonical_json().encode("utf-8")
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "local-commit write-consumption receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "local-commit write-consumption receipt publication failed closed"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "local-commit write-consumption receipt read-back mismatch"
            )
        try:
            parsed = PilotExactTaskLocalCommitWriteConsumptionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "published local-commit write-consumption receipt is invalid"
            ) from exc
        if parsed != receipt or parsed.sha256 != receipt.sha256:
            raise PilotExactTaskLocalCommitWriteConsumptionError(
                "published local-commit write-consumption receipt identity mismatch"
            )
        return path, payload


def _consume_verified_pilot_exact_task_local_commit_authorization(
    *,
    admission_receipt: PilotExactTaskLocalCommitAuthorizationAdmissionReceipt,
    ledger: _PilotExactTaskLocalCommitWriteConsumptionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskLocalCommitWriteConsumptionReceipt:
    admission, identity, inputs = _require_live_admission(admission_receipt)

    pre = _fresh_identity_check(admission, identity, inputs)
    stable = _admission_impl._fresh_workspace_snapshot(inputs)
    _admission_impl._require_snapshot_matches_identity(identity, inputs, stable)
    if stable != pre or stable.sha256 != pre.sha256:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "workspace changed during pre-consumption revalidation"
        )

    prepared_at = now_provider()
    prepared = _utc(prepared_at, name="prepared_at_utc")
    admitted = _utc(admission.admitted_at_utc, name="admitted_at_utc")
    expires = _utc(
        admission.authorization_proof.authorization.expires_at_utc,
        name="authorization expires_at_utc",
    )
    if prepared < admitted:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "write consumption predates ADR-DC-045 admission"
        )
    if prepared >= expires:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "human local-commit authorization expired before durable consumption"
        )

    key = _hex64(
        admission.local_commit_nonce_sha256,
        name="local_commit_nonce_sha256",
    )
    lock_path, lock_payload = ledger.consume(
        key=key,
        admission=admission,
        identity=identity,
    )

    post_lock = _admission_impl._fresh_workspace_snapshot(inputs)
    _admission_impl._require_snapshot_matches_identity(identity, inputs, post_lock)
    _admission_impl._revalidate_object_identity(identity, inputs)
    if post_lock != pre or post_lock.sha256 != pre.sha256:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "workspace changed after durable local-commit consumption; authorization remains burned"
        )

    consumed_at = now_provider()
    consumed = _utc(consumed_at, name="consumed_at_utc")
    if consumed < prepared:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "local-commit write-consumption clock moved backwards after durable consumption"
        )
    if consumed >= expires:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "human local-commit authorization expired after durable consumption; authorization remains burned"
        )

    receipt = PilotExactTaskLocalCommitWriteConsumptionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        consumption_key_sha256=key,
        admission_receipt=admission,
        admission_receipt_sha256=admission.sha256,
        authorization_proof_sha256=admission.authorization_proof_sha256,
        authorization_sha256=admission.authorization_sha256,
        authorization_signature_sha256=admission.authorization_signature_sha256,
        authorization_requirements_sha256=admission.authorization_requirements_sha256,
        requirements_key_sha256=admission.requirements_key_sha256,
        local_commit_object_identity_sha256=admission.local_commit_object_identity_sha256,
        local_commit_plan_sha256=admission.local_commit_plan_sha256,
        development_task_sha256=admission.development_task_sha256,
        task_id=admission.task_id,
        repository=admission.repository,
        base_sha=admission.base_sha,
        root_tree_sha=admission.root_tree_sha,
        predicted_commit_sha=admission.predicted_commit_sha,
        commit_payload_sha256=admission.commit_payload_sha256,
        index_manifest_sha256=admission.index_manifest_sha256,
        index_entry_count=admission.index_entry_count,
        commit_subject_sha256=admission.commit_subject_sha256,
        local_commit_nonce_sha256=admission.local_commit_nonce_sha256,
        admitted_at_utc=admission.admitted_at_utc,
        prepared_at_utc=prepared_at,
        consumed_at_utc=consumed_at,
        pre_consumption_workspace_snapshot_sha256=pre.sha256,
        post_lock_workspace_snapshot_sha256=post_lock.sha256,
        object_format=admission.object_format,
    )
    receipt_path, receipt_payload = ledger.publish(key=key, receipt=receipt)
    _mark_write_consumption_authenticated(
        receipt,
        admission,
        identity,
        lock_path=lock_path,
        lock_payload=lock_payload,
        receipt_path=receipt_path,
        receipt_payload=receipt_payload,
    )
    if receipt.consumption_authenticated is not True:
        raise PilotExactTaskLocalCommitWriteConsumptionError(
            "live local-commit write-consumption provenance was not established"
        )
    return receipt


def consume_pilot_exact_task_local_commit_authorization(
    *,
    admission_receipt: PilotExactTaskLocalCommitAuthorizationAdmissionReceipt,
) -> PilotExactTaskLocalCommitWriteConsumptionReceipt:
    raise PilotExactTaskLocalCommitWriteConsumptionError(
        "production local-commit write-consumption boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitWriteConsumptionError",
    "PilotExactTaskLocalCommitWriteConsumptionReceipt",
    "consume_pilot_exact_task_local_commit_authorization",
]
