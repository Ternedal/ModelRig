"""ADR-DC-046 exact local Git write transaction.

Consumes one live ADR-DC-045 durable reservation, revalidates the frozen
workspace/object identity, writes only the exact tree/commit objects through the
existing trusted Git runner, creates one deterministic custom local ref with a
create-only compare-and-swap, verifies the result, and emits a durable receipt.

No remote write, push, PR mutation, merge, release, deploy, production
activation, HEAD movement, checkout, reset, or clean operation is performed.
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
    PilotExactTaskLocalCommitObjectIdentity,
)
from . import improvement_pilot_exact_task_local_commit_write_reservation as reservation_boundary
from .improvement_pilot_exact_task_local_commit_write_reservation import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY,
    PilotExactTaskLocalCommitWriteReservationReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-write-transaction-receipt/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_AUTHORITY = (
    "host-completed-one-dc-l16-exact-local-commit-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_LEDGER_SCOPE = "canonical-host-local-v1"
PILOT_EXACT_TASK_LOCAL_COMMIT_REF_PREFIX = "refs/modelrig/rsi/local-commit/"
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_MAX_RESERVATION_AGE_SECONDS = 5 * 60

_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_GIT_OBJECT_BYTES = 64 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^refs/modelrig/rsi/local-commit/[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ZERO_SHA = "0" * 40

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-local-commit-write-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-local-commit-write-transaction-ledger-v1"
)


class PilotExactTaskLocalCommitWriteTransactionError(ValueError):
    """The exact local Git write transaction is unsafe, replayed, or drifted."""


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
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "local Git write transaction is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskLocalCommitWriteTransactionError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitWriteTransactionError(f"{name} is invalid")
    if not allow_zero and value == _ZERO_SHA:
        raise PilotExactTaskLocalCommitWriteTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitWriteTransactionError(
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


def _local_ref_name(local_write_nonce_sha256: str) -> str:
    nonce = _hex64(local_write_nonce_sha256, name="local_write_nonce_sha256")
    ref = f"{PILOT_EXACT_TASK_LOCAL_COMMIT_REF_PREFIX}{nonce}"
    if _REF.fullmatch(ref) is None:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "host-pinned local candidate ref is invalid"
        )
    return ref


def _require_live_reservation(
    value: Any,
) -> tuple[
    PilotExactTaskLocalCommitWriteReservationReceipt,
    PilotExactTaskLocalCommitObjectIdentity,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskLocalCommitWriteReservationReceipt:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "exact ADR-DC-045 local-write reservation receipt is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitWriteReservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "ADR-DC-045 reservation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "ADR-DC-045 reservation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_RESERVATION_AUTHORITY
        or value.reservation_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.authorization_proof_verified is not True
        or value.fresh_live_identity_revalidated is not True
        or value.local_write_reserved is not True
        or value.one_shot_local_write_required is not True
        or value.local_write_authorization_consumed is not True
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
        or value.reservation_key_sha256 != value.local_write_nonce_sha256
        or value.local_write_nonce_sha256 == value.execution_nonce_sha256
    ):
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "local Git write transaction requires one live inert ADR-DC-045 reservation"
        )

    inputs = reservation_boundary._get_live_local_commit_write_reservation_inputs(value)
    if inputs is None:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "ADR-DC-045 live reservation provenance is unavailable"
        )
    identity = inputs.get("local_commit_object_identity")
    if type(identity) is not PilotExactTaskLocalCommitObjectIdentity:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "ADR-DC-045 reservation lost exact ADR-DC-042 identity provenance"
        )
    if (
        identity.identity_authenticated is not True
        or identity.sha256 != value.local_commit_object_identity_sha256
        or identity.execution_nonce_sha256 != value.execution_nonce_sha256
        or identity.index_manifest_sha256 != value.index_manifest_sha256
        or identity.root_tree_sha != value.root_tree_sha
        or identity.commit_payload_sha256 != value.commit_payload_sha256
        or identity.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "ADR-DC-045 reservation is not bound to its exact live ADR-DC-042 identity"
        )
    return value, identity, inputs


def _reservation_window_allows_write(
    reservation: PilotExactTaskLocalCommitWriteReservationReceipt,
    at_utc: str,
) -> None:
    now = _utc(at_utc, name="transaction time")
    reserved = _utc(reservation.reserved_at_utc, name="reserved_at_utc")
    if now < reserved or now > reserved + timedelta(
        seconds=PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_MAX_RESERVATION_AGE_SECONDS
    ):
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "ADR-DC-045 reservation is too old for a local Git write"
        )


def _fresh_transaction_state(
    *,
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> tuple[bytes, tuple[tuple[str, str, str], ...]]:
    reservation_boundary._fresh_identity_revalidation(identity)
    plan = inputs.get("local_commit_plan")
    if plan is None or getattr(plan, "sha256", None) != identity.local_commit_plan_sha256:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "live ADR-DC-041 plan provenance changed"
        )
    try:
        index_payload = identity_boundary._read_index_manifest(inputs)
        entries = identity_boundary._parse_index_manifest(index_payload)
        snapshot = identity_boundary._fresh_workspace_snapshot(inputs)
        identity_boundary._require_snapshot_matches_plan(plan, snapshot)
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "fresh transaction workspace/index capture failed"
        ) from exc
    if (
        hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256
        or len(entries) != identity.index_entry_count
        or identity_boundary._root_tree_sha(entries) != identity.root_tree_sha
    ):
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "captured transaction index identity differs from ADR-DC-042"
        )
    return index_payload, entries


def _tree_object_payloads(
    entries: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[str, bytes], ...]:
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
                raise PilotExactTaskLocalCommitWriteTransactionError(
                    "captured index tree contains a path collision"
                )
        leaf = parts[-1]
        if leaf in node:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "captured index tree contains a duplicate leaf"
            )
        node[leaf] = (mode, object_sha)

    objects: list[tuple[str, bytes]] = []

    def materialize(node: dict[str, Any]) -> str:
        records: list[tuple[bytes, bytes]] = []
        for name, value in node.items():
            raw_name = name.encode("utf-8")
            if isinstance(value, dict):
                object_sha = materialize(value)
                mode_raw = b"40000"
                sort_key = raw_name + b"/"
            else:
                mode, object_sha = value
                mode_raw = mode.encode("ascii")
                sort_key = raw_name
            record = (
                mode_raw
                + b" "
                + raw_name
                + b"\0"
                + bytes.fromhex(object_sha)
            )
            records.append((sort_key, record))
        payload = b"".join(
            record for _, record in sorted(records, key=lambda item: item[0])
        )
        sha = identity_boundary._git_sha1("tree", payload)
        objects.append((sha, payload))
        return sha

    materialize(root)
    return tuple(objects)


def _trusted_git_run(
    inputs: Mapping[str, Any],
    args: tuple[str, ...],
    *,
    stdin: bytes | None = None,
    maximum: int = 4096,
) -> bytes:
    try:
        kwargs: dict[str, Any] = {
            "cwd": Path(inputs["workspace_root"]),
            "maximum": maximum,
            "timeout_seconds": 120,
        }
        if stdin is not None:
            kwargs["stdin"] = stdin
        result = inputs["git_runner"].run(args, **kwargs)
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            f"trusted local Git command failed: {args[0]}"
        ) from exc
    if not isinstance(result, bytes):
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "trusted local Git command returned non-bytes output"
        )
    return result


def _write_exact_tree_objects(
    *,
    inputs: Mapping[str, Any],
    tree_objects: tuple[tuple[str, bytes], ...],
    expected_root_tree_sha: str,
) -> int:
    if not tree_objects:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "exact tree object set is empty"
        )
    for expected_sha, payload in tree_objects:
        if len(payload) > _MAX_GIT_OBJECT_BYTES:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "tree object exceeds byte bound"
            )
        actual = _trusted_git_run(
            inputs,
            ("hash-object", "-t", "tree", "-w", "--stdin"),
            stdin=payload,
            maximum=4096,
        ).decode("ascii", errors="strict").strip()
        _hex40(actual, name="written tree SHA")
        if actual != expected_sha:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "TrustedGit wrote an unexpected tree object identity"
            )
        readback = _trusted_git_run(
            inputs,
            ("cat-file", "tree", expected_sha),
            maximum=_MAX_GIT_OBJECT_BYTES,
        )
        if readback != payload:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "written tree object read-back mismatch"
            )
    if tree_objects[-1][0] != expected_root_tree_sha:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "written root tree does not match ADR-DC-042"
        )
    return len(tree_objects)


def _write_exact_commit_object(
    *,
    inputs: Mapping[str, Any],
    identity: PilotExactTaskLocalCommitObjectIdentity,
) -> bytes:
    payload = identity_boundary._commit_payload(
        tree_sha=identity.root_tree_sha,
        parent_sha=identity.base_sha,
        subject=identity.commit_subject,
        epoch_seconds=identity.commit_epoch_seconds,
    )
    if (
        hashlib.sha256(payload).hexdigest() != identity.commit_payload_sha256
        or identity_boundary._git_sha1("commit", payload) != identity.predicted_commit_sha
    ):
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "frozen commit payload no longer reproduces ADR-DC-042"
        )
    actual = _trusted_git_run(
        inputs,
        ("hash-object", "-t", "commit", "-w", "--stdin"),
        stdin=payload,
        maximum=4096,
    ).decode("ascii", errors="strict").strip()
    _hex40(actual, name="written commit SHA")
    if actual != identity.predicted_commit_sha:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "TrustedGit wrote a commit other than the exact predicted SHA"
        )
    readback = _trusted_git_run(
        inputs,
        ("cat-file", "commit", identity.predicted_commit_sha),
        maximum=_MAX_GIT_OBJECT_BYTES,
    )
    if readback != payload:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "written commit object read-back mismatch"
        )
    return payload


def _require_ref_absent(
    *,
    inputs: Mapping[str, Any],
    local_ref: str,
) -> None:
    _trusted_git_run(inputs, ("check-ref-format", local_ref), maximum=4096)
    raw = _trusted_git_run(
        inputs,
        ("for-each-ref", "--format=%(objectname)", "--count=1", local_ref),
        maximum=4096,
    )
    if raw.strip():
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "host-pinned one-shot local candidate ref already exists"
        )


def _create_and_verify_ref(
    *,
    inputs: Mapping[str, Any],
    local_ref: str,
    predicted_commit_sha: str,
) -> None:
    _trusted_git_run(
        inputs,
        ("update-ref", local_ref, predicted_commit_sha, _ZERO_SHA),
        maximum=4096,
    )
    actual = _trusted_git_run(
        inputs,
        ("rev-parse", "--verify", f"{local_ref}^{{commit}}"),
        maximum=4096,
    ).decode("ascii", errors="strict").strip()
    _hex40(actual, name="local candidate ref target")
    if actual != predicted_commit_sha:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "post-write local candidate ref verification failed"
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
        reservation: PilotExactTaskLocalCommitWriteReservationReceipt,
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
            weakref.ref(reservation),
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
            reservation_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        reservation = reservation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or reservation is None
            or reservation.reservation_authenticated is not True
            or receipt.write_reservation_sha256 != reservation.sha256
            or receipt.sha256 != digest
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
        ):
            return None
        inputs = reservation_boundary._get_live_local_commit_write_reservation_inputs(
            reservation
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["local_commit_write_reservation"] = reservation
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_local_commit_write_transaction_authenticated,
    _get_live_local_commit_write_transaction_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitWriteTransactionReceipt:
    transaction_ledger_root_path_sha256: str
    transaction_key_sha256: str
    write_reservation_sha256: str
    authorization_proof_sha256: str
    authorization_signature_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    base_sha: str
    local_ref: str
    expected_old_ref_sha: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    tree_object_count: int
    prepared_at_utc: str
    object_write_completed_at_utc: str
    ref_updated_at_utc: str
    completed_at_utc: str
    host_transaction_guard_committed: bool = True
    write_reservation_authenticated: bool = True
    fresh_live_identity_revalidated: bool = True
    exact_tree_objects_written: bool = True
    exact_commit_object_written: bool = True
    exact_commit_object_verified: bool = True
    local_ref_create_only_cas_succeeded: bool = True
    post_write_ref_verified: bool = True
    post_write_workspace_revalidated: bool = True
    write_reservation_consumed: bool = True
    local_commit_write_completed: bool = True
    git_object_write_performed: bool = True
    local_ref_update_performed: bool = True
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
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_SCHEMA:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction schema is unsupported"
            )
        if self.ledger_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_LEDGER_SCOPE:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction ledger scope is unsupported"
            )
        for name in (
            "transaction_ledger_root_path_sha256",
            "transaction_key_sha256",
            "write_reservation_sha256",
            "authorization_proof_sha256",
            "authorization_signature_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        _hex40(self.expected_old_ref_sha, name="expected_old_ref_sha", allow_zero=True)
        if self.expected_old_ref_sha != _ZERO_SHA:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local candidate ref must use create-only CAS"
            )
        if self.transaction_key_sha256 != self.local_write_nonce_sha256:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "transaction key must be the exact signed local-write nonce"
            )
        if self.local_write_nonce_sha256 == self.execution_nonce_sha256:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local-write nonce must differ from execution nonce"
            )
        if self.local_ref != _local_ref_name(self.local_write_nonce_sha256):
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "transaction local ref is not host-pinned to the signed nonce"
            )
        if (
            isinstance(self.tree_object_count, bool)
            or not isinstance(self.tree_object_count, int)
            or not 1 <= self.tree_object_count <= 1_000_000
        ):
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "tree_object_count is invalid"
            )
        prepared = _utc(self.prepared_at_utc, name="prepared_at_utc")
        object_done = _utc(
            self.object_write_completed_at_utc,
            name="object_write_completed_at_utc",
        )
        ref_done = _utc(self.ref_updated_at_utc, name="ref_updated_at_utc")
        completed = _utc(self.completed_at_utc, name="completed_at_utc")
        if not prepared <= object_done <= ref_done <= completed:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction timestamps are not monotonic"
            )
        required_true = (
            "host_transaction_guard_committed",
            "write_reservation_authenticated",
            "fresh_live_identity_revalidated",
            "exact_tree_objects_written",
            "exact_commit_object_written",
            "exact_commit_object_verified",
            "local_ref_create_only_cas_succeeded",
            "post_write_ref_verified",
            "post_write_workspace_revalidated",
            "write_reservation_consumed",
            "local_commit_write_completed",
            "git_object_write_performed",
            "local_ref_update_performed",
            "local_commit_created",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction evidence is incomplete"
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
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "completed local write receipt cannot retain reusable/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_AUTHORITY:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction authority is unsupported"
            )

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_local_commit_write_transaction_inputs(self) is not None

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
        cls, value: Any
    ) -> "PilotExactTaskLocalCommitWriteTransactionReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls, text: str
    ) -> "PilotExactTaskLocalCommitWriteTransactionReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local Git write transaction JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskLocalCommitWriteTransactionLedger:
    """Permanent transaction receipt ledger keyed by the signed local-write nonce."""

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
        reservation: PilotExactTaskLocalCommitWriteReservationReceipt,
        local_ref: str,
    ) -> bytes:
        key = reservation.local_write_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "exact local-write transaction already exists or requires recovery"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-local-commit-write-transaction-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_LEDGER_SCOPE,
                "transaction_ledger_root_path_sha256": self.root_sha256,
                "transaction_key_sha256": key,
                "write_reservation_sha256": reservation.sha256,
                "authorization_proof_sha256": reservation.authorization_proof_sha256,
                "authorization_signature_sha256": reservation.authorization_signature_sha256,
                "local_commit_object_identity_sha256": reservation.local_commit_object_identity_sha256,
                "execution_nonce_sha256": reservation.execution_nonce_sha256,
                "local_write_nonce_sha256": reservation.local_write_nonce_sha256,
                "predicted_commit_sha": reservation.predicted_commit_sha,
                "local_ref": local_ref,
                "expected_old_ref_sha": _ZERO_SHA,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local-write transaction guard could not be committed"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskLocalCommitWriteTransactionReceipt,
        reservation: PilotExactTaskLocalCommitWriteReservationReceipt,
        lock_payload: bytes,
    ) -> PilotExactTaskLocalCommitWriteTransactionReceipt:
        final, pending, lock = self._paths(receipt.transaction_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local-write transaction marker changed before receipt commit"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local-write transaction receipt state already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local-write transaction receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskLocalCommitWriteTransactionError(
                    "local-write transaction receipt read-back mismatch"
                )
            parsed = PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.transaction_ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskLocalCommitWriteTransactionError(
                    "local-write transaction receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskLocalCommitWriteTransactionError(
                    "local-write transaction marker changed before provenance registration"
                )
            _mark_local_commit_write_transaction_authenticated(
                parsed,
                reservation,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.transaction_authenticated is not True:
                raise PilotExactTaskLocalCommitWriteTransactionError(
                    "local-write transaction lost live durable provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskLocalCommitWriteTransactionError):
                raise
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local-write transaction is durable but receipt requires recovery"
            ) from exc


def _execute_verified_exact_task_local_commit_write(
    *,
    write_reservation: PilotExactTaskLocalCommitWriteReservationReceipt,
    ledger: _PilotExactTaskLocalCommitWriteTransactionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskLocalCommitWriteTransactionReceipt:
    reservation, identity, inputs = _require_live_reservation(write_reservation)
    if type(ledger) is not _PilotExactTaskLocalCommitWriteTransactionLedger:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "local-write transaction ledger is required"
        )

    prepared_at = now_provider()
    _reservation_window_allows_write(reservation, prepared_at)
    prepared_time = _utc(prepared_at, name="prepared_at_utc")

    _index_payload, entries = _fresh_transaction_state(
        identity=identity,
        inputs=inputs,
    )
    tree_objects = _tree_object_payloads(entries)
    if tree_objects[-1][0] != identity.root_tree_sha:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "captured tree object set does not reproduce ADR-DC-042 root"
        )

    local_ref = _local_ref_name(reservation.local_write_nonce_sha256)
    _require_ref_absent(inputs=inputs, local_ref=local_ref)

    marker = ledger.acquire(reservation=reservation, local_ref=local_ref)

    tree_count = _write_exact_tree_objects(
        inputs=inputs,
        tree_objects=tree_objects,
        expected_root_tree_sha=identity.root_tree_sha,
    )
    _write_exact_commit_object(inputs=inputs, identity=identity)

    object_done_at = now_provider()
    _reservation_window_allows_write(reservation, object_done_at)
    object_done_time = _utc(
        object_done_at,
        name="object_write_completed_at_utc",
    )
    if object_done_time < prepared_time:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "system clock moved backwards during Git object write"
        )

    _create_and_verify_ref(
        inputs=inputs,
        local_ref=local_ref,
        predicted_commit_sha=identity.predicted_commit_sha,
    )
    ref_updated_at = now_provider()
    _reservation_window_allows_write(reservation, ref_updated_at)
    ref_time = _utc(ref_updated_at, name="ref_updated_at_utc")
    if ref_time < object_done_time:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "system clock moved backwards during local ref update"
        )

    reservation_boundary._fresh_identity_revalidation(identity)
    post_ref = _trusted_git_run(
        inputs,
        ("rev-parse", "--verify", f"{local_ref}^{{commit}}"),
        maximum=4096,
    ).decode("ascii", errors="strict").strip()
    if post_ref != identity.predicted_commit_sha:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "post-write ref no longer points to the exact commit"
        )

    completed_at = now_provider()
    _reservation_window_allows_write(reservation, completed_at)
    completed_time = _utc(completed_at, name="completed_at_utc")
    if completed_time < ref_time:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "system clock moved backwards before local transaction completion"
        )

    receipt = PilotExactTaskLocalCommitWriteTransactionReceipt(
        transaction_ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=reservation.local_write_nonce_sha256,
        write_reservation_sha256=reservation.sha256,
        authorization_proof_sha256=reservation.authorization_proof_sha256,
        authorization_signature_sha256=reservation.authorization_signature_sha256,
        local_commit_object_identity_sha256=identity.sha256,
        execution_nonce_sha256=reservation.execution_nonce_sha256,
        local_write_nonce_sha256=reservation.local_write_nonce_sha256,
        base_sha=identity.base_sha,
        local_ref=local_ref,
        expected_old_ref_sha=_ZERO_SHA,
        index_manifest_sha256=identity.index_manifest_sha256,
        root_tree_sha=identity.root_tree_sha,
        commit_payload_sha256=identity.commit_payload_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        tree_object_count=tree_count,
        prepared_at_utc=prepared_at,
        object_write_completed_at_utc=object_done_at,
        ref_updated_at_utc=ref_updated_at,
        completed_at_utc=completed_at,
    )
    return ledger.commit(
        receipt=receipt,
        reservation=reservation,
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
            raise PilotExactTaskLocalCommitWriteTransactionError(
                "local-write transaction ledger is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "canonical local-write transaction ledger is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_local_commit_write(
    write_reservation: PilotExactTaskLocalCommitWriteReservationReceipt,
) -> PilotExactTaskLocalCommitWriteTransactionReceipt:
    """Execute exactly one reserved local commit write; never publish remotely."""
    try:
        root = _canonical_ledger_root()
        ledger = _PilotExactTaskLocalCommitWriteTransactionLedger(root)
        return _execute_verified_exact_task_local_commit_write(
            write_reservation=write_reservation,
            ledger=ledger,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskLocalCommitWriteTransactionError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskLocalCommitWriteTransactionError(
            "host-controlled exact local Git write failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_TRANSACTION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_REF_PREFIX",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_MAX_RESERVATION_AGE_SECONDS",
    "PilotExactTaskLocalCommitWriteTransactionError",
    "PilotExactTaskLocalCommitWriteTransactionReceipt",
    "execute_pilot_exact_task_local_commit_write",
]
