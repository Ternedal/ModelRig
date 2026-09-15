"""ADR-DC-047 fixed materialization of exact local Git tree/commit objects.

This is the first local-commit boundary allowed to mutate the Git object database.
It accepts only the exact live ADR-DC-046 consumption receipt, fresh-revalidates
the frozen workspace/index/object identity again, irreversibly claims the live
consumption provenance, durably commits a host-local object-write guard, and
then writes only the exact precomputed tree and commit objects.

It never updates HEAD or any ref, never runs git commit/write-tree/commit-tree,
and grants no reusable Git/ref/publication authority after the transaction.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .durable_publication import DurablePublicationError, create_once_file
from . import _improvement_pilot_exact_task_local_commit_write_consumption_impl as _consumption_impl
from . import improvement_pilot_exact_task_local_commit_write_consumption as consumption_boundary
from .improvement_pilot_exact_task_local_commit_write_consumption import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY,
    PilotExactTaskLocalCommitWriteConsumptionReceipt,
)
from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PilotExactTaskLocalCommitObjectIdentity,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-object-write-receipt/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY = (
    "host-materialized-one-dc-l16-exact-local-commit-object-set-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_TREE_OBJECTS = 1_000_000
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskLocalCommitObjectWriteError(ValueError):
    """The exact local Git object-write transaction is unsafe or replayed."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskLocalCommitObjectWriteError("local-commit object-write receipt is not canonical JSON") from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskLocalCommitObjectWriteError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskLocalCommitObjectWriteError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitObjectWriteError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskLocalCommitObjectWriteError(f"{name} is invalid") from exc


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


def _require_live_consumption(value: Any) -> tuple[PilotExactTaskLocalCommitWriteConsumptionReceipt, PilotExactTaskLocalCommitObjectIdentity, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskLocalCommitWriteConsumptionReceipt:
        raise PilotExactTaskLocalCommitObjectWriteError("exact ADR-DC-046 local-commit write-consumption receipt is required")
    try:
        replayed = PilotExactTaskLocalCommitWriteConsumptionReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-046 consumption receipt replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-046 consumption receipt identity mismatch")
    required_true = (
        "host_consumption_guard_committed", "admission_authenticated_at_consumption",
        "human_local_commit_authorization_verified", "local_commit_authorization_admitted",
        "local_commit_authorization_consumed", "one_shot_local_commit_required",
        "exact_object_identity_revalidated", "fresh_workspace_snapshot_matched", "write_boundary_ready",
    )
    forced_false = (
        "git_object_write_authorized", "local_ref_update_authorized", "local_commit_authorized",
        "local_commit_created", "remote_write_authorized", "push_authorized", "pr_mutation_authorized",
        "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
    )
    if value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_CONSUMPTION_AUTHORITY or any(getattr(value, name) is not True for name in required_true) or any(getattr(value, name) is not False for name in forced_false) or value.consumption_authenticated is not True:
        raise PilotExactTaskLocalCommitObjectWriteError("object write requires the exact live unspent ADR-DC-046 receipt")
    live = consumption_boundary._get_live_local_commit_write_consumption_inputs(value)
    if live is None:
        raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-046 live consumption inputs are unavailable")
    identity = live.get("object_identity")
    admission = live.get("admission_receipt")
    if type(identity) is not PilotExactTaskLocalCommitObjectIdentity or identity.identity_authenticated is not True or admission is None or getattr(admission, "admission_authenticated", False) is not True:
        raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-046 live identity/admission provenance is unavailable")
    if (
        identity.sha256 != value.local_commit_object_identity_sha256
        or identity.local_commit_plan_sha256 != value.local_commit_plan_sha256
        or identity.development_task_sha256 != value.development_task_sha256
        or identity.task_id != value.task_id or identity.repository != value.repository
        or identity.base_sha != value.base_sha or identity.root_tree_sha != value.root_tree_sha
        or identity.predicted_commit_sha != value.predicted_commit_sha
        or identity.commit_payload_sha256 != value.commit_payload_sha256
        or identity.index_manifest_sha256 != value.index_manifest_sha256
        or identity.index_entry_count != value.index_entry_count
        or identity.commit_subject_sha256 != value.commit_subject_sha256
    ):
        raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-046 receipt is no longer bound to its exact live object identity")
    inputs = identity_boundary._get_live_local_commit_object_identity_inputs(identity)
    if inputs is None:
        raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-042 live identity inputs are unavailable")
    return value, identity, inputs


def _fresh_identity_state(consumption: PilotExactTaskLocalCommitWriteConsumptionReceipt, identity: PilotExactTaskLocalCommitObjectIdentity, inputs: Mapping[str, Any]) -> tuple[Any, bytes, tuple[tuple[str, str, str], ...], bytes]:
    snapshot = _consumption_impl._admission_impl._fresh_workspace_snapshot(inputs)
    _consumption_impl._admission_impl._require_snapshot_matches_identity(identity, inputs, snapshot)
    if snapshot.sha256 != consumption.pre_consumption_workspace_snapshot_sha256:
        raise PilotExactTaskLocalCommitObjectWriteError("workspace no longer matches ADR-DC-046 consumption evidence")
    try:
        object_format = identity_boundary._read_object_format(inputs)
        index_payload = identity_boundary._read_index_manifest(inputs)
        entries = identity_boundary._parse_index_manifest(index_payload)
        root_tree_sha = identity_boundary._root_tree_sha(entries)
        commit_payload = identity_boundary._commit_payload(tree_sha=root_tree_sha, parent_sha=identity.base_sha, subject=identity.commit_subject, epoch_seconds=identity.commit_epoch_seconds)
        predicted_commit_sha = identity_boundary._git_sha1("commit", commit_payload)
    except Exception as exc:
        raise PilotExactTaskLocalCommitObjectWriteError("fresh exact Git object identity revalidation failed") from exc
    if object_format != identity.object_format or hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256 or len(entries) != identity.index_entry_count or root_tree_sha != identity.root_tree_sha or hashlib.sha256(commit_payload).hexdigest() != identity.commit_payload_sha256 or predicted_commit_sha != identity.predicted_commit_sha:
        raise PilotExactTaskLocalCommitObjectWriteError("fresh Git object identity no longer matches ADR-DC-042")
    return snapshot, index_payload, entries, commit_payload


def _tree_object_plan(entries: tuple[tuple[str, str, str], ...]) -> tuple[tuple[str, bytes], ...]:
    root: dict[str, Any] = {}
    for mode, object_sha, path in entries:
        parts = path.split("/")
        node = root
        for component in parts[:-1]:
            existing = node.get(component)
            if existing is None:
                child: dict[str, Any] = {}
                node[component] = child
                node = child
            elif isinstance(existing, dict):
                node = existing
            else:
                raise PilotExactTaskLocalCommitObjectWriteError("index tree contains a path collision")
        leaf = parts[-1]
        if leaf in node:
            raise PilotExactTaskLocalCommitObjectWriteError("index tree contains a duplicate leaf")
        node[leaf] = (mode, object_sha)
    ordered: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    def materialize(node: dict[str, Any]) -> str:
        records: list[tuple[bytes, bytes]] = []
        for name, value in node.items():
            name_raw = name.encode("utf-8")
            if isinstance(value, dict):
                object_sha = materialize(value)
                mode_raw = b"40000"
                sort_key = name_raw + b"/"
            else:
                mode, object_sha = value
                mode_raw = mode.encode("ascii")
                sort_key = name_raw
            records.append((sort_key, mode_raw + b" " + name_raw + b"\0" + bytes.fromhex(object_sha)))
        payload = b"".join(record for _, record in sorted(records, key=lambda item: item[0]))
        sha = identity_boundary._git_sha1("tree", payload)
        if sha not in seen:
            seen.add(sha)
            ordered.append((sha, payload))
        return sha
    materialize(root)
    if not ordered or len(ordered) > _MAX_TREE_OBJECTS:
        raise PilotExactTaskLocalCommitObjectWriteError("exact tree-object plan is empty or oversized")
    return tuple(ordered)


_claim_lock = threading.Lock()
_claimed_consumptions: dict[tuple[int, int], tuple[str, weakref.ReferenceType[Any]]] = {}


def _take_consumption_provenance(receipt: PilotExactTaskLocalCommitWriteConsumptionReceipt) -> None:
    if receipt.consumption_authenticated is not True:
        raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-046 live consumption provenance is unavailable")
    key = (os.getpid(), id(receipt))
    with _claim_lock:
        prior = _claimed_consumptions.get(key)
        if prior is not None and prior[1]() is receipt:
            raise PilotExactTaskLocalCommitObjectWriteError("ADR-DC-046 live consumption provenance was already taken")
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            with _claim_lock:
                _claimed_consumptions.pop(key, None)
        _claimed_consumptions[key] = (receipt.sha256, weakref.ref(receipt, cleanup))


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_claimed_consumptions.clear)


def _hash_object_write(*, inputs: Mapping[str, Any], kind: str, payload: bytes, expected_sha: str) -> str:
    if kind not in {"tree", "commit"}:
        raise PilotExactTaskLocalCommitObjectWriteError("unsupported fixed Git object-write kind")
    _hex40(expected_sha, name=f"expected {kind} object SHA")
    try:
        output = inputs["git_runner"].run(("hash-object", "-t", kind, "-w", "--stdin"), cwd=Path(inputs["workspace_root"]), stdin=payload, maximum=128, timeout_seconds=120)
        observed = output.decode("ascii", errors="strict").strip()
    except Exception as exc:
        raise PilotExactTaskLocalCommitObjectWriteError(f"fixed {kind} object materialization failed") from exc
    _hex40(observed, name=f"materialized {kind} object SHA")
    if observed != expected_sha:
        raise PilotExactTaskLocalCommitObjectWriteError(f"materialized {kind} object SHA mismatch")
    return observed


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], Path, bytes, Path, bytes]] = {}
    def mark(receipt: Any, consumption: PilotExactTaskLocalCommitWriteConsumptionReceipt, *, lock_path: Path, lock_payload: bytes, receipt_path: Path, receipt_payload: bytes) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(consumption), lock_path, lock_payload, receipt_path, receipt_payload)
    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, consumption_ref, lock_path, lock_payload, receipt_path, receipt_payload = entry
        consumption = consumption_ref()
        if pid != os.getpid() or receipt_ref() is not receipt or consumption is None or consumption.consumption_authenticated is not True:
            return None
        try:
            if receipt.sha256 != digest:
                return None
        except (AttributeError, TypeError, ValueError):
            return None
        if _read_bound_file(lock_path) != lock_payload or _read_bound_file(receipt_path) != receipt_payload:
            return None
        return MappingProxyType({"write_consumption_receipt": consumption})
    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_object_write_authenticated, _get_live_local_commit_object_write_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitObjectWriteReceipt:
    ledger_root_path_sha256: str
    write_key_sha256: str
    write_consumption_receipt: PilotExactTaskLocalCommitWriteConsumptionReceipt
    write_consumption_receipt_sha256: str
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
    consumed_at_utc: str
    prepared_at_utc: str
    write_started_at_utc: str
    write_completed_at_utc: str
    pre_write_workspace_snapshot_sha256: str
    post_write_workspace_snapshot_sha256: str
    object_format: str
    tree_object_count: int
    tree_object_shas: tuple[str, ...]
    commit_object_sha: str
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE
    host_object_write_guard_committed: bool = True
    consumption_authenticated_at_write: bool = True
    local_commit_authorization_consumed: bool = True
    write_boundary_ready: bool = True
    exact_object_identity_revalidated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    exact_git_object_write_transaction_executed: bool = True
    tree_objects_materialized: bool = True
    commit_object_materialized: bool = True
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
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_RECEIPT_SCHEMA or self.ledger_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE or self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write receipt schema/scope/authority is unsupported")
        if type(self.write_consumption_receipt) is not PilotExactTaskLocalCommitWriteConsumptionReceipt:
            raise PilotExactTaskLocalCommitObjectWriteError("exact ADR-DC-046 write-consumption receipt is required")
        try:
            replayed = PilotExactTaskLocalCommitWriteConsumptionReceipt.from_mapping(self.write_consumption_receipt.to_dict())
        except Exception as exc:
            raise PilotExactTaskLocalCommitObjectWriteError("embedded ADR-DC-046 receipt replay validation failed") from exc
        if replayed != self.write_consumption_receipt or replayed.sha256 != self.write_consumption_receipt_sha256:
            raise PilotExactTaskLocalCommitObjectWriteError("embedded ADR-DC-046 receipt identity mismatch")
        for name in (
            "ledger_root_path_sha256", "write_key_sha256", "write_consumption_receipt_sha256", "admission_receipt_sha256",
            "authorization_proof_sha256", "authorization_sha256", "authorization_signature_sha256", "authorization_requirements_sha256",
            "requirements_key_sha256", "local_commit_object_identity_sha256", "local_commit_plan_sha256", "development_task_sha256",
            "commit_payload_sha256", "index_manifest_sha256", "commit_subject_sha256", "local_commit_nonce_sha256",
            "pre_write_workspace_snapshot_sha256", "post_write_workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha", "commit_object_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitObjectWriteError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskLocalCommitObjectWriteError("repository is invalid")
        if isinstance(self.index_entry_count, bool) or not isinstance(self.index_entry_count, int) or not 1 <= self.index_entry_count <= 1_000_000:
            raise PilotExactTaskLocalCommitObjectWriteError("index_entry_count is invalid")
        if isinstance(self.tree_object_count, bool) or not isinstance(self.tree_object_count, int) or not 1 <= self.tree_object_count <= _MAX_TREE_OBJECTS:
            raise PilotExactTaskLocalCommitObjectWriteError("tree_object_count is invalid")
        if not isinstance(self.tree_object_shas, tuple) or len(self.tree_object_shas) != self.tree_object_count or len(set(self.tree_object_shas)) != self.tree_object_count:
            raise PilotExactTaskLocalCommitObjectWriteError("tree_object_shas are invalid")
        for item in self.tree_object_shas:
            _hex40(item, name="tree_object_sha")
        if self.tree_object_shas[-1] != self.root_tree_sha:
            raise PilotExactTaskLocalCommitObjectWriteError("root tree must be the final exact tree object")
        if self.commit_object_sha != self.predicted_commit_sha:
            raise PilotExactTaskLocalCommitObjectWriteError("materialized commit object must equal the predicted commit SHA")
        if self.object_format != "sha1":
            raise PilotExactTaskLocalCommitObjectWriteError("object_format is unsupported")
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        prepared = _utc(self.prepared_at_utc, name="prepared_at_utc")
        started = _utc(self.write_started_at_utc, name="write_started_at_utc")
        completed = _utc(self.write_completed_at_utc, name="write_completed_at_utc")
        if not consumed <= prepared <= started <= completed:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write timestamps are not monotonic")
        source = self.write_consumption_receipt
        expected = {
            "write_consumption_receipt_sha256": source.sha256, "admission_receipt_sha256": source.admission_receipt_sha256,
            "authorization_proof_sha256": source.authorization_proof_sha256, "authorization_sha256": source.authorization_sha256,
            "authorization_signature_sha256": source.authorization_signature_sha256, "authorization_requirements_sha256": source.authorization_requirements_sha256,
            "requirements_key_sha256": source.requirements_key_sha256, "local_commit_object_identity_sha256": source.local_commit_object_identity_sha256,
            "local_commit_plan_sha256": source.local_commit_plan_sha256, "development_task_sha256": source.development_task_sha256,
            "task_id": source.task_id, "repository": source.repository, "base_sha": source.base_sha, "root_tree_sha": source.root_tree_sha,
            "predicted_commit_sha": source.predicted_commit_sha, "commit_payload_sha256": source.commit_payload_sha256,
            "index_manifest_sha256": source.index_manifest_sha256, "index_entry_count": source.index_entry_count,
            "commit_subject_sha256": source.commit_subject_sha256, "local_commit_nonce_sha256": source.local_commit_nonce_sha256,
            "consumed_at_utc": source.consumed_at_utc, "object_format": source.object_format,
        }
        mismatch = next((name for name, item in expected.items() if getattr(self, name) != item), None)
        if mismatch is not None:
            raise PilotExactTaskLocalCommitObjectWriteError(f"object-write receipt binding mismatch: {mismatch}")
        if self.write_key_sha256 != self.local_commit_nonce_sha256:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write key must equal the signed local-commit nonce")
        if self.pre_write_workspace_snapshot_sha256 != source.pre_consumption_workspace_snapshot_sha256 or self.post_write_workspace_snapshot_sha256 != source.pre_consumption_workspace_snapshot_sha256:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write workspace snapshot binding mismatch")
        required_true = (
            "host_object_write_guard_committed", "consumption_authenticated_at_write", "local_commit_authorization_consumed",
            "write_boundary_ready", "exact_object_identity_revalidated", "fresh_workspace_snapshot_matched",
            "exact_git_object_write_transaction_executed", "tree_objects_materialized", "commit_object_materialized",
        )
        forced_false = (
            "git_object_write_authorized", "local_ref_update_authorized", "local_commit_authorized", "local_commit_created",
            "integration_ready", "product_pilot_started", "remote_write_authorized", "push_authorized", "pr_mutation_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitObjectWriteError("required object-write evidence is not satisfied")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitObjectWriteError("object-write receipt cannot grant residual Git/ref/publication authority")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskLocalCommitObjectWriteReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitObjectWriteError("object-write receipt must be an object")
        if set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskLocalCommitObjectWriteError("object-write receipt fields mismatch")
        data = dict(value)
        source = data.get("write_consumption_receipt")
        if not isinstance(source, Mapping):
            raise PilotExactTaskLocalCommitObjectWriteError("write_consumption_receipt must be an object")
        data["write_consumption_receipt"] = PilotExactTaskLocalCommitWriteConsumptionReceipt.from_mapping(source)
        tree_shas = data.get("tree_object_shas")
        if not isinstance(tree_shas, list):
            raise PilotExactTaskLocalCommitObjectWriteError("tree_object_shas must be an array")
        data["tree_object_shas"] = tuple(tree_shas)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        result = {name: self.write_consumption_receipt.to_dict() if name == "write_consumption_receipt" else getattr(self, name) for name in self.__dataclass_fields__}
        result["tree_object_shas"] = list(self.tree_object_shas)
        return result

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def object_write_authenticated(self) -> bool:
        return _get_live_local_commit_object_write_inputs(self) is not None


class _PilotExactTaskLocalCommitObjectWriteLedger:
    """Create-once host-local guard for one exact Git object-write transaction."""
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)
    def _lock_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='object-write key')}.lock.json"
    def _receipt_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='object-write key')}.receipt.json"
    def reserve(self, *, key: str, consumption: PilotExactTaskLocalCommitWriteConsumptionReceipt, identity: PilotExactTaskLocalCommitObjectIdentity) -> tuple[Path, bytes]:
        lock = self._lock_path(key)
        payload = _canonical({
            "schema": "kaliv-rsi-dc-l16-exact-task-local-commit-object-write-lock/v1",
            "ledger_scope": PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE,
            "ledger_root_path_sha256": self.root_sha256, "write_key_sha256": key,
            "write_consumption_receipt_sha256": consumption.sha256,
            "local_commit_object_identity_sha256": identity.sha256,
            "root_tree_sha": identity.root_tree_sha, "predicted_commit_sha": identity.predicted_commit_sha,
            "commit_payload_sha256": identity.commit_payload_sha256, "index_manifest_sha256": identity.index_manifest_sha256,
        }).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitObjectWriteError("exact local-commit object-write transaction was already reserved") from exc
        if _read_bound_file(lock) != payload:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write guard read-back mismatch")
        return lock, payload
    def publish(self, *, key: str, receipt: PilotExactTaskLocalCommitObjectWriteReceipt) -> tuple[Path, bytes]:
        path = self._receipt_path(key)
        payload = receipt.canonical_json().encode("utf-8")
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write receipt exceeds byte bound")
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write receipt publication failed closed") from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskLocalCommitObjectWriteError("object-write receipt read-back mismatch")
        parsed = PilotExactTaskLocalCommitObjectWriteReceipt.from_mapping(json.loads(payload.decode("utf-8", errors="strict")))
        if parsed != receipt or parsed.sha256 != receipt.sha256:
            raise PilotExactTaskLocalCommitObjectWriteError("published object-write receipt identity mismatch")
        return path, payload


def _materialize_verified_pilot_exact_task_local_commit_objects(*, write_consumption_receipt: PilotExactTaskLocalCommitWriteConsumptionReceipt, ledger: _PilotExactTaskLocalCommitObjectWriteLedger, now_provider: Callable[[], str]) -> PilotExactTaskLocalCommitObjectWriteReceipt:
    consumption, identity, inputs = _require_live_consumption(write_consumption_receipt)
    pre, _index_payload, entries, commit_payload = _fresh_identity_state(consumption, identity, inputs)
    tree_plan = _tree_object_plan(entries)
    if tree_plan[-1][0] != identity.root_tree_sha or identity_boundary._git_sha1("commit", commit_payload) != identity.predicted_commit_sha:
        raise PilotExactTaskLocalCommitObjectWriteError("fixed Git object-write plan does not match ADR-DC-042 identity")
    prepared_at = now_provider()
    if _utc(prepared_at, name="prepared_at_utc") < _utc(consumption.consumed_at_utc, name="consumed_at_utc"):
        raise PilotExactTaskLocalCommitObjectWriteError("object-write preparation predates ADR-DC-046 consumption")
    _take_consumption_provenance(consumption)
    key = _hex64(consumption.local_commit_nonce_sha256, name="local_commit_nonce_sha256")
    lock_path, lock_payload = ledger.reserve(key=key, consumption=consumption, identity=identity)
    post_lock, _post_index, post_entries, post_commit_payload = _fresh_identity_state(consumption, identity, inputs)
    if post_lock != pre or post_lock.sha256 != pre.sha256 or post_entries != entries or post_commit_payload != commit_payload:
        raise PilotExactTaskLocalCommitObjectWriteError("workspace/object identity changed after durable object-write guard; authorization remains burned")
    write_started_at = now_provider()
    if _utc(write_started_at, name="write_started_at_utc") < _utc(prepared_at, name="prepared_at_utc"):
        raise PilotExactTaskLocalCommitObjectWriteError("object-write clock moved backwards after durable guard")
    observed_tree_shas: list[str] = []
    for expected_sha, payload in tree_plan:
        observed_tree_shas.append(_hash_object_write(inputs=inputs, kind="tree", payload=payload, expected_sha=expected_sha))
    commit_object_sha = _hash_object_write(inputs=inputs, kind="commit", payload=commit_payload, expected_sha=identity.predicted_commit_sha)
    post_write, _final_index, final_entries, final_commit_payload = _fresh_identity_state(consumption, identity, inputs)
    if post_write != pre or post_write.sha256 != pre.sha256 or final_entries != entries or final_commit_payload != commit_payload:
        raise PilotExactTaskLocalCommitObjectWriteError("workspace/object identity changed after Git object writes; authorization remains burned")
    write_completed_at = now_provider()
    if _utc(write_completed_at, name="write_completed_at_utc") < _utc(write_started_at, name="write_started_at_utc"):
        raise PilotExactTaskLocalCommitObjectWriteError("object-write clock moved backwards after Git object materialization")
    receipt = PilotExactTaskLocalCommitObjectWriteReceipt(
        ledger_root_path_sha256=ledger.root_sha256, write_key_sha256=key,
        write_consumption_receipt=consumption, write_consumption_receipt_sha256=consumption.sha256,
        admission_receipt_sha256=consumption.admission_receipt_sha256, authorization_proof_sha256=consumption.authorization_proof_sha256,
        authorization_sha256=consumption.authorization_sha256, authorization_signature_sha256=consumption.authorization_signature_sha256,
        authorization_requirements_sha256=consumption.authorization_requirements_sha256, requirements_key_sha256=consumption.requirements_key_sha256,
        local_commit_object_identity_sha256=identity.sha256, local_commit_plan_sha256=identity.local_commit_plan_sha256,
        development_task_sha256=identity.development_task_sha256, task_id=identity.task_id, repository=identity.repository,
        base_sha=identity.base_sha, root_tree_sha=identity.root_tree_sha, predicted_commit_sha=identity.predicted_commit_sha,
        commit_payload_sha256=identity.commit_payload_sha256, index_manifest_sha256=identity.index_manifest_sha256,
        index_entry_count=identity.index_entry_count, commit_subject_sha256=identity.commit_subject_sha256,
        local_commit_nonce_sha256=consumption.local_commit_nonce_sha256, consumed_at_utc=consumption.consumed_at_utc,
        prepared_at_utc=prepared_at, write_started_at_utc=write_started_at, write_completed_at_utc=write_completed_at,
        pre_write_workspace_snapshot_sha256=pre.sha256, post_write_workspace_snapshot_sha256=post_write.sha256,
        object_format=identity.object_format, tree_object_count=len(observed_tree_shas), tree_object_shas=tuple(observed_tree_shas),
        commit_object_sha=commit_object_sha,
    )
    receipt_path, receipt_payload = ledger.publish(key=key, receipt=receipt)
    _mark_object_write_authenticated(receipt, consumption, lock_path=lock_path, lock_payload=lock_payload, receipt_path=receipt_path, receipt_payload=receipt_payload)
    if receipt.object_write_authenticated is not True:
        raise PilotExactTaskLocalCommitObjectWriteError("live exact Git object-write provenance was not established")
    return receipt


def materialize_pilot_exact_task_local_commit_objects(*, write_consumption_receipt: PilotExactTaskLocalCommitWriteConsumptionReceipt) -> PilotExactTaskLocalCommitObjectWriteReceipt:
    raise PilotExactTaskLocalCommitObjectWriteError("production local-commit object-write boundary is not installed")


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitObjectWriteError",
    "PilotExactTaskLocalCommitObjectWriteReceipt",
    "materialize_pilot_exact_task_local_commit_objects",
]
