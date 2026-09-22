"""C19 production-grade SelfState CAS committer.

The committer is the narrow durable authority injected into C18. It serializes
cross-process writers with an OS kernel lock, verifies the complete deterministic
C17 transition binding, writes a bounded write-ahead journal, performs an exact
SelfState compare-and-swap, and returns a durable commit receipt.

There is no application polling/retry loop:
- POSIX uses blocking fcntl.flock(LOCK_EX).
- Windows uses blocking Win32 LockFileEx.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Iterator, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .cycle import self_state_ref, workspace_ref
from .self_state import PersistentSelfState, SelfStateError, SelfStateStore
from .single_step import StateTransitionCommitReceipt
from .supervisor import SupervisorTransitionCandidate


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedError = Annotated[str, Field(min_length=1, max_length=2048)]

_JOURNAL_SCHEMA = "kaliv-consciousness-core/state-commit-journal/v1"
_JOURNAL_MAX = 64 * 1024


class StateCommitError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class StateCommitJournalRecord(StrictModel):
    schema: Literal["kaliv-consciousness-core/state-commit-journal/v1"]
    transaction_id: Annotated[str, Field(pattern=r"^stx-[a-f0-9]{32}$")]
    transition_id: Annotated[str, Field(pattern=r"^suptrans-[a-f0-9]{32}$")]
    state: Literal["prepared", "committed", "aborted", "conflict"]
    before_self_state_ref: NonEmptyRef
    after_self_state_ref: NonEmptyRef
    before_revision: Annotated[int, Field(ge=1, strict=True)]
    after_revision: Annotated[int, Field(ge=2, strict=True)]
    commit_ref: NonEmptyRef
    error: BoundedError | None
    production_activation: Literal[False]


class StateCommitRecoveryReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/state-commit-recovery/v1"]
    outcome: Literal["none", "committed", "aborted", "conflict"]
    transaction_id: Annotated[str, Field(pattern=r"^stx-[a-f0-9]{32}$")] | None
    transition_id: Annotated[str, Field(pattern=r"^suptrans-[a-f0-9]{32}$")] | None
    current_self_state_ref: NonEmptyRef | None
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _fsync_parent(path: Path) -> None:
    """Durably publish a rename on POSIX; Windows has no directory fsync API."""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_regular_file(path: Path, *, allow_missing: bool) -> None:
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return
        raise StateCommitError(f"required state path is missing: {path}")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise StateCommitError(f"path must be one regular non-linked file: {path}")


def _read_bounded(path: Path, maximum: int) -> bytes:
    _validate_regular_file(path, allow_missing=False)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise StateCommitError("opened journal path is not one regular file")
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > maximum:
            raise StateCommitError("state commit journal exceeds bounded size")
        return bytes(raw)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = _canonical_json(payload) + b"\n"
    if len(encoded) > _JOURNAL_MAX:
        raise StateCommitError("state commit journal exceeds bounded size")
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_regular_file(path, allow_missing=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            if os.name == "posix":
                raise
        os.replace(temp_name, path)
        _fsync_parent(path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _validate_open_lock(descriptor: int, path: Path) -> None:
    opened = os.fstat(descriptor)
    try:
        named = path.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise StateCommitError("state commit lock disappeared") from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or not stat.S_ISREG(named.st_mode)
        or named.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
    ):
        raise StateCommitError("state commit lock is irregular or was substituted")


class _WinOverlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


def _lock_windows(descriptor: int, overlapped: _WinOverlapped) -> None:
    import msvcrt

    handle = msvcrt.get_osfhandle(descriptor)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    lock_file_ex = kernel32.LockFileEx
    lock_file_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(_WinOverlapped),
    ]
    lock_file_ex.restype = ctypes.c_int
    LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    if not lock_file_ex(
        ctypes.c_void_p(handle),
        LOCKFILE_EXCLUSIVE_LOCK,
        0,
        1,
        0,
        ctypes.byref(overlapped),
    ):
        raise StateCommitError(
            f"Win32 LockFileEx failed: {ctypes.WinError(ctypes.get_last_error())}"
        )


def _unlock_windows(descriptor: int, overlapped: _WinOverlapped) -> None:
    import msvcrt

    handle = msvcrt.get_osfhandle(descriptor)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    unlock_file_ex = kernel32.UnlockFileEx
    unlock_file_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(_WinOverlapped),
    ]
    unlock_file_ex.restype = ctypes.c_int
    if not unlock_file_ex(
        ctypes.c_void_p(handle),
        0,
        1,
        0,
        ctypes.byref(overlapped),
    ):
        raise StateCommitError(
            f"Win32 UnlockFileEx failed: {ctypes.WinError(ctypes.get_last_error())}"
        )


@contextmanager
def _exclusive_kernel_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_regular_file(path, allow_missing=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    locked = False
    overlapped = _WinOverlapped()
    try:
        _validate_open_lock(descriptor, path)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)

        if os.name == "posix":
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
        elif os.name == "nt":
            _lock_windows(descriptor, overlapped)
            locked = True
        else:
            raise StateCommitError(
                "state commit kernel lock is unsupported on this platform"
            )

        # Re-check the named lock after acquisition; replacement races fail closed.
        _validate_open_lock(descriptor, path)
        yield
    finally:
        if locked:
            if os.name == "posix":
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif os.name == "nt":
                _unlock_windows(descriptor, overlapped)
        os.close(descriptor)


def _transition_expected_id(transition: SupervisorTransitionCandidate) -> str:
    seed = {
        "from_cycle_id": transition.from_cycle_id,
        "next_cycle_id": transition.next_cycle_id,
        "adjudication_ref": transition.decision_ref,
        "next_state_ref": self_state_ref(transition.next_self_state),
        "next_workspace_ref": workspace_ref(transition.next_workspace),
    }
    return "suptrans-" + _digest(seed)[:32]


def _commit_receipt(record: StateCommitJournalRecord) -> StateTransitionCommitReceipt:
    if record.state != "committed":
        raise StateCommitError("journal transaction is not committed")
    return StateTransitionCommitReceipt(
        schema="kaliv-consciousness-core/state-transition-commit-receipt/v1",
        transition_id=record.transition_id,
        from_self_state_ref=record.before_self_state_ref,
        committed_self_state_ref=record.after_self_state_ref,
        committed_revision=record.after_revision,
        commit_ref=record.commit_ref,
        persisted=True,
        production_activation=False,
    )


class LockedSelfStateCommitter:
    """Kernel-locked, journaled compare-and-swap SelfState authority."""

    def __init__(
        self,
        store: SelfStateStore | None = None,
        *,
        state_path: str | Path | None = None,
    ) -> None:
        if store is not None and state_path is not None:
            raise ValueError("provide either store or state_path, not both")
        self.store = store or SelfStateStore(state_path)
        self.lock_path = Path(str(self.store.path) + ".commit.lock")
        self.journal_path = Path(str(self.store.path) + ".commit-journal.json")

    def _read_journal(self) -> StateCommitJournalRecord | None:
        try:
            raw = _read_bounded(self.journal_path, _JOURNAL_MAX)
        except FileNotFoundError:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateCommitError("state commit journal is malformed") from exc
        try:
            return StateCommitJournalRecord.model_validate(payload)
        except ValidationError as exc:
            raise StateCommitError("state commit journal failed strict validation") from exc

    def _write_journal(self, record: StateCommitJournalRecord) -> None:
        _write_atomic(self.journal_path, record.model_dump(mode="json"))

    def _current_state(self) -> PersistentSelfState:
        _validate_regular_file(self.store.path, allow_missing=False)
        try:
            current = self.store.read()
        except SelfStateError as exc:
            raise StateCommitError("current SelfState cannot be verified") from exc
        if current is None:
            raise StateCommitError("current SelfState is missing")
        return current

    def _record(
        self,
        transition: SupervisorTransitionCandidate,
        current: PersistentSelfState,
        *,
        state: Literal["prepared", "committed", "aborted", "conflict"],
        error: str | None = None,
    ) -> StateCommitJournalRecord:
        before_ref = self_state_ref(current)
        after_ref = self_state_ref(transition.next_self_state)
        seed = {
            "transition_id": transition.transition_id,
            "before_self_state_ref": before_ref,
            "after_self_state_ref": after_ref,
            "before_revision": current.revision,
            "after_revision": transition.next_self_state.revision,
        }
        transaction_id = "stx-" + _digest(seed)[:32]
        return StateCommitJournalRecord(
            schema=_JOURNAL_SCHEMA,
            transaction_id=transaction_id,
            transition_id=transition.transition_id,
            state=state,
            before_self_state_ref=before_ref,
            after_self_state_ref=after_ref,
            before_revision=current.revision,
            after_revision=transition.next_self_state.revision,
            commit_ref=f"self-state-commit:{transaction_id}",
            error=error[:2048] if error else None,
            production_activation=False,
        )

    def _transition_record(
        self,
        record: StateCommitJournalRecord,
        *,
        state: Literal["committed", "aborted", "conflict"],
        error: str | None = None,
    ) -> StateCommitJournalRecord:
        updated = record.model_copy(
            update={
                "state": state,
                "error": error[:2048] if error else None,
            }
        )
        self._write_journal(updated)
        return updated

    def _recover_locked(self) -> StateCommitRecoveryReceipt:
        journal = self._read_journal()
        current = self._current_state()
        current_ref = self_state_ref(current)
        if journal is None:
            return StateCommitRecoveryReceipt(
                schema="kaliv-consciousness-core/state-commit-recovery/v1",
                outcome="none",
                transaction_id=None,
                transition_id=None,
                current_self_state_ref=current_ref,
                production_activation=False,
            )

        if journal.state == "prepared":
            if current_ref == journal.after_self_state_ref:
                journal = self._transition_record(journal, state="committed")
                outcome = "committed"
            elif current_ref == journal.before_self_state_ref:
                journal = self._transition_record(journal, state="aborted")
                outcome = "aborted"
            else:
                journal = self._transition_record(
                    journal,
                    state="conflict",
                    error="persisted SelfState matches neither side of prepared transaction",
                )
                outcome = "conflict"
        elif journal.state == "committed":
            if current_ref == journal.after_self_state_ref:
                outcome = "committed"
            else:
                journal = self._transition_record(
                    journal,
                    state="conflict",
                    error="committed journal no longer matches persisted SelfState",
                )
                outcome = "conflict"
        elif journal.state == "aborted":
            if current_ref == journal.before_self_state_ref:
                outcome = "aborted"
            else:
                journal = self._transition_record(
                    journal,
                    state="conflict",
                    error="aborted journal no longer matches its before state",
                )
                outcome = "conflict"
        else:
            outcome = "conflict"

        return StateCommitRecoveryReceipt(
            schema="kaliv-consciousness-core/state-commit-recovery/v1",
            outcome=outcome,
            transaction_id=journal.transaction_id,
            transition_id=journal.transition_id,
            current_self_state_ref=current_ref,
            production_activation=False,
        )

    def recover(self) -> StateCommitRecoveryReceipt:
        with _exclusive_kernel_lock(self.lock_path):
            return self._recover_locked()

    def commit(
        self,
        transition: SupervisorTransitionCandidate | Mapping[str, Any],
    ) -> StateTransitionCommitReceipt:
        try:
            item = (
                transition
                if isinstance(transition, SupervisorTransitionCandidate)
                else SupervisorTransitionCandidate.model_validate(transition)
            )
        except ValidationError as exc:
            raise StateCommitError("invalid supervisor transition") from exc

        if item.transition_id != _transition_expected_id(item):
            raise StateCommitError("supervisor transition integrity mismatch")
        if item.persistence_committed or item.model_invoked:
            raise StateCommitError("transition is not pristine for persistence")
        if item.next_self_state.workspace_ref != workspace_ref(item.next_workspace):
            raise StateCommitError("next SelfState/workspace binding mismatch")

        with _exclusive_kernel_lock(self.lock_path):
            recovery = self._recover_locked()
            if recovery.outcome == "conflict":
                raise StateCommitError("unresolved SelfState commit conflict")

            current = self._current_state()
            current_ref = self_state_ref(current)
            after_ref = self_state_ref(item.next_self_state)
            journal = self._read_journal()

            # Idempotent retry of the latest successfully committed transition.
            if (
                journal is not None
                and journal.state == "committed"
                and journal.transition_id == item.transition_id
                and journal.before_self_state_ref == item.from_self_state_ref
                and journal.after_self_state_ref == after_ref
                and current_ref == after_ref
            ):
                return _commit_receipt(journal)

            if current_ref != item.from_self_state_ref:
                raise StateCommitError("stale SelfState compare-and-swap source")
            if item.next_self_state.revision != current.revision + 1:
                raise StateCommitError("next SelfState revision must advance exactly by one")
            if item.next_self_state.self_id != current.self_id:
                raise StateCommitError("SelfState identity cannot change")
            if item.next_self_state.person_id != current.person_id:
                raise StateCommitError("SelfState person cannot change")
            if item.next_self_state.person_revision != current.person_revision:
                raise StateCommitError("C19 does not authorize Person Revision rebind")

            prepared = self._record(item, current, state="prepared")
            self._write_journal(prepared)

            try:
                self.store.write_next(item.next_self_state)
            except Exception as exc:
                observed = self._current_state()
                observed_ref = self_state_ref(observed)
                if observed_ref == prepared.after_self_state_ref:
                    # The authoritative replace happened despite the surfaced error.
                    try:
                        self._sync_committed_state()
                    except Exception as sync_exc:
                        self._transition_record(
                            prepared,
                            state="conflict",
                            error=f"state replaced but durability sync failed: {sync_exc}",
                        )
                        raise StateCommitError(
                            "SelfState replaced but durability could not be proven"
                        ) from sync_exc
                    committed = self._transition_record(prepared, state="committed")
                    return _commit_receipt(committed)
                if observed_ref == prepared.before_self_state_ref:
                    self._transition_record(
                        prepared,
                        state="aborted",
                        error=f"SelfState write aborted: {exc}",
                    )
                    raise StateCommitError("SelfState write aborted") from exc
                self._transition_record(
                    prepared,
                    state="conflict",
                    error="SelfState write failed with an unrelated persisted state",
                )
                raise StateCommitError("SelfState write produced a conflict") from exc

            try:
                self._sync_committed_state()
            except Exception as exc:
                self._transition_record(
                    prepared,
                    state="conflict",
                    error=f"SelfState durability sync failed: {exc}",
                )
                raise StateCommitError(
                    "SelfState was replaced but durability could not be proven"
                ) from exc

            observed = self._current_state()
            if self_state_ref(observed) != prepared.after_self_state_ref:
                self._transition_record(
                    prepared,
                    state="conflict",
                    error="post-write SelfState hash does not match prepared after state",
                )
                raise StateCommitError("post-write SelfState verification failed")
            if observed.revision != prepared.after_revision:
                self._transition_record(
                    prepared,
                    state="conflict",
                    error="post-write SelfState revision mismatch",
                )
                raise StateCommitError("post-write SelfState revision mismatch")

            committed = self._transition_record(prepared, state="committed")
            return _commit_receipt(committed)

    def _sync_committed_state(self) -> None:
        _validate_regular_file(self.store.path, allow_missing=False)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.store.path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_parent(self.store.path)
