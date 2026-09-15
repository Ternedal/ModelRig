"""ADR-DC-043 replay-safe one-shot local commit write authorization.

This boundary accepts only the exact live ADR-DC-042 commit-object identity,
fresh-revalidates the unchanged staged candidate and exact in-memory Git object
identity, then durably reserves one host-local write slot keyed by the original
human-signed execution nonce.

It does not write a Git object, create a commit, move a local ref, publish
remotely, or execute any caller-controlled command.  The resulting receipt is
usable by a later boundary only while its process-local live provenance remains
intact.
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
from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY,
    PilotExactTaskLocalCommitObjectIdentity,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-write-authorization-receipt/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_AUTHORITY = (
    "host-authorized-one-dc-l16-exact-local-commit-write-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)
_MAX_ARTIFACT_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-local-commit-write-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-local-commit-write-authorization-ledger-v1"
)


class PilotExactTaskLocalCommitWriteAuthorizationError(ValueError):
    """The exact local commit write authorization is replayed or unsafe."""


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
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "local commit write authorization is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskLocalCommitWriteAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitWriteAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
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


def _require_live_identity(
    value: Any,
) -> tuple[PilotExactTaskLocalCommitObjectIdentity, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskLocalCommitObjectIdentity:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "exact ADR-DC-042 local commit object identity is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitObjectIdentity.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "ADR-DC-042 object identity replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "ADR-DC-042 object identity mismatch"
        )
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
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "write authorization requires one live inert ADR-DC-042 identity"
        )
    inputs = identity_boundary._get_live_local_commit_object_identity_inputs(value)
    if inputs is None:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "ADR-DC-042 live identity inputs are unavailable"
        )
    plan = inputs.get("local_commit_plan")
    task = inputs.get("task")
    if (
        plan is None
        or task is None
        or getattr(plan, "sha256", None) != value.local_commit_plan_sha256
        or getattr(plan, "plan_authenticated", None) is not True
        or getattr(task, "task_id", None) != value.task_id
        or getattr(task, "repository", None) != value.repository
        or getattr(task, "base_sha", None) != value.base_sha
    ):
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "ADR-DC-042 identity is not bound to its exact live plan/task"
        )
    return value, inputs


def _fresh_revalidate_exact_identity(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> None:
    plan = inputs.get("local_commit_plan")
    if plan is None:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "live local commit plan is unavailable"
        )
    try:
        snapshot = identity_boundary._fresh_workspace_snapshot(inputs)
        identity_boundary._require_snapshot_matches_plan(plan, snapshot)
        object_format = identity_boundary._read_object_format(inputs)
        index_payload = identity_boundary._read_index_manifest(inputs)
        index_entries = identity_boundary._parse_index_manifest(index_payload)
        tree_sha = identity_boundary._root_tree_sha(index_entries)
        commit_payload = identity_boundary._commit_payload(
            tree_sha=tree_sha,
            parent_sha=identity.base_sha,
            subject=identity.commit_subject,
            epoch_seconds=identity.commit_epoch_seconds,
        )
        predicted = identity_boundary._git_sha1("commit", commit_payload)
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "fresh exact commit identity revalidation failed"
        ) from exc

    if (
        snapshot.sha256 != identity.post_execution_workspace_snapshot_sha256
        or object_format != identity.object_format
        or hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256
        or len(index_entries) != identity.index_entry_count
        or tree_sha != identity.root_tree_sha
        or hashlib.sha256(commit_payload).hexdigest() != identity.commit_payload_sha256
        or predicted != identity.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "workspace/index no longer matches ADR-DC-042 exact commit identity"
        )


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
            Path,
            bytes,
        ],
    ] = {}

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
        (
            pid,
            digest,
            receipt_ref,
            identity_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        identity = identity_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or identity is None
            or receipt.sha256 != digest
            or receipt.local_commit_object_identity_sha256 != identity.sha256
            or identity.identity_authenticated is not True
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


(
    _mark_local_commit_write_authorization_authenticated,
    _get_live_local_commit_write_authorization_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitWriteAuthorizationReceipt:
    ledger_root_path_sha256: str
    authorization_key_sha256: str
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    post_execution_evaluation_sha256: str
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    candidate_patch_sha256: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    fresh_revalidated_at_utc: str
    authorized_at_utc: str
    host_replay_guard_committed: bool = True
    local_commit_object_identity_authenticated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    fresh_index_manifest_matched: bool = True
    exact_commit_identity_revalidated: bool = True
    local_commit_write_authority_reserved: bool = True
    one_shot_local_commit_write_required: bool = True
    git_object_write_authorized: bool = True
    local_ref_update_authorized: bool = True
    local_commit_authorized: bool = True
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
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization schema is unsupported"
            )
        if self.ledger_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_LEDGER_SCOPE:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization ledger scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "authorization_key_sha256",
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "post_execution_evaluation_sha256",
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.authorization_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write key must be the exact signed execution nonce"
            )
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitWriteAuthorizationError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskLocalCommitWriteAuthorizationError("repository is invalid")
        fresh = _utc(self.fresh_revalidated_at_utc, name="fresh_revalidated_at_utc")
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        if authorized < fresh:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization predates fresh revalidation"
            )
        required_true = (
            "host_replay_guard_committed",
            "local_commit_object_identity_authenticated",
            "fresh_workspace_snapshot_matched",
            "fresh_index_manifest_matched",
            "exact_commit_identity_revalidated",
            "local_commit_write_authority_reserved",
            "one_shot_local_commit_write_required",
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization evidence is incomplete"
            )
        forced_false = (
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
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization cannot claim write completion/publication"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_AUTHORITY:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization authority is unsupported"
            )

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_local_commit_write_authorization_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskLocalCommitWriteAuthorizationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskLocalCommitWriteAuthorizationReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskLocalCommitWriteAuthorizationLedger:
    """Permanent create-once local-write slot keyed by the execution nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="authorization_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def acquire(self, *, identity: PilotExactTaskLocalCommitObjectIdentity) -> bytes:
        key = identity.execution_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "exact execution nonce already has a local-write slot or needs recovery"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-local-commit-write-authorization-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "authorization_key_sha256": key,
                "local_commit_object_identity_sha256": identity.sha256,
                "local_commit_plan_sha256": identity.local_commit_plan_sha256,
                "execution_nonce_sha256": identity.execution_nonce_sha256,
                "development_task_sha256": identity.development_task_sha256,
                "base_sha": identity.base_sha,
                "index_manifest_sha256": identity.index_manifest_sha256,
                "root_tree_sha": identity.root_tree_sha,
                "commit_payload_sha256": identity.commit_payload_sha256,
                "predicted_commit_sha": identity.predicted_commit_sha,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write slot could not be durably reserved"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskLocalCommitWriteAuthorizationReceipt,
        identity: PilotExactTaskLocalCommitObjectIdentity,
        lock_payload: bytes,
    ) -> PilotExactTaskLocalCommitWriteAuthorizationReceipt:
        final, pending, lock = self._paths(receipt.authorization_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization marker changed before commit"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization receipt already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskLocalCommitWriteAuthorizationError(
                    "local commit write authorization receipt read-back mismatch"
                )
            parsed = PilotExactTaskLocalCommitWriteAuthorizationReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskLocalCommitWriteAuthorizationError(
                    "local commit write receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskLocalCommitWriteAuthorizationError(
                    "local commit write marker changed before provenance registration"
                )
            _mark_local_commit_write_authorization_authenticated(
                parsed,
                identity,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.authorization_authenticated is not True:
                raise PilotExactTaskLocalCommitWriteAuthorizationError(
                    "local commit write authorization lost live transaction provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskLocalCommitWriteAuthorizationError):
                raise
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization is durable but requires recovery"
            ) from exc


def _authorize_verified_pilot_exact_task_local_commit_write(
    *,
    local_commit_object_identity: PilotExactTaskLocalCommitObjectIdentity,
    ledger: _PilotExactTaskLocalCommitWriteAuthorizationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskLocalCommitWriteAuthorizationReceipt:
    identity, before_inputs = _require_live_identity(local_commit_object_identity)
    if type(ledger) is not _PilotExactTaskLocalCommitWriteAuthorizationLedger:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "local commit write authorization ledger is required"
        )

    _fresh_revalidate_exact_identity(identity, before_inputs)
    fresh_at = now_provider()
    fresh_time = _utc(fresh_at, name="fresh_revalidated_at_utc")
    materialized_time = _utc(identity.materialized_at_utc, name="materialized_at_utc")
    if fresh_time < materialized_time:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "system clock moved backwards after ADR-DC-042 materialization"
        )

    marker = ledger.acquire(identity=identity)

    # Revalidate after the permanent marker too.  Any drift after reservation
    # burns this local-write slot fail-closed instead of making it reusable.
    identity_again, after_inputs = _require_live_identity(identity)
    if identity_again is not identity:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "live ADR-DC-042 identity changed during authorization"
        )
    _fresh_revalidate_exact_identity(identity, after_inputs)
    authorized_at = now_provider()
    authorized_time = _utc(authorized_at, name="authorized_at_utc")
    if authorized_time < fresh_time:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "system clock moved backwards during local commit write authorization"
        )

    receipt = PilotExactTaskLocalCommitWriteAuthorizationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        authorization_key_sha256=identity.execution_nonce_sha256,
        local_commit_object_identity_sha256=identity.sha256,
        local_commit_plan_sha256=identity.local_commit_plan_sha256,
        post_execution_evaluation_sha256=identity.post_execution_evaluation_sha256,
        execution_transaction_sha256=identity.execution_transaction_sha256,
        tier_a_receipt_sha256=identity.tier_a_receipt_sha256,
        execution_nonce_sha256=identity.execution_nonce_sha256,
        development_task_sha256=identity.development_task_sha256,
        task_id=identity.task_id,
        repository=identity.repository,
        base_sha=identity.base_sha,
        candidate_patch_sha256=identity.candidate_patch_sha256,
        index_manifest_sha256=identity.index_manifest_sha256,
        root_tree_sha=identity.root_tree_sha,
        commit_payload_sha256=identity.commit_payload_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        fresh_revalidated_at_utc=fresh_at,
        authorized_at_utc=authorized_at,
    )
    return ledger.commit(
        receipt=receipt,
        identity=identity,
        lock_payload=marker,
    )


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskLocalCommitWriteAuthorizationError(
                "local commit write authorization is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "canonical local commit write authorization ledger is not host-admin controlled"
        ) from exc


def authorize_pilot_exact_task_local_commit_write(
    local_commit_object_identity: PilotExactTaskLocalCommitObjectIdentity,
) -> PilotExactTaskLocalCommitWriteAuthorizationReceipt:
    """Host-pinned ADR-DC-043 entrypoint. Authorize one exact local write only."""
    try:
        root = _canonical_ledger_root()
        ledger = _PilotExactTaskLocalCommitWriteAuthorizationLedger(root)
        return _authorize_verified_pilot_exact_task_local_commit_write(
            local_commit_object_identity=local_commit_object_identity,
            ledger=ledger,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskLocalCommitWriteAuthorizationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskLocalCommitWriteAuthorizationError(
            "host-controlled local commit write authorization failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitWriteAuthorizationError",
    "PilotExactTaskLocalCommitWriteAuthorizationReceipt",
    "authorize_pilot_exact_task_local_commit_write",
]
