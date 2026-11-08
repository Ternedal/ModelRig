"""Atomic gallery index update under a process-lifetime single-writer lock.

**The lock is an OS lock, not the existence of a file.** It is ``fcntl.flock`` on POSIX and
``msvcrt.locking`` on Windows, taken on a persistent ``.gallery-index.lock``. The helpers are the
same ones ``gpu_lease`` uses. The OS releases the lock when its process dies, so a writer killed
inside the window (SIGKILL, power loss, a supervisor's timeout kill) blocks nobody afterwards.
Before this change, the lock was the file's mere existence (``O_CREAT|O_EXCL``), and one such
kill blocked every later registration until someone removed the file (C8, #2275 6680066477).

**The file is never unlinked, here or anywhere.** Unlinking a flock'd file would let two writers
hold locks on different inodes. A leftover file from the old writer is now just an unlocked file.

**The open is refused** if the path is a symlink, a reparse point or not a regular file, or if it
is swapped between the check and the open.

**Acquisition waits a bounded time** (``LOCK_TIMEOUT_S``, with backoff), so two writers that
finish together, e.g. one executor per GPU, are serialised instead of one failing. Only then does
it raise ``gallery_index_locked``, which is fail-closed as before.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .gpu_lease import _try_lock, _unlock
from .media_gallery_catalog import (
    GalleryUnavailable, _index, _root, _MAX_INDEX_BYTES, _MAX_INDEX_ITEMS,
)

LOCK_NAME = ".gallery-index.lock"
LOCK_TIMEOUT_S = 5.0
_REPARSE_POINT = 0x400


def _refusable(info) -> bool:
    return (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT))


@contextmanager
def index_lock(root: Path, *, timeout_s: float | None = None):
    """Hold the gallery index lock in ``root`` for the duration of the ``with`` block."""
    timeout_s = LOCK_TIMEOUT_S if timeout_s is None else timeout_s
    path = root / LOCK_NAME
    try:
        if _refusable(os.lstat(path)):
            raise GalleryUnavailable("gallery_index_lock_refused")
    except FileNotFoundError:
        pass
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise GalleryUnavailable("gallery_index_lock_refused") from exc
    try:
        opened = os.fstat(fd)
        named = os.lstat(path)
        if (not stat.S_ISREG(opened.st_mode) or _refusable(named)
                or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)):
            raise GalleryUnavailable("gallery_index_lock_refused")
        deadline = time.monotonic() + timeout_s
        delay = 0.01
        while True:
            try:
                _try_lock(fd)
                break
            except OSError:  # held by another live process (BlockingIOError / EACCES on Windows)
                if time.monotonic() >= deadline:
                    raise GalleryUnavailable("gallery_index_locked") from None
                time.sleep(delay)
                delay = min(delay * 2, 0.2)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def register_asset(media_root: str | Path, verified_volume_root: str | Path,
                   asset_id: str, extension: str, size_bytes: int) -> None:
    """Register a previously durably published asset; never silently reset index."""
    from .media_gallery_catalog import _ID
    if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
        raise ValueError("invalid_asset_id")
    if extension not in (".png", ".mp4"):
        raise ValueError("invalid_extension")
    if type(size_bytes) is not int or size_bytes <= 0:
        raise ValueError("invalid_size")
    root = _root(media_root, verified_volume_root=verified_volume_root)
    # A catalog row must never point to an absent or differently sized asset.
    # lstat refuses symlinks; the asset is opened without following them.
    import stat
    asset_path = root / (asset_id + extension)
    if asset_path.is_symlink():
        raise GalleryUnavailable("asset_symlink_refused")
    try:
        fd = os.open(asset_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size != size_bytes:
                raise GalleryUnavailable("asset_size_mismatch")
        finally:
            os.close(fd)
    except OSError as exc:
        raise GalleryUnavailable("asset_unavailable") from exc
    with index_lock(root):
        _write_entry(media_root, verified_volume_root, root, asset_id, extension, size_bytes)


def _write_entry(media_root, verified_volume_root, root: Path, asset_id: str, extension: str,
                 size_bytes: int) -> None:
    """The index read-modify-replace. The caller holds index_lock(root)."""
    temporary = None
    try:
        index_path = root / "gallery-index.json"
        if index_path.exists() or index_path.is_symlink():
            # _index validates the existing catalog and refuses symlinks.
            entries = _index(root)
            # Strip computed presentation-only fields before serialization.
            entries = [
                {**{k: v for k, v in item.items()
                    if k not in ("url", "thumbnail_url", "playback")},
                 "supports_range": item["playback"]["supports_range"]}
                for item in entries
            ]
        else:
            entries = []
        existing = next((item for item in entries if item["id"] == asset_id), None)
        if existing is not None:
            kind = "video" if extension == ".mp4" else "image"
            mime = "video/mp4" if extension == ".mp4" else "image/png"
            if (existing["kind"], existing["mime_type"], existing["size_bytes"]) == (kind, mime, size_bytes):
                return  # Idempotent retry; preserve the original timestamp.
            raise GalleryUnavailable("duplicate_index_id")
        if len(entries) >= _MAX_INDEX_ITEMS:
            raise GalleryUnavailable("index_item_limit")
        entries.append({
            "id": asset_id, "kind": "video" if extension == ".mp4" else "image",
            "mime_type": "video/mp4" if extension == ".mp4" else "image/png",
            "size_bytes": size_bytes,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
        payload = json.dumps(entries, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(payload) > _MAX_INDEX_BYTES:
            raise GalleryUnavailable("index_too_large")
        # Recheck mount before writing; never create a fallback directory.
        _root(media_root, verified_volume_root=verified_volume_root)
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".gallery-index-", suffix=".tmp",
                                         dir=root, delete=False) as f:
            temporary = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        _root(media_root, verified_volume_root=verified_volume_root)
        os.replace(temporary, index_path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
