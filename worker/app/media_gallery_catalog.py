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

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
# Match canonical UTC timestamps accepted by Android Instant.parse.
_CREATED_AT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z")
_MAX_PAGE = 100
_MAX_INDEX_BYTES = 4 * 1024 * 1024


class GalleryUnavailable(RuntimeError):
    pass


class GalleryBadRequest(ValueError):
    pass


def _root(path: str | Path, *, verified_volume_root: str | Path | None = None) -> Path:
    root = Path(path)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise GalleryUnavailable("external_media_unavailable")
    resolved = root.resolve(strict=True)
    # Reject symlinked parent components as well as a symlink at the root itself.
    if root != resolved:
        raise GalleryUnavailable("media_root_symlink_parent")
    if verified_volume_root is not None:
        volume = Path(verified_volume_root)
        if not volume.is_absolute() or volume.is_symlink() or not volume.is_dir():
            raise GalleryUnavailable("external_media_unavailable")
        mounted = volume.resolve(strict=True)
        if mounted != volume:
            raise GalleryUnavailable("media_root_symlink_parent")
        if not os.path.ismount(mounted):
            raise GalleryUnavailable("external_media_not_mounted")
        if not resolved.is_relative_to(mounted):
            raise GalleryUnavailable("media_root_outside_volume")
    else:
        # Legacy mode remains fail-closed until the writer supplies a verified volume.
        if resolved == Path(resolved.anchor):
            raise GalleryUnavailable("media_root_refused")
        if not os.path.ismount(resolved):
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
        # Producer metadata must not supply transport paths or URLs.  The
        # server derives same-origin URLs only after validation.
        if any(key in item for key in ("url", "thumbnail_url", "path", "file_path")):
            raise GalleryUnavailable("untrusted_media_location")
        media_id = item["id"]
        if not _ID.fullmatch(media_id) or media_id in seen:
            raise GalleryUnavailable("invalid_index_id")
        seen.add(media_id)
        if item.get("kind") not in ("image", "video"):
            raise GalleryUnavailable("invalid_index_kind")
        if not isinstance(item.get("mime_type"), str) or item["mime_type"] not in (
            "image/jpeg", "image/png", "image/webp", "video/mp4"
        ):
            raise GalleryUnavailable("invalid_media_type")
        if (item["kind"] == "video") != (item["mime_type"] == "video/mp4"):
            raise GalleryUnavailable("media_kind_mismatch")
        if type(item.get("size_bytes")) is not int or item["size_bytes"] < 0:
            raise GalleryUnavailable("invalid_media_size")
        # Catalog entries must match the Android kaliv-media-gallery/v1 schema.
        # Never trust producer-supplied URL/path values.
        from datetime import datetime, timezone
        created = item.get("created_at")
        if not isinstance(created, str) or not _CREATED_AT.fullmatch(created):
            raise GalleryUnavailable("invalid_created_at")
        try:
            parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if parsed.tzinfo != timezone.utc:
                raise ValueError("non-UTC")
        except ValueError as exc:
            raise GalleryUnavailable("invalid_created_at") from exc
        for dim in ("width", "height"):
            value = item.get(dim)
            if value is not None and (type(value) is not int or not 0 <= value <= 2147483647):
                raise GalleryUnavailable("invalid_dimensions")
        duration = item.get("duration_seconds")
        if duration is not None:
            import math
            if item["kind"] == "image" or type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                raise GalleryUnavailable("invalid_duration")
        projection = item.get("projection", "flat")
        stereo = item.get("stereo", "mono")
        if projection not in ("flat", "equirectangular_180", "equirectangular_360") or stereo not in ("mono", "left_right", "top_bottom"):
            raise GalleryUnavailable("invalid_layout")
        thumb = item.get("thumbnail_id")
        if thumb is not None and (not isinstance(thumb, str) or not _ID.fullmatch(thumb)):
            raise GalleryUnavailable("invalid_thumbnail")
        range_supported = item.get("supports_range", item["kind"] == "video")
        if type(range_supported) is not bool:
            raise GalleryUnavailable("invalid_range")
        item = {
            "id": media_id, "kind": item["kind"], "mime_type": item["mime_type"],
            "created_at": created, "size_bytes": item["size_bytes"],
            "width": item.get("width"), "height": item.get("height"),
            "duration_seconds": duration, "projection": projection, "stereo": stereo,
            "thumbnail_id": thumb, "thumbnail_url": f"/api/v1/media/{thumb}" if thumb else None,
            "url": f"/api/v1/media/{media_id}",
            "playback": {"supports_range": range_supported},
        }
        validated.append(item)
    return validated


def list_gallery(root_path: str | Path, *, limit: int = 30, cursor: str | None = None,
                 verified_volume_root: str | Path | None = None) -> dict:
    """Read a bounded page from a trusted producer-written index.

    Cursor is an exact asset ID, not a path or a numeric offset.
    """
    if type(limit) is not int or not 1 <= limit <= _MAX_PAGE:
        raise GalleryBadRequest("invalid_limit")
    if cursor is not None and (not isinstance(cursor, str) or not _ID.fullmatch(cursor)):
        raise GalleryBadRequest("invalid_cursor")
    items = _index(_root(root_path, verified_volume_root=verified_volume_root))
    start = 0
    if cursor is not None:
        positions = [i for i, item in enumerate(items) if item["id"] == cursor]
        if not positions:
            raise GalleryBadRequest("unknown_cursor")
        start = positions[0] + 1
    page = items[start:start + limit]
    next_cursor = page[-1]["id"] if start + limit < len(items) and page else None
    return {"schema": "kaliv-media-gallery/v1", "items": page, "next_cursor": next_cursor}
