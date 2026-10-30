"""Atomic gallery index update with fail-closed single-writer lock.

The lock is deliberately not stolen automatically: an operator must investigate
an abandoned lock after a crash before removing it.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .media_gallery_catalog import (
    GalleryUnavailable, _index, _root, _MAX_INDEX_BYTES, _MAX_INDEX_ITEMS,
)


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
    lock = root / ".gallery-index.lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(lock, flags, 0o600)
    except FileExistsError as exc:
        raise GalleryUnavailable("gallery_index_locked") from exc
    temporary = None
    try:
        os.close(descriptor)
        index_path = root / "gallery-index.json"
        if index_path.exists() or index_path.is_symlink():
            # _index validates the existing catalog and refuses symlinks.
            entries = _index(root)
            # Strip computed presentation-only fields before serialization.
            entries = [
                {k: v for k, v in item.items()
                 if k not in ("url", "thumbnail_url", "playback")}
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
        lock.unlink(missing_ok=True)
