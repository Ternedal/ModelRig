"""Client-facing gallery projections; URLs remain relative to the trusted API origin.

The calling HTTP handler must authenticate requests before returning entries.
Never expose filesystem paths or a drive letter to clients.
"""
from __future__ import annotations

from urllib.parse import quote


def gallery_item_for_client(item: dict, *, url_prefix: str = "/api/v1/media") -> dict:
    if url_prefix not in ("/api/v1/media", "/experimental/media"):
        raise ValueError("Unsupported media URL prefix")
    media_id = item["id"]
    if not isinstance(media_id, str) or not media_id.isascii() or not 1 <= len(media_id) <= 128 or not all(
        c.isalnum() or c in "_-" for c in media_id
    ):
        raise ValueError("Invalid catalog media identifier")
    result = dict(item)
    result["url"] = url_prefix + "/" + quote(media_id, safe="")
    thumb = item.get("thumbnail_id")
    if thumb is not None:
        if not isinstance(thumb, str) or not thumb.isascii() or not 1 <= len(thumb) <= 128 or not all(
            c.isalnum() or c in "_-" for c in thumb
        ):
            raise ValueError("Invalid thumbnail identifier")
        result["thumbnail_url"] = url_prefix + "/" + quote(thumb, safe="")
    else:
        result["thumbnail_url"] = None
    return result
