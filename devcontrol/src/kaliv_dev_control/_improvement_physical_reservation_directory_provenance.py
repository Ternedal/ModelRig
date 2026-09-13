"""POSIX ledger-directory path-history binding for RSI reservation provenance.

File-level provenance retains the original final/replay-marker descriptors. This
layer additionally retains the ledger-root directory object and an event-history
monitor armed before the first permanent publication. A whole-ledger rename is
therefore monotonic evidence even if the exact directory is later moved back to
its original pathname.

The monitor is intentionally scoped to the ledger directory itself, not its
parent. Unrelated sibling creation under the shared host-state root must not
revoke an otherwise valid reservation. Linux uses inotify IN_MOVE_SELF /
IN_DELETE_SELF / IN_UNMOUNT. BSD-style POSIX systems use a kqueue vnode rename /
delete / revoke filter when available. Unsupported POSIX history monitoring fails
closed at reservation publication rather than silently weakening provenance.
"""
from __future__ import annotations

import contextvars
import ctypes
import os
import select
import stat
import weakref
from pathlib import Path
from typing import Any, Callable

_DIR_TOKEN: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "rsi_physical_reservation_directory_token",
    default=None,
)

_DirObjectIdentity = tuple[int, int]

_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_UNMOUNT = 0x00002000
_IN_IGNORED = 0x00008000
_IN_HISTORY_MASK = _IN_DELETE_SELF | _IN_MOVE_SELF | _IN_UNMOUNT | _IN_IGNORED


class DirectoryBoundProvenanceError(ValueError):
    """The canonical ledger directory history could not be bound safely."""


class _Binding:
    __slots__ = (
        "ledger_path",
        "ledger_descriptor",
        "ledger_identity",
        "history_kind",
        "history_handle",
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
        history_kind: str,
        history_handle: Any,
        transaction_token: object,
    ) -> None:
        self.ledger_path = ledger_path
        self.ledger_descriptor = ledger_descriptor
        self.ledger_identity = ledger_identity
        self.history_kind = history_kind
        self.history_handle = history_handle
        self.transaction_token = transaction_token
        self.reference = None
        self.revoked = False


def _ctime_ns(observed: os.stat_result) -> int:
    value = getattr(observed, "st_ctime_ns", None)
    if value is None:
        value = int(float(observed.st_ctime) * 1_000_000_000)
    return int(value)


def _object_identity(observed: os.stat_result) -> _DirObjectIdentity:
    return int(observed.st_dev), int(observed.st_ino)


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


def _is_linux() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "uname")
        and os.uname().sysname == "Linux"
    )


def _start_linux_history(path: Path) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    init1 = getattr(libc, "inotify_init1", None)
    add_watch = getattr(libc, "inotify_add_watch", None)
    if init1 is None or add_watch is None:
        raise DirectoryBoundProvenanceError(
            "reservation ledger rename-history monitor is unavailable"
        )
    init1.argtypes = [ctypes.c_int]
    init1.restype = ctypes.c_int
    add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    add_watch.restype = ctypes.c_int

    flags = os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    descriptor = init1(flags)
    if descriptor < 0:
        raise DirectoryBoundProvenanceError(
            "reservation ledger rename-history monitor could not be opened"
        )
    try:
        watch = add_watch(descriptor, os.fsencode(os.fspath(path)), _IN_HISTORY_MASK)
        if watch < 0:
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory could not be history-watched"
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _start_kqueue_history(descriptor: int) -> Any:
    kqueue_type = getattr(select, "kqueue", None)
    kevent_type = getattr(select, "kevent", None)
    if kqueue_type is None or kevent_type is None:
        raise DirectoryBoundProvenanceError(
            "reservation ledger rename-history monitor is unavailable"
        )
    required = (
        "KQ_FILTER_VNODE",
        "KQ_EV_ADD",
        "KQ_EV_CLEAR",
        "KQ_NOTE_RENAME",
        "KQ_NOTE_DELETE",
    )
    if any(not hasattr(select, name) for name in required):
        raise DirectoryBoundProvenanceError(
            "reservation ledger vnode history flags are unavailable"
        )
    fflags = select.KQ_NOTE_RENAME | select.KQ_NOTE_DELETE
    if hasattr(select, "KQ_NOTE_REVOKE"):
        fflags |= select.KQ_NOTE_REVOKE
    queue = kqueue_type()
    try:
        change = kevent_type(
            descriptor,
            filter=select.KQ_FILTER_VNODE,
            flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
            fflags=fflags,
        )
        queue.control([change], 0, 0)
        return queue
    except BaseException:
        queue.close()
        raise


def _start_history(path: Path, ledger_descriptor: int) -> tuple[str, Any]:
    if _is_linux():
        return "inotify", _start_linux_history(path)
    if hasattr(select, "kqueue"):
        return "kqueue", _start_kqueue_history(ledger_descriptor)
    raise DirectoryBoundProvenanceError(
        "exact reservation ledger rename-history monitoring is unsupported"
    )


def _history_clean(binding: _Binding) -> bool:
    if binding.history_kind == "inotify":
        try:
            event = os.read(binding.history_handle, 4096)
        except BlockingIOError:
            return True
        except OSError:
            return False
        return not event
    if binding.history_kind == "kqueue":
        try:
            return not binding.history_handle.control(None, 1, 0)
        except (OSError, ValueError):
            return False
    return False


def _capture_binding(ledger_path: Path, transaction_token: object) -> _Binding:
    ledger = Path(ledger_path).resolve(strict=True)
    ledger_descriptor, before = _open_directory(ledger)
    before_identity = _object_identity(before)
    before_ctime = _ctime_ns(before)
    history_kind = ""
    history_handle: Any = None
    try:
        path_before = os.stat(ledger, follow_symlinks=False)
        if (
            not stat.S_ISDIR(path_before.st_mode)
            or _object_identity(path_before) != before_identity
        ):
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory changed before history monitoring"
            )
        history_kind, history_handle = _start_history(ledger, ledger_descriptor)
        after = os.fstat(ledger_descriptor)
        path_after = os.stat(ledger, follow_symlinks=False)
        # ctime is used only to close the setup race before the event monitor is
        # known to be armed. Once armed, child-file writes may change directory
        # ctime and are intentionally irrelevant to path-history authority.
        if (
            _object_identity(after) != before_identity
            or _object_identity(path_after) != before_identity
            or _ctime_ns(after) != before_ctime
            or _ctime_ns(path_after) != before_ctime
        ):
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory changed while arming history monitor"
            )
        binding = _Binding(
            ledger_path=ledger,
            ledger_descriptor=ledger_descriptor,
            ledger_identity=before_identity,
            history_kind=history_kind,
            history_handle=history_handle,
            transaction_token=transaction_token,
        )
        if not _binding_matches(binding):
            raise DirectoryBoundProvenanceError(
                "reservation ledger directory changed while binding history"
            )
        return binding
    except BaseException:
        if history_kind == "inotify" and isinstance(history_handle, int):
            try:
                os.close(history_handle)
            except OSError:
                pass
        elif history_kind == "kqueue" and history_handle is not None:
            try:
                history_handle.close()
            except (OSError, ValueError):
                pass
        os.close(ledger_descriptor)
        raise


def _binding_matches(binding: _Binding) -> bool:
    if binding.revoked or not _history_clean(binding):
        return False
    try:
        ledger_held = os.fstat(binding.ledger_descriptor)
        ledger_path = os.stat(binding.ledger_path, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISDIR(ledger_held.st_mode)
        and ledger_held.st_nlink >= 1
        and stat.S_ISDIR(ledger_path.st_mode)
        and ledger_path.st_nlink >= 1
        and _object_identity(ledger_held) == binding.ledger_identity
        and _object_identity(ledger_path) == binding.ledger_identity
    )


def _close_binding(binding: _Binding) -> None:
    if binding.ledger_descriptor >= 0:
        try:
            os.close(binding.ledger_descriptor)
        except OSError:
            pass
        binding.ledger_descriptor = -1
    if binding.history_kind == "inotify" and isinstance(binding.history_handle, int):
        try:
            os.close(binding.history_handle)
        except OSError:
            pass
    elif binding.history_kind == "kqueue" and binding.history_handle is not None:
        try:
            binding.history_handle.close()
        except (OSError, ValueError):
            pass
    binding.history_handle = None


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

    def mark(
        value: Any,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
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
        if not original_is_authenticated(value):
            return False
        binding = live.get(id(value))
        if (
            binding is None
            or binding.reference is None
            or binding.reference() is not value
        ):
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
        raise DirectoryBoundProvenanceError(
            "reservation implementation is unavailable"
        )
    if getattr(implementation, "_directory_history_provenance_installed", False):
        return
    if os.name == "posix":
        _install_posix_directory_history(implementation)
    implementation._directory_history_provenance_installed = True


__all__: list[str] = []
