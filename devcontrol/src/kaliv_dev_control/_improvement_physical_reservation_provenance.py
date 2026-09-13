"""Create-once descriptor-bound provenance for RSI physical reservation receipts.

Persisted bytes are replay/recovery state, never reloadable authority. Production
installation replaces the reservation implementation's create-once publication
for the permanent replay marker and final receipt with a primitive that keeps the
*original publication descriptor* open from O_CREAT|O_EXCL creation through
provenance registration. A byte-identical replacement between publication and
registration therefore cannot become the authority baseline.

The held descriptors are transaction-scoped with a ContextVar. Failed
transactions close any unclaimed descriptors while leaving durable files in
recovery state. Successful registration transfers the exact original final and
replay-marker descriptors into the live receipt registry. Unlink, replacement,
content mutation, receipt mutation, or fork invalidates provenance.
"""
from __future__ import annotations

import contextvars
import os
import stat
import weakref
from pathlib import Path
from typing import Any, Callable

from .durable_publication import (
    DurablePublicationError,
    create_once_file as _durable_create_once_file,
    sync_directory,
)
from .trusted_git_runtime_model import _has_linkish_component

_MAX_ARTIFACT_BYTES = 256 * 1024
_PUBLICATION_TOKEN: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "rsi_physical_reservation_publication_token",
    default=None,
)
# (transaction token, canonical path) -> (payload, descriptor, (dev, ino))
_HELD_PUBLICATIONS: dict[
    tuple[object, Path], tuple[bytes, int, tuple[int, int]]
] = {}


class DescriptorBoundProvenanceError(ValueError):
    """Live transaction provenance could not be bound safely."""


def _read_descriptor_exact(
    descriptor: int,
    *,
    maximum: int,
) -> tuple[bytes, os.stat_result]:
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > maximum
        ):
            raise DescriptorBoundProvenanceError(
                "reservation marker descriptor is unsafe"
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise DescriptorBoundProvenanceError(
                    "reservation marker descriptor read was incomplete"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise DescriptorBoundProvenanceError(
                "reservation marker descriptor grew while reading"
            )
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or after.st_nlink != 1
        ):
            raise DescriptorBoundProvenanceError(
                "reservation marker descriptor changed while reading"
            )
        return b"".join(chunks), after
    except OSError as exc:
        raise DescriptorBoundProvenanceError(
            "reservation marker descriptor could not be read"
        ) from exc


def _canonical_publication_path(path: Path) -> tuple[Path, Path]:
    destination = Path(path)
    if not destination.is_absolute() or _has_linkish_component(destination.parent):
        raise DurablePublicationError("create-once bound file path is unsafe")
    try:
        parent = destination.parent.resolve(strict=True)
    except OSError as exc:
        raise DurablePublicationError(
            "create-once bound file parent is unavailable"
        ) from exc
    if not parent.is_dir() or destination.parent.resolve() != parent:
        raise DurablePublicationError("create-once bound file parent is unsafe")
    return parent / destination.name, parent


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        try:
            written = os.write(descriptor, view[offset:])
        except OSError as exc:
            raise DurablePublicationError(
                "create-once bound file write failed"
            ) from exc
        if written <= 0:
            raise DurablePublicationError(
                "create-once bound file write was incomplete"
            )
        offset += written


def _publish_bound_file(path: Path, payload: bytes, *, mode: int) -> None:
    token = _PUBLICATION_TOKEN.get()
    if token is None:
        raise DurablePublicationError(
            "descriptor-bound publication requires an authenticated transaction"
        )
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_ARTIFACT_BYTES
        or not isinstance(mode, int)
        or isinstance(mode, bool)
    ):
        raise DurablePublicationError("create-once bound file inputs are invalid")

    destination, parent = _canonical_publication_path(path)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NOINHERIT", 0)
    )
    try:
        descriptor = os.open(destination, flags, mode)
    except FileExistsError:
        raise
    except OSError as exc:
        raise DurablePublicationError(
            "create-once bound file could not be created"
        ) from exc

    retained = False
    try:
        _write_all(descriptor, payload)
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise DurablePublicationError(
                "create-once bound file sync failed"
            ) from exc
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_size != len(payload)
        ):
            raise DurablePublicationError(
                "create-once bound file identity is unsafe"
            )
        sync_directory(parent)
        try:
            current = os.stat(destination, follow_symlinks=False)
        except OSError as exc:
            raise DurablePublicationError(
                "create-once bound file disappeared after publication"
            ) from exc
        identity = (int(observed.st_dev), int(observed.st_ino))
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (int(current.st_dev), int(current.st_ino)) != identity
        ):
            raise DurablePublicationError(
                "create-once bound file path changed after publication"
            )
        key = (token, destination)
        previous = _HELD_PUBLICATIONS.pop(key, None)
        if previous is not None:
            try:
                os.close(previous[1])
            except OSError:
                pass
            raise DurablePublicationError(
                "create-once bound file transaction published one path twice"
            )
        _HELD_PUBLICATIONS[key] = (bytes(payload), descriptor, identity)
        retained = True
    finally:
        if not retained:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _requires_identity_retention(path: Path) -> bool:
    name = Path(path).name
    # Reservation transaction creates exactly three files: .lock, .pending.json,
    # and final <sha>.json. Pending is temporary recovery state and does not carry
    # live provenance; the permanent lock and final receipt do.
    return name.endswith(".lock") or (
        name.endswith(".json") and not name.startswith(".")
    )


def _installed_create_once_file(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> None:
    if _PUBLICATION_TOKEN.get() is not None and _requires_identity_retention(path):
        _publish_bound_file(path, payload, mode=mode)
        return
    _durable_create_once_file(path, payload, mode=mode)


def _path_matches_held_marker(
    path: Path,
    expected_payload: bytes,
    held_descriptor: int,
    held_identity: tuple[int, int],
) -> bool:
    try:
        held_payload, held_stat = _read_descriptor_exact(
            held_descriptor,
            maximum=_MAX_ARTIFACT_BYTES,
        )
    except DescriptorBoundProvenanceError:
        return False
    if (
        held_payload != expected_payload
        or held_stat.st_nlink != 1
        or (int(held_stat.st_dev), int(held_stat.st_ino)) != held_identity
    ):
        return False

    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return False
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NOINHERIT", 0)
    )
    try:
        current_descriptor = os.open(candidate, flags)
    except OSError:
        return False
    try:
        current_payload, current_stat = _read_descriptor_exact(
            current_descriptor,
            maximum=_MAX_ARTIFACT_BYTES,
        )
        return (
            current_payload == expected_payload
            and current_stat.st_nlink == 1
            and (int(current_stat.st_dev), int(current_stat.st_ino))
            == held_identity
        )
    except DescriptorBoundProvenanceError:
        return False
    finally:
        os.close(current_descriptor)


def _claim_original_publication(
    path: Path,
    expected_payload: bytes,
) -> tuple[int, tuple[int, int]]:
    token = _PUBLICATION_TOKEN.get()
    if token is None:
        raise DescriptorBoundProvenanceError(
            "reservation provenance registration has no transaction token"
        )
    destination, _parent = _canonical_publication_path(path)
    entry = _HELD_PUBLICATIONS.pop((token, destination), None)
    if entry is None:
        raise DescriptorBoundProvenanceError(
            "reservation provenance has no original create-once publication"
        )
    payload, descriptor, identity = entry
    if payload != expected_payload or not _path_matches_held_marker(
        destination,
        expected_payload,
        descriptor,
        identity,
    ):
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise DescriptorBoundProvenanceError(
            "reservation marker changed after its original create-once publication"
        )
    return descriptor, identity


def _release_unclaimed_publications(token: object) -> None:
    keys = [key for key in _HELD_PUBLICATIONS if key[0] is token]
    for key in keys:
        _payload, descriptor, _identity = _HELD_PUBLICATIONS.pop(key)
        try:
            os.close(descriptor)
        except OSError:
            pass


def _descriptor_bound_transaction_registry():
    # identity -> (pid, receipt sha, final path/payload/fd/id,
    #              lock path/payload/fd/id, weakref)
    references: dict[int, tuple[Any, ...]] = {}

    def close_entry(entry: tuple[Any, ...]) -> None:
        for descriptor in (entry[4], entry[8]):
            try:
                os.close(descriptor)
            except OSError:
                pass

    def mark(
        value: Any,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        final_descriptor, final_identity = _claim_original_publication(
            final_path,
            final_payload,
        )
        try:
            lock_descriptor, lock_identity = _claim_original_publication(
                lock_path,
                lock_payload,
            )
        except Exception:
            try:
                os.close(final_descriptor)
            except OSError:
                pass
            raise

        identity = id(value)
        previous = references.pop(identity, None)
        if previous is not None:
            close_entry(previous)
        origin_pid = os.getpid()
        authenticated_sha256 = value.sha256

        def discard(reference: Any, *, identity: int = identity) -> None:
            entry = references.get(identity)
            if entry is not None and entry[9] is reference:
                references.pop(identity, None)
                close_entry(entry)

        reference = weakref.ref(value, discard)
        references[identity] = (
            origin_pid,
            authenticated_sha256,
            Path(final_path),
            bytes(final_payload),
            final_descriptor,
            final_identity,
            Path(lock_path),
            bytes(lock_payload),
            lock_descriptor,
            reference,
            lock_identity,
        )

    def contains(value: Any) -> bool:
        entry = references.get(id(value))
        if entry is None:
            return False
        (
            origin_pid,
            authenticated_sha256,
            final_path,
            final_payload,
            final_descriptor,
            final_identity,
            lock_path,
            lock_payload,
            lock_descriptor,
            reference,
            lock_identity,
        ) = entry
        if origin_pid != os.getpid() or reference() is not value:
            return False
        try:
            if value.sha256 != authenticated_sha256:
                return False
        except (AttributeError, TypeError, ValueError):
            return False
        return _path_matches_held_marker(
            final_path,
            final_payload,
            final_descriptor,
            final_identity,
        ) and _path_matches_held_marker(
            lock_path,
            lock_payload,
            lock_descriptor,
            lock_identity,
        )

    def after_fork_child() -> None:
        for entry in tuple(references.values()):
            close_entry(entry)
        references.clear()
        for _payload, descriptor, _identity in tuple(_HELD_PUBLICATIONS.values()):
            try:
                os.close(descriptor)
            except OSError:
                pass
        _HELD_PUBLICATIONS.clear()
        _PUBLICATION_TOKEN.set(None)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=after_fork_child)

    return mark, contains


mark_transaction_authenticated, is_transaction_authenticated = (
    _descriptor_bound_transaction_registry()
)


def _install_transaction_scope(implementation: Any) -> None:
    original_consume: Callable[..., Any] = implementation._consume_physical_qualification_request_once

    def descriptor_scoped_consume(*args: Any, **kwargs: Any) -> Any:
        transaction_token = object()
        context_token = _PUBLICATION_TOKEN.set(transaction_token)
        try:
            return original_consume(*args, **kwargs)
        finally:
            _release_unclaimed_publications(transaction_token)
            _PUBLICATION_TOKEN.reset(context_token)

    implementation._consume_physical_qualification_request_once = descriptor_scoped_consume


def install_descriptor_bound_provenance(implementation: Any) -> None:
    """Install create-time descriptor provenance before any production transaction."""

    if implementation is None:
        raise DescriptorBoundProvenanceError(
            "reservation implementation is unavailable"
        )
    if getattr(implementation, "_descriptor_bound_provenance_installed", False):
        return
    implementation.create_once_file = _installed_create_once_file
    implementation._mark_transaction_authenticated = mark_transaction_authenticated
    implementation._is_transaction_authenticated = is_transaction_authenticated
    _install_transaction_scope(implementation)
    implementation._descriptor_bound_provenance_installed = True


__all__: list[str] = []
