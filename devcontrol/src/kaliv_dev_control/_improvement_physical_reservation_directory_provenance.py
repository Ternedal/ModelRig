"""POSIX ledger-directory history binding for RSI reservation provenance.

File-level provenance keeps the original final/replay-marker descriptors. This
layer additionally retains the ledger-root directory inode plus a history guard
on its parent directory from the first permanent publication onward. Renaming
the whole ledger root through its parent changes the parent's ctime even when
the child files keep identical inode/bytes/ctime, so rename-away/replay/
rename-back cannot resurrect an older live receipt.
"""
from __future__ import annotations

import contextvars
import os
import stat
import weakref
from pathlib import Path
from typing import Any, Callable

_DIR_TOKEN: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "rsi_physical_reservation_directory_token",
    default=None,
)

# File creation inside the ledger legitimately changes the ledger directory's
# ctime, so the ledger itself is bound by (dev, ino). Its parent is the history
# guard and is bound by (dev, ino, ctime_ns); adding/removing files *inside* the
# ledger does not change that parent stamp, while renaming the ledger entry does.
_DirObjectIdentity = tuple[int, int]
_DirHistoryIdentity = tuple[int, int, int]


class DirectoryBoundProvenanceError(ValueError):
    """The canonical ledger directory history could not be bound safely."""


class _Binding:
    __slots__ = (
        "ledger_path",
        "ledger_descriptor",
        "ledger_identity",
        "guard_path",
        "guard_descriptor",
        "guard_identity",
        "transaction_token",
        "reference",
        "revoked",
    )

    def __init__(
        self,
        *,
        ledger_path: Path,
        ledger_descriptor: int,
        ledger_identity: _DirObjectIdentity,
        guard_path: Path,
        guard_descriptor: int,
        guard_identity: _DirHistoryIdentity,
        transaction_token: object,
    ) -> None:
        self.ledger_path = ledger_path
        self.ledger_descriptor = ledger_descriptor
        self.ledger_identity = ledger_identity
        self.guard_path = guard_path
        self.guard_descriptor = guard_descriptor
        self.guard_identity = guard_identity
        self.transaction_token = transaction_token
        self.reference = None
        self.revoked = False


def _ctime_ns(observed: os.stat_result) -> int:
    value = getattr(observed, "st_ctime_ns", None)
    if value is None:
        value = int(float(observed.st_ctime) * 1_000_000_000)
    return int(value)


def _object_identity(observed: os.stat_result) -> _DirObjectIdentity:
    return (int(observed.st_dev), int(observed.st_ino))


def _history_identity(observed: os.stat_result) -> _DirHistoryIdentity:
    return (int(observed.st_dev), int(observed.st_ino), _ctime_ns(observed))


def _open_directory(path: Path) -> tuple[int, os.stat_result]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DirectoryBoundProvenanceError(
            "reservation ledger directory could not be opened"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISDIR(observed.st_mode) or observed.st_nlink < 1:
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory descriptor is unsafe"
            )
        return descriptor, observed
    except Exception:
        os.close(descriptor)
        raise


def _capture_binding(ledger_path: Path, transaction_token: object) -> _Binding:
    ledger = Path(ledger_path).resolve(strict=True)
    guard = ledger.parent.resolve(strict=True)
    ledger_descriptor, ledger_stat = _open_directory(ledger)
    try:
        guard_descriptor, guard_stat = _open_directory(guard)
    except Exception:
        os.close(ledger_descriptor)
        raise
    binding = _Binding(
        ledger_path=ledger,
        ledger_descriptor=ledger_descriptor,
        ledger_identity=_object_identity(ledger_stat),
        guard_path=guard,
        guard_descriptor=guard_descriptor,
        guard_identity=_history_identity(guard_stat),
        transaction_token=transaction_token,
    )
    if not _binding_matches(binding):
        _close_binding(binding)
        raise DirectoryBoundProvenanceError(
            "reservation ledger directory changed while binding history"
        )
    return binding


def _binding_matches(binding: _Binding) -> bool:
    if binding.revoked:
        return False
    try:
        ledger_held = os.fstat(binding.ledger_descriptor)
        guard_held = os.fstat(binding.guard_descriptor)
        ledger_path = os.stat(binding.ledger_path, follow_symlinks=False)
        guard_path = os.stat(binding.guard_path, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISDIR(ledger_held.st_mode)
        and ledger_held.st_nlink >= 1
        and stat.S_ISDIR(ledger_path.st_mode)
        and ledger_path.st_nlink >= 1
        and _object_identity(ledger_held) == binding.ledger_identity
        and _object_identity(ledger_path) == binding.ledger_identity
        and stat.S_ISDIR(guard_held.st_mode)
        and guard_held.st_nlink >= 1
        and stat.S_ISDIR(guard_path.st_mode)
        and guard_path.st_nlink >= 1
        and _history_identity(guard_held) == binding.guard_identity
        and _history_identity(guard_path) == binding.guard_identity
    )


def _close_binding(binding: _Binding) -> None:
    for descriptor_name in ("ledger_descriptor", "guard_descriptor"):
        descriptor = getattr(binding, descriptor_name)
        if descriptor < 0:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass
        setattr(binding, descriptor_name, -1)


def _requires_history_binding(path: Path) -> bool:
    name = Path(path).name
    return name.endswith(".lock") or (
        name.endswith(".json") and not name.startswith(".")
    )


def _install_posix_directory_history(implementation: Any) -> None:
    original_create_once: Callable[..., Any] = implementation.create_once_file
    original_mark: Callable[..., Any] = implementation._mark_transaction_authenticated
    original_is_authenticated: Callable[..., Any] = implementation._is_transaction_authenticated
    original_consume: Callable[..., Any] = implementation._consume_physical_qualification_request_once

    held: dict[tuple[object, Path], _Binding] = {}
    live: dict[int, _Binding] = {}

    def release_held(transaction_token: object) -> None:
        keys = [key for key in held if key[0] is transaction_token]
        for key in keys:
            binding = held.pop(key)
            _close_binding(binding)

    def revoke_live(binding: _Binding) -> None:
        binding.revoked = True
        _close_binding(binding)

    def revoke_transaction(transaction_token: object) -> None:
        for binding in tuple(live.values()):
            if binding.transaction_token is transaction_token:
                revoke_live(binding)

    def create_once_file(path: Path, payload: bytes, *, mode: int = 0o600) -> Any:
        token = _DIR_TOKEN.get()
        candidate = Path(path)
        if token is None or not _requires_history_binding(candidate):
            return original_create_once(candidate, payload, mode=mode)
        ledger_path = candidate.parent.resolve(strict=True)
        key = (token, ledger_path)
        binding = held.get(key)
        created_binding = False
        if binding is None:
            binding = _capture_binding(ledger_path, token)
            held[key] = binding
            created_binding = True
        elif not _binding_matches(binding):
            revoke_live(binding)
            held.pop(key, None)
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory history changed before publication"
            )
        try:
            result = original_create_once(candidate, payload, mode=mode)
            if not _binding_matches(binding):
                raise DirectoryBoundProvenanceError(
                    "reservation ledger directory history changed during publication"
                )
            return result
        except BaseException:
            if created_binding:
                held.pop(key, None)
                _close_binding(binding)
            raise

    def mark(value: Any, *, final_path: Path, final_payload: bytes, lock_path: Path, lock_payload: bytes) -> None:
        token = _DIR_TOKEN.get()
        if token is None:
            raise DirectoryBoundProvenanceError(
                "reservation directory provenance has no transaction token"
            )
        ledger_path = Path(final_path).parent.resolve(strict=True)
        if Path(lock_path).parent.resolve(strict=True) != ledger_path:
            raise DirectoryBoundProvenanceError(
                "reservation final and replay marker use different ledger roots"
            )
        key = (token, ledger_path)
        binding = held.get(key)
        if binding is None or not _binding_matches(binding):
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory history is unavailable"
            )
        # File-level provenance claims the original create-once file descriptors.
        # If this call fails, the outer scopes release/revoke all retained state.
        original_mark(
            value,
            final_path=final_path,
            final_payload=final_payload,
            lock_path=lock_path,
            lock_payload=lock_payload,
        )
        if not _binding_matches(binding):
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory history changed at registration"
            )
        held.pop(key, None)
        identity = id(value)
        previous = live.pop(identity, None)
        if previous is not None:
            revoke_live(previous)

        def discard(reference: Any, *, identity: int = identity) -> None:
            entry = live.get(identity)
            if entry is not None and entry.reference is reference:
                live.pop(identity, None)
                _close_binding(entry)

        binding.reference = weakref.ref(value, discard)
        live[identity] = binding

    def is_authenticated(value: Any) -> bool:
        # Preserve the underlying content/fork/file provenance semantics. In
        # particular, reversible in-memory content mutation may make this false
        # temporarily without revoking the directory-history binding.
        if not original_is_authenticated(value):
            return False
        binding = live.get(id(value))
        if binding is None or binding.reference is None or binding.reference() is not value:
            return False
        if not _binding_matches(binding):
            revoke_live(binding)
            return False
        return True

    def consume(*args: Any, **kwargs: Any) -> Any:
        transaction_token = object()
        context_token = _DIR_TOKEN.set(transaction_token)
        try:
            return original_consume(*args, **kwargs)
        except BaseException:
            revoke_transaction(transaction_token)
            raise
        finally:
            release_held(transaction_token)
            _DIR_TOKEN.reset(context_token)

    def after_fork_child() -> None:
        for binding in tuple(held.values()):
            _close_binding(binding)
        held.clear()
        for binding in tuple(live.values()):
            _close_binding(binding)
        live.clear()
        _DIR_TOKEN.set(None)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=after_fork_child)

    implementation.create_once_file = create_once_file
    implementation._mark_transaction_authenticated = mark
    implementation._is_transaction_authenticated = is_authenticated
    implementation._consume_physical_qualification_request_once = consume


def install_directory_history_provenance(implementation: Any) -> None:
    """Install ledger-root rename-history binding after file provenance."""

    if implementation is None:
        raise DirectoryBoundProvenanceError("reservation implementation is unavailable")
    if getattr(implementation, "_directory_history_provenance_installed", False):
        return
    if os.name == "posix":
        _install_posix_directory_history(implementation)
    implementation._directory_history_provenance_installed = True


__all__: list[str] = []
