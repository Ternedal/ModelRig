"""ADR-DC-044 one-shot exact local commit transaction.

This is the first RSI pilot boundary permitted to write Git objects and move one
local branch ref.  It accepts only the exact live ADR-DC-043 write authorization,
permanently consumes a separate host-local transaction slot, repeatedly
revalidates the frozen candidate, writes only the already predicted tree/commit
objects, and compare-and-swap updates exactly one local refs/heads/* ref.

No remote, push, PR mutation, merge, release, deploy or production activation
operation exists here.
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
from . import improvement_pilot_exact_task_local_commit_write_authorization as authorization_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PilotExactTaskLocalCommitObjectIdentity,
)
from .improvement_pilot_exact_task_local_commit_write_authorization import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_AUTHORITY,
    PilotExactTaskLocalCommitWriteAuthorizationReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-transaction-receipt/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_AUTHORITY = (
    "host-created-one-dc-l16-exact-local-commit-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_ARTIFACT_BYTES = 1024 * 1024
_MAX_COMMIT_PAYLOAD_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_HEAD_REF = re.compile(r"^refs/heads/[A-Za-z0-9._/-]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-local-commit-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-local-commit-transaction-ledger-v1"
)


class PilotExactTaskLocalCommitTransactionError(ValueError):
    """The exact one-shot local commit transaction is replayed or unsafe."""


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
        raise PilotExactTaskLocalCommitTransactionError(
            "local commit transaction is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskLocalCommitTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitTransactionError(f"{name} is invalid") from exc


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


def _local_head_ref(value: Any) -> str:
    if (
        not isinstance(value, str)
        or _HEAD_REF.fullmatch(value) is None
        or len(value) > 255
        or ".." in value
        or "//" in value
        or "@{" in value
        or value.endswith("/")
    ):
        raise PilotExactTaskLocalCommitTransactionError("local HEAD ref is invalid")
    components = value[len("refs/heads/") :].split("/")
    if any(
        not component
        or component.startswith(".")
        or component.endswith(".")
        or component.endswith(".lock")
        for component in components
    ):
        raise PilotExactTaskLocalCommitTransactionError("local HEAD ref is non-canonical")
    return value


def _require_live_authorization(
    value: Any,
) -> tuple[
    PilotExactTaskLocalCommitWriteAuthorizationReceipt,
    PilotExactTaskLocalCommitObjectIdentity,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskLocalCommitWriteAuthorizationReceipt:
        raise PilotExactTaskLocalCommitTransactionError(
            "exact ADR-DC-043 local commit write authorization is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitWriteAuthorizationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "ADR-DC-043 write authorization replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitTransactionError(
            "ADR-DC-043 write authorization identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_AUTHORIZATION_AUTHORITY
        or value.authorization_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.local_commit_object_identity_authenticated is not True
        or value.fresh_workspace_snapshot_matched is not True
        or value.fresh_index_manifest_matched is not True
        or value.exact_commit_identity_revalidated is not True
        or value.local_commit_write_authority_reserved is not True
        or value.one_shot_local_commit_write_required is not True
        or value.git_object_write_authorized is not True
        or value.local_ref_update_authorized is not True
        or value.local_commit_authorized is not True
        or value.local_commit_created is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitTransactionError(
            "transaction requires one live unused ADR-DC-043 authorization"
        )
    inputs = authorization_boundary._get_live_local_commit_write_authorization_inputs(
        value
    )
    if inputs is None:
        raise PilotExactTaskLocalCommitTransactionError(
            "ADR-DC-043 live authorization inputs are unavailable"
        )
    identity = inputs.get("local_commit_object_identity")
    if (
        type(identity) is not PilotExactTaskLocalCommitObjectIdentity
        or identity.identity_authenticated is not True
        or identity.sha256 != value.local_commit_object_identity_sha256
        or identity.local_commit_plan_sha256 != value.local_commit_plan_sha256
        or identity.execution_nonce_sha256 != value.execution_nonce_sha256
        or identity.development_task_sha256 != value.development_task_sha256
        or identity.task_id != value.task_id
        or identity.repository != value.repository
        or identity.base_sha != value.base_sha
        or identity.candidate_patch_sha256 != value.candidate_patch_sha256
        or identity.index_manifest_sha256 != value.index_manifest_sha256
        or identity.root_tree_sha != value.root_tree_sha
        or identity.commit_payload_sha256 != value.commit_payload_sha256
        or identity.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitTransactionError(
            "ADR-DC-043 authorization is not bound to its exact live identity"
        )
    return value, identity, inputs


def _git_sha_output(raw: bytes, *, name: str) -> str:
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise PilotExactTaskLocalCommitTransactionError(f"{name} is not ASCII") from exc
    return _hex40(value, name=name)


def _read_local_head_ref(inputs: Mapping[str, Any]) -> str:
    try:
        raw = inputs["git_runner"].run(
            ("symbolic-ref", "-q", "HEAD"),
            cwd=Path(inputs["workspace_root"]),
            maximum=512,
            timeout_seconds=120,
        )
        value = raw.decode("ascii", errors="strict").strip()
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "local HEAD symbolic ref collection failed"
        ) from exc
    return _local_head_ref(value)


def _read_ref_sha(inputs: Mapping[str, Any], ref: str) -> str:
    ref = _local_head_ref(ref)
    try:
        raw = inputs["git_runner"].run(
            ("rev-parse", "--verify", ref),
            cwd=Path(inputs["workspace_root"]),
            maximum=128,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "local branch ref identity collection failed"
        ) from exc
    return _git_sha_output(raw, name="local branch ref SHA")


def _fresh_prewrite_revalidation(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
    *,
    expected_ref: str | None = None,
) -> str:
    try:
        authorization_boundary._fresh_revalidate_exact_identity(identity, inputs)
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "fresh exact commit identity prewrite revalidation failed"
        ) from exc
    ref = _read_local_head_ref(inputs)
    if expected_ref is not None and ref != _local_head_ref(expected_ref):
        raise PilotExactTaskLocalCommitTransactionError(
            "local HEAD ref changed during commit transaction"
        )
    if _read_ref_sha(inputs, ref) != identity.base_sha:
        raise PilotExactTaskLocalCommitTransactionError(
            "local branch ref no longer equals exact commit base"
        )
    return ref


def _commit_payload(identity: PilotExactTaskLocalCommitObjectIdentity) -> bytes:
    try:
        payload = identity_boundary._commit_payload(
            tree_sha=identity.root_tree_sha,
            parent_sha=identity.base_sha,
            subject=identity.commit_subject,
            epoch_seconds=identity.commit_epoch_seconds,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "exact commit payload reconstruction failed"
        ) from exc
    if (
        not payload
        or len(payload) > _MAX_COMMIT_PAYLOAD_BYTES
        or hashlib.sha256(payload).hexdigest() != identity.commit_payload_sha256
        or identity_boundary._git_sha1("commit", payload) != identity.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitTransactionError(
            "exact commit payload no longer matches ADR-DC-042 identity"
        )
    return payload


def _write_exact_tree(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> None:
    try:
        raw = inputs["git_runner"].run(
            ("write-tree",),
            cwd=Path(inputs["workspace_root"]),
            maximum=128,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "exact Git tree write failed"
        ) from exc
    if _git_sha_output(raw, name="written root tree SHA") != identity.root_tree_sha:
        raise PilotExactTaskLocalCommitTransactionError(
            "written Git tree does not match ADR-DC-042 root tree"
        )


def _write_exact_commit_object(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
    payload: bytes,
) -> None:
    try:
        raw = inputs["git_runner"].run(
            ("hash-object", "-t", "commit", "-w", "--stdin"),
            cwd=Path(inputs["workspace_root"]),
            stdin=payload,
            maximum=128,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "exact Git commit object write failed"
        ) from exc
    if _git_sha_output(raw, name="written commit object SHA") != identity.predicted_commit_sha:
        raise PilotExactTaskLocalCommitTransactionError(
            "written Git commit object does not match ADR-DC-042 identity"
        )


def _read_exact_commit_payload(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> bytes:
    try:
        kind = inputs["git_runner"].run(
            ("cat-file", "-t", identity.predicted_commit_sha),
            cwd=Path(inputs["workspace_root"]),
            maximum=128,
            timeout_seconds=120,
        )
        payload = inputs["git_runner"].run(
            ("cat-file", "commit", identity.predicted_commit_sha),
            cwd=Path(inputs["workspace_root"]),
            maximum=_MAX_COMMIT_PAYLOAD_BYTES,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "written Git commit object verification failed"
        ) from exc
    if kind != b"commit\n":
        raise PilotExactTaskLocalCommitTransactionError(
            "written Git object is not a commit"
        )
    return payload


def _compare_and_swap_local_ref(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
    ref: str,
) -> None:
    ref = _local_head_ref(ref)
    try:
        output = inputs["git_runner"].run(
            ("update-ref", ref, identity.predicted_commit_sha, identity.base_sha),
            cwd=Path(inputs["workspace_root"]),
            maximum=4096,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "local branch compare-and-swap update failed"
        ) from exc
    if output != b"":
        raise PilotExactTaskLocalCommitTransactionError(
            "local branch compare-and-swap produced unexpected output"
        )


def _post_commit_verify(
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
    ref: str,
    payload: bytes,
) -> None:
    ref = _local_head_ref(ref)
    runner = inputs["git_runner"]
    cwd = Path(inputs["workspace_root"])
    try:
        symbolic = runner.run(
            ("symbolic-ref", "-q", "HEAD"),
            cwd=cwd,
            maximum=512,
            timeout_seconds=120,
        ).decode("ascii", errors="strict").strip()
        head = runner.run(
            ("rev-parse", "--verify", "HEAD"),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        )
        direct_ref = runner.run(
            ("rev-parse", "--verify", ref),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        )
        cached = runner.run(
            (
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            ),
            cwd=cwd,
            maximum=32 * 1024 * 1024,
            timeout_seconds=120,
        )
        unstaged = runner.run(
            (
                "diff",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            ),
            cwd=cwd,
            maximum=32 * 1024 * 1024,
            timeout_seconds=120,
        )
        untracked = runner.run(
            ("ls-files", "--others", "--exclude-standard", "-z"),
            cwd=cwd,
            maximum=32 * 1024 * 1024,
            timeout_seconds=120,
        )
        index_payload = identity_boundary._read_index_manifest(inputs)
        written_payload = _read_exact_commit_payload(identity, inputs)
    except Exception as exc:
        if isinstance(exc, PilotExactTaskLocalCommitTransactionError):
            raise
        raise PilotExactTaskLocalCommitTransactionError(
            "post-commit exact state verification failed"
        ) from exc

    if symbolic != ref:
        raise PilotExactTaskLocalCommitTransactionError(
            "HEAD symbolic ref changed after local commit"
        )
    if (
        _git_sha_output(head, name="post-commit HEAD SHA")
        != identity.predicted_commit_sha
        or _git_sha_output(direct_ref, name="post-commit branch SHA")
        != identity.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitTransactionError(
            "post-commit ref does not equal predicted commit"
        )
    if cached != b"":
        raise PilotExactTaskLocalCommitTransactionError(
            "index is not clean after exact local commit"
        )
    if unstaged != b"" or untracked != b"":
        raise PilotExactTaskLocalCommitTransactionError(
            "worktree is not clean after exact local commit"
        )
    if hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256:
        raise PilotExactTaskLocalCommitTransactionError(
            "Git index identity changed during local commit"
        )
    if written_payload != payload:
        raise PilotExactTaskLocalCommitTransactionError(
            "written commit payload differs from exact predicted payload"
        )


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
        authorization: PilotExactTaskLocalCommitWriteAuthorizationReceipt,
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
            weakref.ref(authorization),
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
            authorization_ref,
            identity_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        authorization = authorization_ref()
        identity = identity_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or authorization is None
            or identity is None
            or receipt.sha256 != digest
            or receipt.local_commit_write_authorization_sha256 != authorization.sha256
            or receipt.local_commit_object_identity_sha256 != identity.sha256
            or authorization.authorization_authenticated is not True
            or identity.identity_authenticated is not True
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
        ):
            return None
        inputs = authorization_boundary._get_live_local_commit_write_authorization_inputs(
            authorization
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["local_commit_write_authorization"] = authorization
        result["local_commit_object_identity"] = identity
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_local_commit_transaction_authenticated,
    _get_live_local_commit_transaction_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitTransactionReceipt:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    local_commit_write_authorization_sha256: str
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    local_head_ref: str
    candidate_patch_sha256: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    prewrite_revalidated_at_utc: str
    consumed_at_utc: str
    committed_at_utc: str
    host_replay_guard_committed: bool = True
    local_commit_write_authorization_authenticated: bool = True
    local_commit_write_authority_consumed: bool = True
    prewrite_workspace_revalidated: bool = True
    local_head_ref_bound: bool = True
    write_tree_sha_matched: bool = True
    commit_object_sha_matched: bool = True
    commit_object_payload_matched: bool = True
    local_ref_compare_and_swap_succeeded: bool = True
    post_commit_head_verified: bool = True
    post_commit_index_clean: bool = True
    post_commit_worktree_clean: bool = True
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
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_SCHEMA:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction schema is unsupported"
            )
        if self.ledger_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_LEDGER_SCOPE:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction ledger scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "transaction_key_sha256",
            "local_commit_write_authorization_sha256",
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.transaction_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction key must equal exact execution nonce"
            )
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitTransactionError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskLocalCommitTransactionError("repository is invalid")
        _local_head_ref(self.local_head_ref)
        prewrite = _utc(
            self.prewrite_revalidated_at_utc,
            name="prewrite_revalidated_at_utc",
        )
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        committed = _utc(self.committed_at_utc, name="committed_at_utc")
        if consumed < prewrite or committed < consumed:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction timestamps are non-monotonic"
            )
        required_true = (
            "host_replay_guard_committed",
            "local_commit_write_authorization_authenticated",
            "local_commit_write_authority_consumed",
            "prewrite_workspace_revalidated",
            "local_head_ref_bound",
            "write_tree_sha_matched",
            "commit_object_sha_matched",
            "commit_object_payload_matched",
            "local_ref_compare_and_swap_succeeded",
            "post_commit_head_verified",
            "post_commit_index_clean",
            "post_commit_worktree_clean",
            "local_commit_created",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction evidence is incomplete"
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
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitTransactionError(
                "completed local commit transaction cannot retain write/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_AUTHORITY:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction authority is unsupported"
            )

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_local_commit_transaction_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskLocalCommitTransactionReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(cls, text: str) -> "PilotExactTaskLocalCommitTransactionReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskLocalCommitTransactionLedger:
    """Permanent create-once transaction consumption keyed by execution nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="transaction_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def acquire(
        self,
        *,
        authorization: PilotExactTaskLocalCommitWriteAuthorizationReceipt,
        identity: PilotExactTaskLocalCommitObjectIdentity,
        local_head_ref: str,
    ) -> bytes:
        key = authorization.execution_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskLocalCommitTransactionError(
                "exact execution nonce already consumed for local commit or needs recovery"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-local-commit-transaction-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "transaction_key_sha256": key,
                "local_commit_write_authorization_sha256": authorization.sha256,
                "local_commit_object_identity_sha256": identity.sha256,
                "local_commit_plan_sha256": identity.local_commit_plan_sha256,
                "execution_nonce_sha256": identity.execution_nonce_sha256,
                "development_task_sha256": identity.development_task_sha256,
                "base_sha": identity.base_sha,
                "local_head_ref": _local_head_ref(local_head_ref),
                "root_tree_sha": identity.root_tree_sha,
                "commit_payload_sha256": identity.commit_payload_sha256,
                "predicted_commit_sha": identity.predicted_commit_sha,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction could not be durably consumed"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskLocalCommitTransactionReceipt,
        authorization: PilotExactTaskLocalCommitWriteAuthorizationReceipt,
        identity: PilotExactTaskLocalCommitObjectIdentity,
        lock_payload: bytes,
    ) -> PilotExactTaskLocalCommitTransactionReceipt:
        final, pending, lock = self._paths(receipt.transaction_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction marker changed before receipt publication"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction receipt already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskLocalCommitTransactionError(
                    "local commit transaction receipt read-back mismatch"
                )
            parsed = PilotExactTaskLocalCommitTransactionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskLocalCommitTransactionError(
                    "local commit transaction receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskLocalCommitTransactionError(
                    "local commit transaction marker changed before provenance registration"
                )
            _mark_local_commit_transaction_authenticated(
                parsed,
                authorization,
                identity,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.transaction_authenticated is not True:
                raise PilotExactTaskLocalCommitTransactionError(
                    "local commit transaction lost live transaction provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskLocalCommitTransactionError):
                raise
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit exists but durable receipt requires recovery"
            ) from exc


def _execute_verified_pilot_exact_task_local_commit(
    *,
    local_commit_write_authorization: PilotExactTaskLocalCommitWriteAuthorizationReceipt,
    ledger: _PilotExactTaskLocalCommitTransactionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskLocalCommitTransactionReceipt:
    authorization, identity, inputs = _require_live_authorization(
        local_commit_write_authorization
    )
    if type(ledger) is not _PilotExactTaskLocalCommitTransactionLedger:
        raise PilotExactTaskLocalCommitTransactionError(
            "local commit transaction ledger is required"
        )

    local_ref = _fresh_prewrite_revalidation(identity, inputs)
    prewrite_at = now_provider()
    prewrite_time = _utc(prewrite_at, name="prewrite_revalidated_at_utc")
    authorized_time = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    if prewrite_time < authorized_time:
        raise PilotExactTaskLocalCommitTransactionError(
            "system clock moved backwards after ADR-DC-043 authorization"
        )

    marker = ledger.acquire(
        authorization=authorization,
        identity=identity,
        local_head_ref=local_ref,
    )
    consumed_at = now_provider()
    consumed_time = _utc(consumed_at, name="consumed_at_utc")
    if consumed_time < prewrite_time:
        raise PilotExactTaskLocalCommitTransactionError(
            "system clock moved backwards during local commit consumption"
        )

    # Permanent consumption precedes every Git object/ref write.  Re-resolve
    # the exact live authorization and candidate after the marker exists.
    authorization_again, identity_again, inputs_again = _require_live_authorization(
        authorization
    )
    if authorization_again is not authorization or identity_again is not identity:
        raise PilotExactTaskLocalCommitTransactionError(
            "live local commit authority changed after transaction consumption"
        )
    _fresh_prewrite_revalidation(identity, inputs_again, expected_ref=local_ref)

    payload = _commit_payload(identity)

    # First mutation: write exactly the current index tree.  The returned root
    # identity must equal ADR-DC-042 before any commit object is written.
    _write_exact_tree(identity, inputs_again)

    # Tree-object writes do not change the candidate. Revalidate again so any
    # concurrent index/worktree/ref drift burns the transaction before commit write.
    _fresh_prewrite_revalidation(identity, inputs_again, expected_ref=local_ref)

    # Second mutation: write the exact canonical commit payload via stdin only.
    _write_exact_commit_object(identity, inputs_again, payload)
    if _read_exact_commit_payload(identity, inputs_again) != payload:
        raise PilotExactTaskLocalCommitTransactionError(
            "written commit object payload does not equal predicted payload"
        )

    # Commit-object creation still leaves HEAD untouched. Revalidate one final
    # time before the compare-and-swap ref mutation.
    _fresh_prewrite_revalidation(identity, inputs_again, expected_ref=local_ref)

    # Third and final mutation: atomically move only the bound local branch if
    # and only if it still points at the exact ADR-DC-042 base SHA.
    _compare_and_swap_local_ref(identity, inputs_again, local_ref)

    # After the ref move, no further mutation occurs.  Verify HEAD/ref/object,
    # unchanged index identity, and a clean index/worktree before publishing proof.
    _post_commit_verify(identity, inputs_again, local_ref, payload)

    committed_at = now_provider()
    committed_time = _utc(committed_at, name="committed_at_utc")
    if committed_time < consumed_time:
        raise PilotExactTaskLocalCommitTransactionError(
            "system clock moved backwards during local commit transaction"
        )

    receipt = PilotExactTaskLocalCommitTransactionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=identity.execution_nonce_sha256,
        local_commit_write_authorization_sha256=authorization.sha256,
        local_commit_object_identity_sha256=identity.sha256,
        local_commit_plan_sha256=identity.local_commit_plan_sha256,
        execution_nonce_sha256=identity.execution_nonce_sha256,
        development_task_sha256=identity.development_task_sha256,
        task_id=identity.task_id,
        repository=identity.repository,
        base_sha=identity.base_sha,
        local_head_ref=local_ref,
        candidate_patch_sha256=identity.candidate_patch_sha256,
        index_manifest_sha256=identity.index_manifest_sha256,
        root_tree_sha=identity.root_tree_sha,
        commit_payload_sha256=identity.commit_payload_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        prewrite_revalidated_at_utc=prewrite_at,
        consumed_at_utc=consumed_at,
        committed_at_utc=committed_at,
    )
    return ledger.commit(
        receipt=receipt,
        authorization=authorization,
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
            raise PilotExactTaskLocalCommitTransactionError(
                "local commit transaction ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "canonical local commit transaction ledger is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_local_commit(
    local_commit_write_authorization: PilotExactTaskLocalCommitWriteAuthorizationReceipt,
) -> PilotExactTaskLocalCommitTransactionReceipt:
    """Host-pinned ADR-DC-044 boundary. Create exactly one local commit only."""
    try:
        root = _canonical_ledger_root()
        ledger = _PilotExactTaskLocalCommitTransactionLedger(root)
        return _execute_verified_pilot_exact_task_local_commit(
            local_commit_write_authorization=local_commit_write_authorization,
            ledger=ledger,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskLocalCommitTransactionError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskLocalCommitTransactionError(
            "host-controlled exact local commit transaction failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_LEDGER_SCOPE",
    "PilotExactTaskLocalCommitTransactionError",
    "PilotExactTaskLocalCommitTransactionReceipt",
    "execute_pilot_exact_task_local_commit",
]
