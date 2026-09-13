"""POSIX directory-chain path-history binding for RSI reservation provenance.

File-level provenance retains the original final/replay-marker descriptors. This
layer additionally binds the ledger directory and every ancestor entry back to
the filesystem root before the first permanent publication. A rename/delete of
the ledger itself *or of an ancestor that changes its canonical pathname* is
therefore monotonic evidence even if the exact directory tree is later restored.

Linux uses one inotify instance with parent-directory watches. Events are
filtered to the exact protected child name for each ancestry edge, so unrelated
sibling churn does not revoke a valid receipt. BSD-style POSIX systems use
kqueue vnode rename/delete/revoke filters on every retained directory object.
Unsupported POSIX history monitoring fails closed at reservation publication
rather than silently weakening provenance.
"""
from __future__ import annotations

import contextvars
import ctypes
import os
import select
import stat
import struct
import weakref
from pathlib import Path
from typing import Any, Callable

_DIR_TOKEN: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "rsi_physical_reservation_directory_token",
    default=None,
)

_DirObjectIdentity = tuple[int, int]

_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_UNMOUNT = 0x00002000
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_IN_PARENT_MASK = (
    _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
    | _IN_UNMOUNT
)
_IN_CHILD_PATH_MASK = _IN_MOVED_FROM | _IN_MOVED_TO | _IN_CREATE | _IN_DELETE
_INOTIFY_EVENT = struct.Struct("iIII")


class DirectoryBoundProvenanceError(ValueError):
    """The canonical ledger directory history could not be bound safely."""


class _Node:
    __slots__ = ("path", "descriptor", "identity")

    def __init__(
        self,
        *,
        path: Path,
        descriptor: int,
        identity: _DirObjectIdentity,
    ) -> None:
        self.path = path
        self.descriptor = descriptor
        self.identity = identity


class _Binding:
    __slots__ = (
        "ledger_path",
        "nodes",
        "history_kind",
        "history_handle",
        "history_expected",
        "transaction_token",
        "reference",
        "revoked",
    )

    def __init__(
        self,
        *,
        ledger_path: Path,
        nodes: tuple[_Node, ...],
        history_kind: str,
        history_handle: Any,
        history_expected: dict[int, bytes] | None,
        transaction_token: object,
    ) -> None:
        self.ledger_path = ledger_path
        self.nodes = nodes
        self.history_kind = history_kind
        self.history_handle = history_handle
        self.history_expected = history_expected
        self.transaction_token = transaction_token
        self.reference = None
        self.revoked = False


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
            "reservation directory-chain object could not be opened"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISDIR(observed.st_mode) or observed.st_nlink < 1:
            raise DirectoryBoundProvenanceError(
                "reservation directory-chain descriptor is unsafe"
            )
        return descriptor, observed
    except Exception:
        os.close(descriptor)
        raise


def _directory_chain(ledger: Path) -> tuple[Path, ...]:
    resolved = Path(ledger).resolve(strict=True)
    chain: list[Path] = []
    cursor = resolved
    while cursor.parent != cursor:
        chain.append(cursor)
        cursor = cursor.parent
    chain.reverse()
    if not chain or chain[-1] != resolved:
        raise DirectoryBoundProvenanceError(
            "reservation ledger directory ancestry is invalid"
        )
    return tuple(chain)


def _capture_nodes(ledger: Path) -> tuple[_Node, ...]:
    nodes: list[_Node] = []
    try:
        for path in _directory_chain(ledger):
            descriptor, observed = _open_directory(path)
            try:
                current = os.stat(path, follow_symlinks=False)
            except OSError:
                os.close(descriptor)
                raise
            identity = _object_identity(observed)
            if (
                not stat.S_ISDIR(current.st_mode)
                or current.st_nlink < 1
                or _object_identity(current) != identity
            ):
                os.close(descriptor)
                raise DirectoryBoundProvenanceError(
                    "reservation directory-chain path changed while capturing identity"
                )
            nodes.append(
                _Node(
                    path=path,
                    descriptor=descriptor,
                    identity=identity,
                )
            )
        return tuple(nodes)
    except BaseException:
        for node in nodes:
            try:
                os.close(node.descriptor)
            except OSError:
                pass
        raise


def _is_linux() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "uname")
        and os.uname().sysname == "Linux"
    )


def _start_linux_history(nodes: tuple[_Node, ...]) -> tuple[int, dict[int, bytes]]:
    libc = ctypes.CDLL(None, use_errno=True)
    init1 = getattr(libc, "inotify_init1", None)
    add_watch = getattr(libc, "inotify_add_watch", None)
    if init1 is None or add_watch is None:
        raise DirectoryBoundProvenanceError(
            "reservation directory-chain history monitor is unavailable"
        )
    init1.argtypes = [ctypes.c_int]
    init1.restype = ctypes.c_int
    add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    add_watch.restype = ctypes.c_int

    flags = os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    descriptor = init1(flags)
    if descriptor < 0:
        raise DirectoryBoundProvenanceError(
            "reservation directory-chain history monitor could not be opened"
        )
    expected: dict[int, bytes] = {}
    try:
        for node in nodes:
            parent = node.path.parent
            watch = add_watch(
                descriptor,
                os.fsencode(os.fspath(parent)),
                _IN_PARENT_MASK,
            )
            if watch < 0:
                raise DirectoryBoundProvenanceError(
                    "reservation directory-chain parent could not be history-watched"
                )
            protected_name = os.fsencode(node.path.name)
            previous = expected.get(watch)
            if previous is not None and previous != protected_name:
                raise DirectoryBoundProvenanceError(
                    "reservation directory-chain watch identity collided"
                )
            expected[watch] = protected_name
        return descriptor, expected
    except BaseException:
        os.close(descriptor)
        raise


def _start_kqueue_history(nodes: tuple[_Node, ...]) -> Any:
    kqueue_type = getattr(select, "kqueue", None)
    kevent_type = getattr(select, "kevent", None)
    if kqueue_type is None or kevent_type is None:
        raise DirectoryBoundProvenanceError(
            "reservation directory-chain history monitor is unavailable"
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
            "reservation directory-chain vnode history flags are unavailable"
        )
    fflags = select.KQ_NOTE_RENAME | select.KQ_NOTE_DELETE
    if hasattr(select, "KQ_NOTE_REVOKE"):
        fflags |= select.KQ_NOTE_REVOKE
    queue = kqueue_type()
    try:
        changes = [
            kevent_type(
                node.descriptor,
                filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=fflags,
            )
            for node in nodes
        ]
        queue.control(changes, 0, 0)
        return queue
    except BaseException:
        queue.close()
        raise


def _start_history(
    nodes: tuple[_Node, ...],
) -> tuple[str, Any, dict[int, bytes] | None]:
    if _is_linux():
        handle, expected = _start_linux_history(nodes)
        return "inotify", handle, expected
    if hasattr(select, "kqueue"):
        return "kqueue", _start_kqueue_history(nodes), None
    raise DirectoryBoundProvenanceError(
        "exact reservation directory-chain rename-history monitoring is unsupported"
    )


def _linux_history_clean(binding: _Binding) -> bool:
    if not isinstance(binding.history_handle, int) or binding.history_expected is None:
        return False
    while True:
        try:
            payload = os.read(binding.history_handle, 64 * 1024)
        except BlockingIOError:
            return True
        except OSError:
            return False
        if not payload:
            return False
        offset = 0
        while offset < len(payload):
            if len(payload) - offset < _INOTIFY_EVENT.size:
                return False
            watch, mask, _cookie, name_length = _INOTIFY_EVENT.unpack_from(
                payload,
                offset,
            )
            end = offset + _INOTIFY_EVENT.size + int(name_length)
            if end > len(payload):
                return False
            raw_name = payload[offset + _INOTIFY_EVENT.size : end]
            name = raw_name.split(b"\x00", 1)[0]
            if mask & _IN_Q_OVERFLOW:
                return False
            expected_name = binding.history_expected.get(watch)
            if expected_name is None:
                return False
            if mask & (_IN_DELETE_SELF | _IN_MOVE_SELF | _IN_UNMOUNT | _IN_IGNORED):
                return False
            if name == expected_name and mask & _IN_CHILD_PATH_MASK:
                return False
            offset = end


def _history_clean(binding: _Binding) -> bool:
    if binding.history_kind == "inotify":
        return _linux_history_clean(binding)
    if binding.history_kind == "kqueue":
        try:
            return not binding.history_handle.control(None, len(binding.nodes), 0)
        except (OSError, ValueError):
            return False
    return False


def _capture_binding(ledger_path: Path, transaction_token: object) -> _Binding:
    ledger = Path(ledger_path).resolve(strict=True)
    nodes = _capture_nodes(ledger)
    history_kind = ""
    history_handle: Any = None
    history_expected: dict[int, bytes] | None = None
    try:
        history_kind, history_handle, history_expected = _start_history(nodes)
        binding = _Binding(
            ledger_path=ledger,
            nodes=nodes,
            history_kind=history_kind,
            history_handle=history_handle,
            history_expected=history_expected,
            transaction_token=transaction_token,
        )
        if not _binding_matches(binding):
            raise DirectoryBoundProvenanceError(
                "reservation directory-chain changed while binding history"
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
        for node in nodes:
            try:
                os.close(node.descriptor)
            except OSError:
                pass
        raise


def _binding_matches(binding: _Binding) -> bool:
    if binding.revoked or not _history_clean(binding):
        return False
    try:
        for node in binding.nodes:
            held = os.fstat(node.descriptor)
            current = os.stat(node.path, follow_symlinks=False)
            if (
                not stat.S_ISDIR(held.st_mode)
                or held.st_nlink < 1
                or not stat.S_ISDIR(current.st_mode)
                or current.st_nlink < 1
                or _object_identity(held) != node.identity
                or _object_identity(current) != node.identity
            ):
                return False
    except OSError:
        return False
    return True


def _close_binding(binding: _Binding) -> None:
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
    binding.history_expected = None
    for node in binding.nodes:
        if node.descriptor >= 0:
            try:
                os.close(node.descriptor)
            except OSError:
                pass
            node.descriptor = -1


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
                "reservation directory-chain history changed before publication"
            )
        try:
            result = original_create_once(candidate, payload, mode=mode)
            if not _binding_matches(binding):
                raise DirectoryBoundProvenanceError(
                    "reservation directory-chain history changed during publication"
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
                "reservation directory-chain history is unavailable"
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
                "reservation directory-chain history changed at registration"
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
    """Install ledger + ancestor rename-history binding after file provenance."""

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
