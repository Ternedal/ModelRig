"""Fail-closed media asset lookup and bounded reads; no HTTP route or auth.

Only call after the transport has authenticated the paired client.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from .media_gallery_catalog import _root, _index, GalleryUnavailable
from .media_gallery_range import select_range, RangeNotSatisfiable

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg",
              "image/webp": ".webp", "video/mp4": ".mp4"}


class GalleryAssetNotFound(LookupError):
    pass


def open_asset(media_root: str | Path, verified_volume_root: str | Path,
               asset_id: str):
    """Return (binary file handle, validated catalog entry); caller closes handle."""
    if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
        raise GalleryAssetNotFound("invalid_asset_id")
    root = _root(media_root, verified_volume_root=verified_volume_root)
    entries = _index(root)
    entry = next((item for item in entries if item["id"] == asset_id), None)
    if entry is None:
        raise GalleryAssetNotFound("unknown_asset")
    target = root / (asset_id + _EXTENSION[entry["mime_type"]])
    if target.is_symlink():
        raise GalleryUnavailable("asset_symlink_refused")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size != entry["size_bytes"]:
                raise GalleryUnavailable("asset_size_mismatch")
            if target.is_symlink():
                raise GalleryUnavailable("asset_symlink_refused")
            return os.fdopen(descriptor, "rb"), entry
        except BaseException:
            os.close(descriptor)
            raise
    except FileNotFoundError as exc:
        raise GalleryAssetNotFound("missing_asset") from exc


def read_asset_range(handle, entry: dict, header: str | None,
                     *, max_chunk: int = 8 * 1024 * 1024) -> tuple[bytes, int, dict]:
    """Bounded helper for an authenticated adapter; full assets need streaming.

    Refuses an unbounded 200 read above max_chunk. The HTTP adapter must use
    bounded incremental streaming for large full responses instead.
    """
    start, end, status = select_range(header, entry["size_bytes"], max_chunk=max_chunk)
    length = end - start + 1
    if length > max_chunk:
        raise RangeNotSatisfiable("stream_required")
    handle.seek(start)
    data = handle.read(length)
    if len(data) != length:
        raise GalleryUnavailable("asset_changed_during_read")
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{entry['size_bytes']}"
    return data, status, headers
