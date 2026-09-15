"""ADR-DC-048 exact local branch ref-update transaction.

This boundary accepts only the exact live ADR-DC-047 object-write receipt,
fresh-revalidates the still-frozen candidate and exact materialized commit
object, durably commits a one-shot host-local ref-update guard, and then moves
only the current local branch ref from the exact base SHA to the exact predicted
commit SHA with Git's compare-and-swap update-ref form.

It never pushes, mutates a PR, merges, releases, deploys, or activates
production. No reusable Git/ref authority survives the transaction.
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
from . import _improvement_pilot_exact_task_local_commit_object_write_impl as _object_write_impl
from . import improvement_pilot_exact_task_local_commit_object_write as object_write_boundary
from .improvement_pilot_exact_task_local_commit_object_write import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY,
    PilotExactTaskLocalCommitObjectWriteReceipt,
)
from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .tier_a_command_receipt import _GitWorkspaceEvidence
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-ref-update-receipt/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY = (
    "host-attached-one-dc-l16-exact-local-commit-to-current-local-branch-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskLocalCommitRefUpdateError(ValueError):
    """The exact local branch ref-update transaction is unsafe or replayed."""


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
        raise PilotExactTaskLocalCommitRefUpdateError(
            "local-commit ref-update receipt is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitRefUpdateError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitRefUpdateError(f"{name} is invalid") from exc


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


def _require_live_object_write(
    value: Any,
) -> tuple[PilotExactTaskLocalCommitObjectWriteReceipt, Any, Any, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskLocalCommitObjectWriteReceipt:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "exact ADR-DC-047 local-commit object-write receipt is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitObjectWriteReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ADR-DC-047 object-write receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ADR-DC-047 object-write receipt identity mismatch"
        )
    required_true = (
        "host_object_write_guard_committed",
        "consumption_authenticated_at_write",
        "local_commit_authorization_consumed",
        "write_boundary_ready",
        "exact_object_identity_revalidated",
        "fresh_workspace_snapshot_matched",
        "exact_git_object_write_transaction_executed",
        "tree_objects_materialized",
        "commit_object_materialized",
    )
    forced_false = (
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
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_WRITE_AUTHORITY
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.object_write_authenticated is not True
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ref update requires the exact live ADR-DC-047 object-write receipt"
        )
    live = object_write_boundary._get_live_local_commit_object_write_inputs(value)
    if live is None:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ADR-DC-047 live object-write inputs are unavailable"
        )
    consumption = live.get("write_consumption_receipt")
    if consumption is None:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ADR-DC-047 live write-consumption provenance is unavailable"
        )
    try:
        _exact_consumption, identity, inputs = _object_write_impl._require_live_consumption(
            consumption
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ADR-DC-047 live identity binding is unavailable"
        ) from exc
    if (
        identity.sha256 != value.local_commit_object_identity_sha256
        or identity.base_sha != value.base_sha
        or identity.root_tree_sha != value.root_tree_sha
        or identity.predicted_commit_sha != value.predicted_commit_sha
        or value.commit_object_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ADR-DC-047 receipt no longer matches its exact live object identity"
        )
    return value, consumption, identity, inputs


def _validate_local_branch_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("refs/heads/"):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "HEAD must point to one canonical local branch ref"
        )
    branch = value[len("refs/heads/") :]
    if (
        not branch
        or len(value.encode("utf-8")) > 1024
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or value.endswith("/")
        or value.endswith(".")
        or value.endswith(".lock")
        or value.startswith("/")
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(char in value for char in ("\\", ":", "?", "*", "[", "~", "^"))
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "current local branch ref is non-canonical"
        )
    return value


def _read_ref_state(
    inputs: Mapping[str, Any],
    *,
    expected_sha: str,
) -> str:
    _hex40(expected_sha, name="expected local branch SHA")
    workspace = Path(inputs["workspace_root"])
    runner = inputs["git_runner"]
    try:
        raw_ref = runner.run(
            ("symbolic-ref", "-q", "HEAD"),
            cwd=workspace,
            maximum=2048,
            timeout_seconds=120,
        )
        target_ref = _validate_local_branch_ref(
            raw_ref.decode("utf-8", errors="strict").strip()
        )
        runner.run(
            ("check-ref-format", target_ref),
            cwd=workspace,
            maximum=128,
            timeout_seconds=120,
        )
        raw_ref_sha = runner.run(
            ("rev-parse", "--verify", target_ref),
            cwd=workspace,
            maximum=128,
            timeout_seconds=120,
        )
        raw_head_sha = runner.run(
            ("rev-parse", "HEAD"),
            cwd=workspace,
            maximum=128,
            timeout_seconds=120,
        )
        ref_sha = raw_ref_sha.decode("ascii", errors="strict").strip()
        head_sha = raw_head_sha.decode("ascii", errors="strict").strip()
    except Exception as exc:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "current local branch ref evidence collection failed"
        ) from exc
    _hex40(ref_sha, name="current local branch SHA")
    _hex40(head_sha, name="current HEAD SHA")
    if ref_sha != expected_sha or head_sha != expected_sha:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "current local branch/HEAD does not match the exact expected SHA"
        )
    return target_ref


def _verify_materialized_commit(
    object_write: PilotExactTaskLocalCommitObjectWriteReceipt,
    inputs: Mapping[str, Any],
) -> None:
    workspace = Path(inputs["workspace_root"])
    runner = inputs["git_runner"]
    try:
        commit_type = runner.run(
            ("cat-file", "-t", object_write.predicted_commit_sha),
            cwd=workspace,
            maximum=128,
            timeout_seconds=120,
        ).decode("ascii", errors="strict").strip()
        tree_type = runner.run(
            ("cat-file", "-t", object_write.root_tree_sha),
            cwd=workspace,
            maximum=128,
            timeout_seconds=120,
        ).decode("ascii", errors="strict").strip()
    except Exception as exc:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "materialized exact Git object verification failed"
        ) from exc
    if commit_type != "commit" or tree_type != "tree":
        raise PilotExactTaskLocalCommitRefUpdateError(
            "materialized exact commit/tree object type mismatch"
        )


_claim_lock = threading.Lock()
_claimed_object_writes: dict[
    tuple[int, int], tuple[str, weakref.ReferenceType[Any]]
] = {}


def _take_object_write_provenance(
    receipt: PilotExactTaskLocalCommitObjectWriteReceipt,
) -> None:
    if receipt.object_write_authenticated is not True:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ADR-DC-047 live object-write provenance is unavailable"
        )
    key = (os.getpid(), id(receipt))
    with _claim_lock:
        prior = _claimed_object_writes.get(key)
        if prior is not None and prior[1]() is receipt:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ADR-DC-047 live object-write provenance was already taken"
            )

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            with _claim_lock:
                _claimed_object_writes.pop(key, None)

        _claimed_object_writes[key] = (
            receipt.sha256,
            weakref.ref(receipt, cleanup),
        )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_claimed_object_writes.clear)


def _post_commit_workspace_snapshot(
    inputs: Mapping[str, Any],
    *,
    predicted_commit_sha: str,
):
    try:
        snapshot = _GitWorkspaceEvidence(
            Path(inputs["workspace_root"]),
            inputs["task"],
            inputs["git_runner"],
        ).snapshot()
    except Exception as exc:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "post-ref-update workspace snapshot failed"
        ) from exc
    if (
        snapshot.head_sha != predicted_commit_sha
        or snapshot.staged_patch_bytes != 0
        or snapshot.unstaged_patch_bytes != 0
        or snapshot.untracked_path_count != 0
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "local branch ref update did not produce the exact clean committed workspace"
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
            Path,
            bytes,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: Any,
        object_write: PilotExactTaskLocalCommitObjectWriteReceipt,
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
            weakref.ref(object_write),
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
            object_write_ref,
            lock_path,
            lock_payload,
            receipt_path,
            receipt_payload,
        ) = entry
        object_write = object_write_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or object_write is None
            or object_write.object_write_authenticated is not True
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
        return MappingProxyType({"object_write_receipt": object_write})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_ref_update_authenticated, _get_live_local_commit_ref_update_inputs = (
    _live_registry()
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitRefUpdateReceipt:
    ledger_root_path_sha256: str
    ref_update_key_sha256: str
    object_write_receipt: PilotExactTaskLocalCommitObjectWriteReceipt
    object_write_receipt_sha256: str
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
    object_write_completed_at_utc: str
    prepared_at_utc: str
    ref_update_started_at_utc: str
    ref_update_completed_at_utc: str
    target_ref: str
    expected_old_sha: str
    new_commit_sha: str
    pre_ref_update_workspace_snapshot_sha256: str
    post_ref_update_workspace_snapshot_sha256: str
    object_format: str
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE
    host_ref_update_guard_committed: bool = True
    object_write_authenticated_at_ref_update: bool = True
    exact_commit_object_verified: bool = True
    current_local_branch_ref_verified: bool = True
    compare_and_swap_ref_update_executed: bool = True
    local_ref_updated: bool = True
    local_commit_created: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_RECEIPT_SCHEMA
            or self.ledger_scope
            != PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE
            or self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY
        ):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update receipt schema/scope/authority is unsupported"
            )
        if type(self.object_write_receipt) is not PilotExactTaskLocalCommitObjectWriteReceipt:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "exact ADR-DC-047 object-write receipt is required"
            )
        try:
            replayed = PilotExactTaskLocalCommitObjectWriteReceipt.from_mapping(
                self.object_write_receipt.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "embedded ADR-DC-047 receipt replay validation failed"
            ) from exc
        if (
            replayed != self.object_write_receipt
            or replayed.sha256 != self.object_write_receipt_sha256
        ):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "embedded ADR-DC-047 receipt identity mismatch"
            )
        for name in (
            "ledger_root_path_sha256",
            "ref_update_key_sha256",
            "object_write_receipt_sha256",
            "write_consumption_receipt_sha256",
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
            "pre_ref_update_workspace_snapshot_sha256",
            "post_ref_update_workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "base_sha",
            "root_tree_sha",
            "predicted_commit_sha",
            "expected_old_sha",
            "new_commit_sha",
        ):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitRefUpdateError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskLocalCommitRefUpdateError("repository is invalid")
        if (
            isinstance(self.index_entry_count, bool)
            or not isinstance(self.index_entry_count, int)
            or not 1 <= self.index_entry_count <= 1_000_000
        ):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "index_entry_count is invalid"
            )
        _validate_local_branch_ref(self.target_ref)
        if self.object_format != "sha1":
            raise PilotExactTaskLocalCommitRefUpdateError(
                "object_format is unsupported"
            )
        source = self.object_write_receipt
        expected = {
            "object_write_receipt_sha256": source.sha256,
            "write_consumption_receipt_sha256": source.write_consumption_receipt_sha256,
            "admission_receipt_sha256": source.admission_receipt_sha256,
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
            "object_write_completed_at_utc": source.write_completed_at_utc,
            "object_format": source.object_format,
        }
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskLocalCommitRefUpdateError(
                f"ref-update receipt binding mismatch: {mismatch}"
            )
        if self.ref_update_key_sha256 != self.local_commit_nonce_sha256:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update key must equal the signed local-commit nonce"
            )
        if self.expected_old_sha != self.base_sha:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update old SHA must equal exact base SHA"
            )
        if self.new_commit_sha != self.predicted_commit_sha:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update new SHA must equal exact predicted commit SHA"
            )
        if (
            self.pre_ref_update_workspace_snapshot_sha256
            != source.post_write_workspace_snapshot_sha256
        ):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "pre-ref-update workspace must equal ADR-DC-047 post-write evidence"
            )
        if (
            self.post_ref_update_workspace_snapshot_sha256
            == self.pre_ref_update_workspace_snapshot_sha256
        ):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "post-ref-update workspace evidence must reflect the committed HEAD"
            )
        prepared = _utc(self.prepared_at_utc, name="prepared_at_utc")
        started = _utc(
            self.ref_update_started_at_utc,
            name="ref_update_started_at_utc",
        )
        completed = _utc(
            self.ref_update_completed_at_utc,
            name="ref_update_completed_at_utc",
        )
        object_completed = _utc(
            self.object_write_completed_at_utc,
            name="object_write_completed_at_utc",
        )
        if not object_completed <= prepared <= started <= completed:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update timestamps are not monotonic"
            )
        required_true = (
            "host_ref_update_guard_committed",
            "object_write_authenticated_at_ref_update",
            "exact_commit_object_verified",
            "current_local_branch_ref_verified",
            "compare_and_swap_ref_update_executed",
            "local_ref_updated",
            "local_commit_created",
        )
        forced_false = (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
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
            raise PilotExactTaskLocalCommitRefUpdateError(
                "required local-commit ref-update evidence is not satisfied"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update receipt cannot grant residual Git/publication authority"
            )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskLocalCommitRefUpdateReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update receipt must be an object"
            )
        if set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update receipt fields mismatch"
            )
        data = dict(value)
        source = data.get("object_write_receipt")
        if not isinstance(source, Mapping):
            raise PilotExactTaskLocalCommitRefUpdateError(
                "object_write_receipt must be an object"
            )
        data["object_write_receipt"] = (
            PilotExactTaskLocalCommitObjectWriteReceipt.from_mapping(source)
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: (
                self.object_write_receipt.to_dict()
                if name == "object_write_receipt"
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
    def ref_update_authenticated(self) -> bool:
        return _get_live_local_commit_ref_update_inputs(self) is not None


class _PilotExactTaskLocalCommitRefUpdateLedger:
    """Create-once host-local guard for one exact local branch ref update."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _lock_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='ref-update key')}.lock.json"

    def _receipt_path(self, key: str) -> Path:
        return self.root / f"{_hex64(key, name='ref-update key')}.receipt.json"

    def reserve(
        self,
        *,
        key: str,
        object_write: PilotExactTaskLocalCommitObjectWriteReceipt,
        target_ref: str,
    ) -> tuple[Path, bytes]:
        lock = self._lock_path(key)
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-local-commit-ref-update-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "ref_update_key_sha256": key,
                "object_write_receipt_sha256": object_write.sha256,
                "target_ref": _validate_local_branch_ref(target_ref),
                "expected_old_sha": object_write.base_sha,
                "new_commit_sha": object_write.predicted_commit_sha,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "exact local-commit ref-update transaction was already reserved"
            ) from exc
        if _read_bound_file(lock) != payload:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update guard read-back mismatch"
            )
        return lock, payload

    def publish(
        self,
        *,
        key: str,
        receipt: PilotExactTaskLocalCommitRefUpdateReceipt,
    ) -> tuple[Path, bytes]:
        path = self._receipt_path(key)
        payload = receipt.canonical_json().encode("utf-8")
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update receipt publication failed closed"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "ref-update receipt read-back mismatch"
            )
        parsed = PilotExactTaskLocalCommitRefUpdateReceipt.from_mapping(
            json.loads(payload.decode("utf-8", errors="strict"))
        )
        if parsed != receipt or parsed.sha256 != receipt.sha256:
            raise PilotExactTaskLocalCommitRefUpdateError(
                "published ref-update receipt identity mismatch"
            )
        return path, payload


def _attach_verified_pilot_exact_task_local_commit(
    *,
    object_write_receipt: PilotExactTaskLocalCommitObjectWriteReceipt,
    ledger: _PilotExactTaskLocalCommitRefUpdateLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskLocalCommitRefUpdateReceipt:
    object_write, _consumption, identity, inputs = _require_live_object_write(
        object_write_receipt
    )
    pre_snapshot, _index_payload, _entries, _commit_payload = (
        _object_write_impl._fresh_identity_state(
            object_write.write_consumption_receipt,
            identity,
            inputs,
        )
    )
    target_ref = _read_ref_state(inputs, expected_sha=object_write.base_sha)
    _verify_materialized_commit(object_write, inputs)
    prepared_at = now_provider()
    if _utc(prepared_at, name="prepared_at_utc") < _utc(
        object_write.write_completed_at_utc,
        name="object_write_completed_at_utc",
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ref-update preparation predates ADR-DC-047 object write"
        )

    _take_object_write_provenance(object_write)
    key = _hex64(
        object_write.local_commit_nonce_sha256,
        name="local_commit_nonce_sha256",
    )
    lock_path, lock_payload = ledger.reserve(
        key=key,
        object_write=object_write,
        target_ref=target_ref,
    )

    post_guard_snapshot, _post_index, post_entries, post_commit_payload = (
        _object_write_impl._fresh_identity_state(
            object_write.write_consumption_receipt,
            identity,
            inputs,
        )
    )
    if (
        post_guard_snapshot != pre_snapshot
        or post_guard_snapshot.sha256 != pre_snapshot.sha256
        or identity_boundary._root_tree_sha(post_entries) != object_write.root_tree_sha
        or identity_boundary._git_sha1("commit", post_commit_payload)
        != object_write.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "workspace/object identity changed after durable ref-update guard; "
            "authorization remains burned"
        )
    if _read_ref_state(inputs, expected_sha=object_write.base_sha) != target_ref:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "current local branch ref changed after durable ref-update guard"
        )
    _verify_materialized_commit(object_write, inputs)

    ref_update_started_at = now_provider()
    if _utc(
        ref_update_started_at,
        name="ref_update_started_at_utc",
    ) < _utc(prepared_at, name="prepared_at_utc"):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ref-update clock moved backwards after durable guard"
        )

    try:
        output = inputs["git_runner"].run(
            (
                "update-ref",
                target_ref,
                object_write.predicted_commit_sha,
                object_write.base_sha,
            ),
            cwd=Path(inputs["workspace_root"]),
            maximum=128,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "exact compare-and-swap local branch ref update failed; "
            "authorization remains burned"
        ) from exc
    if output not in (b"", b"\n"):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "local branch ref update returned unexpected output"
        )

    if (
        _read_ref_state(
            inputs,
            expected_sha=object_write.predicted_commit_sha,
        )
        != target_ref
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "local branch ref did not settle on the exact predicted commit"
        )
    _verify_materialized_commit(object_write, inputs)
    post_snapshot = _post_commit_workspace_snapshot(
        inputs,
        predicted_commit_sha=object_write.predicted_commit_sha,
    )

    ref_update_completed_at = now_provider()
    if _utc(
        ref_update_completed_at,
        name="ref_update_completed_at_utc",
    ) < _utc(
        ref_update_started_at,
        name="ref_update_started_at_utc",
    ):
        raise PilotExactTaskLocalCommitRefUpdateError(
            "ref-update clock moved backwards after local commit creation"
        )

    receipt = PilotExactTaskLocalCommitRefUpdateReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        ref_update_key_sha256=key,
        object_write_receipt=object_write,
        object_write_receipt_sha256=object_write.sha256,
        write_consumption_receipt_sha256=object_write.write_consumption_receipt_sha256,
        admission_receipt_sha256=object_write.admission_receipt_sha256,
        authorization_proof_sha256=object_write.authorization_proof_sha256,
        authorization_sha256=object_write.authorization_sha256,
        authorization_signature_sha256=object_write.authorization_signature_sha256,
        authorization_requirements_sha256=object_write.authorization_requirements_sha256,
        requirements_key_sha256=object_write.requirements_key_sha256,
        local_commit_object_identity_sha256=object_write.local_commit_object_identity_sha256,
        local_commit_plan_sha256=object_write.local_commit_plan_sha256,
        development_task_sha256=object_write.development_task_sha256,
        task_id=object_write.task_id,
        repository=object_write.repository,
        base_sha=object_write.base_sha,
        root_tree_sha=object_write.root_tree_sha,
        predicted_commit_sha=object_write.predicted_commit_sha,
        commit_payload_sha256=object_write.commit_payload_sha256,
        index_manifest_sha256=object_write.index_manifest_sha256,
        index_entry_count=object_write.index_entry_count,
        commit_subject_sha256=object_write.commit_subject_sha256,
        local_commit_nonce_sha256=object_write.local_commit_nonce_sha256,
        object_write_completed_at_utc=object_write.write_completed_at_utc,
        prepared_at_utc=prepared_at,
        ref_update_started_at_utc=ref_update_started_at,
        ref_update_completed_at_utc=ref_update_completed_at,
        target_ref=target_ref,
        expected_old_sha=object_write.base_sha,
        new_commit_sha=object_write.predicted_commit_sha,
        pre_ref_update_workspace_snapshot_sha256=pre_snapshot.sha256,
        post_ref_update_workspace_snapshot_sha256=post_snapshot.sha256,
        object_format=object_write.object_format,
    )
    receipt_path, receipt_payload = ledger.publish(key=key, receipt=receipt)
    _mark_ref_update_authenticated(
        receipt,
        object_write,
        lock_path=lock_path,
        lock_payload=lock_payload,
        receipt_path=receipt_path,
        receipt_payload=receipt_payload,
    )
    if receipt.ref_update_authenticated is not True:
        raise PilotExactTaskLocalCommitRefUpdateError(
            "live exact local-commit ref-update provenance was not established"
        )
    return receipt


def attach_pilot_exact_task_local_commit(
    *,
    object_write_receipt: PilotExactTaskLocalCommitObjectWriteReceipt,
) -> PilotExactTaskLocalCommitRefUpdateReceipt:
    raise PilotExactTaskLocalCommitRefUpdateError(
        "production local-commit ref-update boundary is not installed"
    )


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_RECEIPT_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitRefUpdateError",
    "PilotExactTaskLocalCommitRefUpdateReceipt",
    "attach_pilot_exact_task_local_commit",
]
