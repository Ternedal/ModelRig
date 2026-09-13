"""Descriptor-bound live provenance for RSI physical reservation receipts.

Persisted bytes are replay/recovery state, never reloadable authority. A live
receipt is authenticated only while the exact final and replay-marker file
objects opened by the successful transaction remain linked at their canonical
paths with the authenticated bytes. Open descriptors keep file identity alive,
so unlink-and-recreate cannot resurrect provenance even when replacement bytes
are identical.
"""
from __future__ import annotations

import os
import stat
import weakref
from pathlib import Path
from typing import Any

from .trusted_git_runtime_model import _has_linkish_component

_MAX_ARTIFACT_BYTES = 256 * 1024


class DescriptorBoundProvenanceError(ValueError):
    """Live transaction provenance could not be bound safely."""


def _read_descriptor_exact(descriptor: int, *, maximum: int) -> tuple[bytes, os.stat_result]:
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > maximum
        ):
            raise DescriptorBoundProvenanceError("reservation marker descriptor is unsafe")
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


def _open_bound_marker(path: Path, expected_payload: bytes) -> tuple[int, tuple[int, int]]:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or _has_linkish_component(candidate)
        or not isinstance(expected_payload, bytes)
        or not expected_payload
        or len(expected_payload) > _MAX_ARTIFACT_BYTES
    ):
        raise DescriptorBoundProvenanceError("reservation marker path/payload is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise DescriptorBoundProvenanceError(
            "reservation marker could not be opened for provenance"
        ) from exc
    try:
        payload, observed = _read_descriptor_exact(
            descriptor, maximum=_MAX_ARTIFACT_BYTES
        )
        if payload != expected_payload:
            raise DescriptorBoundProvenanceError(
                "reservation marker bytes changed before provenance registration"
            )
        return descriptor, (int(observed.st_dev), int(observed.st_ino))
    except Exception:
        os.close(descriptor)
        raise


def _path_matches_held_marker(
    path: Path,
    expected_payload: bytes,
    held_descriptor: int,
    held_identity: tuple[int, int],
) -> bool:
    try:
        held_payload, held_stat = _read_descriptor_exact(
            held_descriptor, maximum=_MAX_ARTIFACT_BYTES
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
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        current_descriptor = os.open(candidate, flags)
    except OSError:
        return False
    try:
        current_payload, current_stat = _read_descriptor_exact(
            current_descriptor, maximum=_MAX_ARTIFACT_BYTES
        )
        return (
            current_payload == expected_payload
            and current_stat.st_nlink == 1
            and (int(current_stat.st_dev), int(current_stat.st_ino)) == held_identity
        )
    except DescriptorBoundProvenanceError:
        return False
    finally:
        os.close(current_descriptor)


def _descriptor_bound_transaction_registry():
    # identity -> (pid, receipt sha, final path/payload/fd/id, lock path/payload/fd/id, weakref)
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
        final_descriptor, final_identity = _open_bound_marker(
            final_path, final_payload
        )
        try:
            lock_descriptor, lock_identity = _open_bound_marker(
                lock_path, lock_payload
            )
        except Exception:
            os.close(final_descriptor)
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

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=after_fork_child)

    return mark, contains


mark_transaction_authenticated, is_transaction_authenticated = (
    _descriptor_bound_transaction_registry()
)


def install_descriptor_bound_provenance(implementation: Any) -> None:
    """Replace the implementation's in-memory provenance hooks before production use."""

    if implementation is None:
        raise DescriptorBoundProvenanceError("reservation implementation is unavailable")
    implementation._mark_transaction_authenticated = mark_transaction_authenticated
    implementation._is_transaction_authenticated = is_transaction_authenticated


__all__: list[str] = []
