"""Read-only, fail-closed gallery catalog for an external media volume.

This module deliberately does not mount disks or expose an unauthenticated HTTP
route. A server adapter must enforce pairing authorization before calling it.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\\Z")
_MAX_PAGE = 100
_MAX_INDEX_BYTES = 4 * 1024 * 1024


class GalleryUnavailable(RuntimeError):
    pass


class GalleryBadRequest(ValueError):
    pass


def _root(path: str | Path) -> Path:
    root = Path(path)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise GalleryUnavailable("external_media_unavailable")
    resolved = root.resolve(strict=True)
    if resolved == Path(resolved.anchor):
        raise GalleryUnavailable("media_root_refused")
    if os.name != "nt" and not os.path.ismount(resolved):
        raise GalleryUnavailable("external_media_not_mounted")
    return resolved


def _index(root: Path) -> list[dict]:
    index = root / "gallery-index.json"
    try:
        if index.is_symlink():
            raise GalleryUnavailable("index_symlink_refused")
        descriptor = os.open(index, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_INDEX_BYTES:
                raise GalleryUnavailable("invalid_index")
            with os.fdopen(descriptor, "rb", closefd=False) as f:
                payload = f.read(_MAX_INDEX_BYTES + 1)
            if len(payload) > _MAX_INDEX_BYTES:
                raise GalleryUnavailable("index_too_large")
        finally:
            os.close(descriptor)
        items = json.loads(payload)
    except (OSError, ValueError, TypeError) as exc:
        raise GalleryUnavailable("invalid_index") from exc
    if not isinstance(items, list):
        raise GalleryUnavailable("invalid_index")
    validated = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise GalleryUnavailable("invalid_index_item")
        media_id = item["id"]
        if not _ID.fullmatch(media_id) or media_id in seen:
            raise GalleryUnavailable("invalid_index_id")
        seen.add(media_id)
        if item.get("kind") not in ("image", "video"):
            raise GalleryUnavailable("invalid_index_kind")
        validated.append(item)
    return validated


def list_gallery(root_path: str | Path, *, limit: int = 30, cursor: str | None = None) -> dict:
    """Read a bounded page from a trusted producer-written index.

    Cursor is an exact asset ID, not a path or a numeric offset.
    """
    if type(limit) is not int or not 1 <= limit <= _MAX_PAGE:
        raise GalleryBadRequest("invalid_limit")
    if cursor is not None and (not isinstance(cursor, str) or not _ID.fullmatch(cursor)):
        raise GalleryBadRequest("invalid_cursor")
    items = _index(_root(root_path))
    start = 0
    if cursor is not None:
        positions = [i for i, item in enumerate(items) if item["id"] == cursor]
        if not positions:
            raise GalleryBadRequest("unknown_cursor")
        start = positions[0] + 1
    page = items[start:start + limit]
    next_cursor = page[-1]["id"] if start + limit < len(items) and page else None
    return {"schema": "kaliv-media-gallery/v1", "items": page, "next_cursor": next_cursor}
