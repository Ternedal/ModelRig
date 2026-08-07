"""Crash-durable create-once staging for a complete trusted Git runtime."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    remove_tree_durable,
    rename_directory_no_replace,
    sync_directory,
    unlink_durable,
)
from .trusted_git_runtime_model import (
    _MAX_FILE_BYTES,
    TrustedGitRuntimeError,
    TrustedGitRuntimeManifest,
    TrustedGitRuntimeStagingReceipt,
    _existing_link_free_directory,
    _has_linkish_component,
    _path_hash,
    _regular_unaliased_file,
    _sha256_bytes,
    _transaction_id,
)

TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA = (
    "kaliv-development-trusted-git-runtime-recovery-receipt/v1"
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_RECOVERY_ACTIONS = {
    "publish_prepared",
    "discard_pending",
    "release_reservation",
    "acknowledge_committed",
}
_RECOVERY_STATES = {
    "absent",
    "reserved",
    "partial",
    "prepared",
    "committed",
    "committed_locked",
    "conflict",
}


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeRecoveryReceipt:
    transaction_id: str
    manifest_sha256: str
    staging_root_path_sha256: str
    recovery_authorization_sha256: str
    operator_actor_id: str
    recovered_at_utc: str
    action: str
    state_before: str
    state_after: str
    final_root_verified: bool
    schema: str = TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA:
            raise TrustedGitRuntimeError("unsupported Git runtime recovery schema")
        if self.transaction_id != _transaction_id(self.manifest_sha256):
            raise TrustedGitRuntimeError("Git runtime recovery transaction is invalid")
        for name, value in (
            ("manifest hash", self.manifest_sha256),
            ("staging root hash", self.staging_root_path_sha256),
            ("recovery authorization hash", self.recovery_authorization_sha256),
        ):
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                raise TrustedGitRuntimeError(f"Git runtime recovery {name} is invalid")
        if not isinstance(self.operator_actor_id, str) or _ACTOR.fullmatch(
            self.operator_actor_id
        ) is None:
            raise TrustedGitRuntimeError("Git runtime recovery operator is invalid")
        if not isinstance(self.recovered_at_utc, str) or _UTC.fullmatch(
            self.recovered_at_utc
        ) is None:
            raise TrustedGitRuntimeError("Git runtime recovery time is invalid")
        try:
            datetime.strptime(self.recovered_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError as exc:
            raise TrustedGitRuntimeError("Git runtime recovery time is invalid") from exc
        if self.action not in _RECOVERY_ACTIONS:
            raise TrustedGitRuntimeError("Git runtime recovery action is invalid")
        if self.state_before not in _RECOVERY_STATES or self.state_after not in _RECOVERY_STATES:
            raise TrustedGitRuntimeError("Git runtime recovery state is invalid")
        if self.final_root_verified is not (self.state_after == "committed"):
            raise TrustedGitRuntimeError("Git runtime recovery verification flag is inconsistent")

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeRecoveryReceipt":
        fields = {
            "schema",
            "transaction_id",
            "manifest_sha256",
            "staging_root_path_sha256",
            "recovery_authorization_sha256",
            "operator_actor_id",
            "recovered_at_utc",
            "action",
            "state_before",
            "state_after",
            "final_root_verified",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise TrustedGitRuntimeError("Git runtime recovery receipt fields mismatch")
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "transaction_id": self.transaction_id,
            "manifest_sha256": self.manifest_sha256,
            "staging_root_path_sha256": self.staging_root_path_sha256,
            "recovery_authorization_sha256": self.recovery_authorization_sha256,
            "operator_actor_id": self.operator_actor_id,
            "recovered_at_utc": self.recovered_at_utc,
            "action": self.action,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "final_root_verified": self.final_root_verified,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


def _write_file(path: Path, payload: bytes, *, executable: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if _has_linkish_component(path.parent) or path.exists():
        raise TrustedGitRuntimeError("Git runtime staging path is unsafe")
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o755 if executable else 0o644)


def _verify_runtime_tree(runtime_root: Path, manifest: TrustedGitRuntimeManifest) -> None:
    root = _existing_link_free_directory(runtime_root, name="staged Git runtime")
    expected = {item.relative_path: item for item in manifest.files}
    observed: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        if candidate.is_dir():
            if _has_linkish_component(candidate):
                raise TrustedGitRuntimeError("staged Git runtime contains a linked directory")
            continue
        relative = candidate.relative_to(root).as_posix()
        item = expected.get(relative)
        if item is None:
            raise TrustedGitRuntimeError("staged Git runtime contains an extra file")
        stat_result = _regular_unaliased_file(
            candidate, name="staged Git runtime file"
        )
        payload = candidate.read_bytes()
        if (
            stat_result.st_size != item.size_bytes
            or _sha256_bytes(payload) != item.sha256
        ):
            raise TrustedGitRuntimeError("staged Git runtime file changed")
        if item.executable and not bool(stat_result.st_mode & 0o111):
            raise TrustedGitRuntimeError("staged Git runtime executable bit changed")
        observed.add(relative)
    if observed != set(expected):
        raise TrustedGitRuntimeError("staged Git runtime is incomplete")


def _load_receipt_at(
    transaction_root: Path,
    *,
    expected_transaction_id: str,
) -> TrustedGitRuntimeStagingReceipt:
    root = _existing_link_free_directory(
        transaction_root,
        name="Git runtime transaction root",
    )
    receipt_path = root / "receipt.json"
    stat_result = _regular_unaliased_file(
        receipt_path, name="Git runtime receipt"
    )
    if stat_result.st_size > _MAX_FILE_BYTES:
        raise TrustedGitRuntimeError("Git runtime receipt is too large")
    payload = receipt_path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrustedGitRuntimeError("Git runtime receipt is invalid JSON") from exc
    receipt = TrustedGitRuntimeStagingReceipt.from_mapping(value)
    if payload != receipt.canonical_json().encode("utf-8"):
        raise TrustedGitRuntimeError("Git runtime receipt is not canonical")
    if receipt.transaction_id != expected_transaction_id:
        raise TrustedGitRuntimeError("Git runtime transaction identity is invalid")
    top_level = {item.name for item in root.iterdir()}
    if top_level != {"runtime", "receipt.json"}:
        raise TrustedGitRuntimeError("Git runtime transaction layout is invalid")
    _verify_runtime_tree(root / receipt.runtime_relative_path, receipt.manifest)
    return receipt


def _transaction_paths(staging_root: Path, transaction_id: str) -> tuple[Path, Path, Path]:
    return (
        staging_root / transaction_id,
        staging_root / f".{transaction_id}.pending",
        staging_root / f".{transaction_id}.lock",
    )


def _transaction_state(
    *,
    manifest: TrustedGitRuntimeManifest,
    final: Path,
    pending: Path,
    lock: Path,
) -> str:
    final_exists = final.exists()
    pending_exists = pending.exists()
    lock_exists = lock.exists()
    if final_exists and pending_exists:
        return "conflict"
    if final_exists:
        try:
            receipt = _load_receipt_at(
                final, expected_transaction_id=_transaction_id(manifest.sha256)
            )
        except TrustedGitRuntimeError:
            return "conflict"
        if receipt.manifest.sha256 != manifest.sha256:
            return "conflict"
        return "committed_locked" if lock_exists else "committed"
    if pending_exists:
        try:
            receipt = _load_receipt_at(
                pending, expected_transaction_id=_transaction_id(manifest.sha256)
            )
        except TrustedGitRuntimeError:
            return "partial"
        return "prepared" if receipt.manifest.sha256 == manifest.sha256 else "partial"
    return "reserved" if lock_exists else "absent"


def stage_trusted_git_runtime(
    manifest: TrustedGitRuntimeManifest,
    *,
    source_root: Path,
    staging_root: Path,
) -> Path:
    """Durably publish one verified runtime transaction without overwrite."""

    if not isinstance(manifest, TrustedGitRuntimeManifest):
        raise TrustedGitRuntimeError("Git runtime staging requires a manifest")
    source = _existing_link_free_directory(source_root, name="Git runtime source root")
    destination = _existing_link_free_directory(
        staging_root, name="Git runtime staging root"
    )
    transaction_id = _transaction_id(manifest.sha256)
    final, pending, lock = _transaction_paths(destination, transaction_id)
    try:
        create_once_file(
            lock,
            (manifest.sha256 + "\n").encode("ascii"),
            mode=0o600,
        )
    except FileExistsError as exc:
        raise TrustedGitRuntimeError(
            "Git runtime transaction is reserved; explicit recovery is required"
        ) from exc
    except DurablePublicationError as exc:
        raise TrustedGitRuntimeError("Git runtime reservation was not durable") from exc

    prepared = False
    committed = False
    try:
        if final.exists():
            raise TrustedGitRuntimeError("Git runtime transaction already exists")
        if pending.exists():
            raise TrustedGitRuntimeError(
                "Git runtime pending transaction requires explicit recovery"
            )
        pending.mkdir(mode=0o700)
        sync_directory(destination)
        runtime = pending / "runtime"
        runtime.mkdir()
        for item in manifest.files:
            source_path = source.joinpath(
                *PurePosixPath(item.relative_path).parts
            )
            stat_result = _regular_unaliased_file(
                source_path,
                name="Git runtime source file",
            )
            payload = source_path.read_bytes()
            if (
                stat_result.st_size != item.size_bytes
                or _sha256_bytes(payload) != item.sha256
            ):
                raise TrustedGitRuntimeError(
                    "Git runtime source does not match the pinned manifest"
                )
            _write_file(
                runtime.joinpath(*PurePosixPath(item.relative_path).parts),
                payload,
                executable=item.executable,
            )
        _verify_runtime_tree(runtime, manifest)
        receipt = TrustedGitRuntimeStagingReceipt(
            manifest=manifest,
            transaction_id=transaction_id,
            source_root_path_sha256=_path_hash(source),
            runtime_relative_path="runtime",
            complete=True,
        )
        _write_file(
            pending / "receipt.json",
            receipt.canonical_json().encode("utf-8"),
            executable=False,
        )
        _load_receipt_at(pending, expected_transaction_id=transaction_id)
        prepared = True
        try:
            rename_directory_no_replace(pending, final)
        except FileExistsError as exc:
            raise TrustedGitRuntimeError(
                "Git runtime transaction already exists"
            ) from exc
        except DurablePublicationError as exc:
            raise TrustedGitRuntimeError(
                "Git runtime transaction commit failed; explicit recovery is required"
            ) from exc
        committed = True
        _load_receipt_at(final, expected_transaction_id=transaction_id)
        try:
            unlink_durable(lock)
        except DurablePublicationError as exc:
            raise TrustedGitRuntimeError(
                "Git runtime committed but reservation cleanup requires recovery"
            ) from exc
        return final
    finally:
        if not prepared:
            if pending.exists():
                try:
                    remove_tree_durable(pending)
                except DurablePublicationError:
                    shutil.rmtree(pending, ignore_errors=True)
            if lock.exists():
                try:
                    unlink_durable(lock)
                except DurablePublicationError:
                    pass
        elif committed:
            # A committed final directory is never removed implicitly. A stale
            # lock is evidence for acknowledge_committed recovery.
            pass


def recover_trusted_git_runtime_transaction(
    manifest: TrustedGitRuntimeManifest,
    *,
    staging_root: Path,
    action: str,
    recovery_authorization_sha256: str,
    operator_actor_id: str,
    recovered_at_utc: str,
) -> TrustedGitRuntimeRecoveryReceipt:
    """Perform one explicit, evidence-bound recovery action."""

    if not isinstance(manifest, TrustedGitRuntimeManifest):
        raise TrustedGitRuntimeError("Git runtime recovery requires a manifest")
    if action not in _RECOVERY_ACTIONS:
        raise TrustedGitRuntimeError("Git runtime recovery action is invalid")
    destination = _existing_link_free_directory(
        staging_root, name="Git runtime staging root"
    )
    transaction_id = _transaction_id(manifest.sha256)
    final, pending, lock = _transaction_paths(destination, transaction_id)
    state_before = _transaction_state(
        manifest=manifest, final=final, pending=pending, lock=lock
    )
    try:
        if action == "publish_prepared":
            if state_before != "prepared":
                raise TrustedGitRuntimeError(
                    "publish recovery requires one verified prepared transaction"
                )
            rename_directory_no_replace(pending, final)
            _load_receipt_at(final, expected_transaction_id=transaction_id)
            unlink_durable(lock)
        elif action == "discard_pending":
            if state_before not in {"partial", "prepared"}:
                raise TrustedGitRuntimeError(
                    "discard recovery requires one pending transaction"
                )
            remove_tree_durable(pending)
            unlink_durable(lock)
        elif action == "release_reservation":
            if state_before != "reserved":
                raise TrustedGitRuntimeError(
                    "reservation recovery requires an orphaned lock"
                )
            unlink_durable(lock)
        elif action == "acknowledge_committed":
            if state_before != "committed_locked":
                raise TrustedGitRuntimeError(
                    "commit acknowledgement requires a verified committed transaction"
                )
            _load_receipt_at(final, expected_transaction_id=transaction_id)
            unlink_durable(lock)
    except DurablePublicationError as exc:
        raise TrustedGitRuntimeError("Git runtime recovery operation was not durable") from exc
    state_after = _transaction_state(
        manifest=manifest, final=final, pending=pending, lock=lock
    )
    expected_after = {
        "publish_prepared": "committed",
        "discard_pending": "absent",
        "release_reservation": "absent",
        "acknowledge_committed": "committed",
    }[action]
    if state_after != expected_after:
        raise TrustedGitRuntimeError("Git runtime recovery postcondition failed")
    return TrustedGitRuntimeRecoveryReceipt(
        transaction_id=transaction_id,
        manifest_sha256=manifest.sha256,
        staging_root_path_sha256=_path_hash(destination),
        recovery_authorization_sha256=recovery_authorization_sha256,
        operator_actor_id=operator_actor_id,
        recovered_at_utc=recovered_at_utc,
        action=action,
        state_before=state_before,
        state_after=state_after,
        final_root_verified=state_after == "committed",
    )


def load_trusted_git_runtime_receipt(
    transaction_root: Path,
) -> TrustedGitRuntimeStagingReceipt:
    root = _existing_link_free_directory(
        transaction_root,
        name="Git runtime transaction root",
    )
    receipt = _load_receipt_at(root, expected_transaction_id=root.name)
    if root.name != receipt.transaction_id:
        raise TrustedGitRuntimeError("Git runtime transaction path is invalid")
    return receipt


class TrustedGitRuntime:
    """Verified view of one staged complete Git runtime transaction."""

    def __init__(self, transaction_root: Path) -> None:
        self.transaction_root = _existing_link_free_directory(
            transaction_root,
            name="Git runtime transaction root",
        )
        self.receipt = load_trusted_git_runtime_receipt(self.transaction_root)
        self.runtime_root = (
            self.transaction_root / self.receipt.runtime_relative_path
        )

    @property
    def executable_path(self) -> Path:
        return self.runtime_root.joinpath(
            *PurePosixPath(
                self.receipt.manifest.executable_relative_path
            ).parts
        )

    @property
    def exec_path(self) -> Path:
        relative = self.receipt.manifest.exec_path_relative_path
        return self.runtime_root if relative == "." else self.runtime_root.joinpath(
            *PurePosixPath(relative).parts
        )

    @property
    def path_directories(self) -> tuple[Path, ...]:
        result: list[Path] = []
        for relative in self.receipt.manifest.path_relative_directories:
            result.append(
                self.runtime_root
                if relative == "."
                else self.runtime_root.joinpath(*PurePosixPath(relative).parts)
            )
        return tuple(result)

    @property
    def library_directories(self) -> tuple[Path, ...]:
        relative_directories = sorted(
            {
                str(PurePosixPath(item.relative_path).parent)
                for item in self.receipt.manifest.files
                if item.role == "library"
            }
        )
        return tuple(
            self.runtime_root
            if relative == "."
            else self.runtime_root.joinpath(*PurePosixPath(relative).parts)
            for relative in relative_directories
        )

    def verify(self) -> None:
        current = load_trusted_git_runtime_receipt(self.transaction_root)
        if current.sha256 != self.receipt.sha256:
            raise TrustedGitRuntimeError("Git runtime receipt changed")
