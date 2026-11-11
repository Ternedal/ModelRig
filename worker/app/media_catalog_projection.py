"""Fail-closed ownership projection for a verified media publication catalog.

This module never opens a path. A separate G1-verified catalog is responsible for
descriptor validation and for returning already-open file handles.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping

_ASSET_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_MAX_ASSETS = 4096


class MediaCatalogProjectionError(ValueError):
    """Invalid catalog metadata or unavailable ownership authority."""


def owned_completed_media(
    owner: str,
    completed_assets_for: Callable[[str], frozenset[str]],
    verified_entries: Callable[[], Iterable[Mapping[str, object]]],
    *,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Return only verified entries owned by completed jobs, never paths.

    Both inputs must be trusted server-side collaborators. Any malformed entry,
    duplicate id or authority error fails the entire read, rather than returning
    a partial or misleading catalog. No request-supplied owner is accepted.
    """
    if type(owner) is not str or not owner.strip() or len(owner) > 256:
        raise MediaCatalogProjectionError("invalid owner")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise MediaCatalogProjectionError("invalid limit")
    try:
        owned = completed_assets_for(owner)
        if type(owned) is not frozenset or len(owned) > _MAX_ASSETS:
            raise MediaCatalogProjectionError("invalid ownership authority")
        if any(type(x) is not str or not _ASSET_ID.fullmatch(x) for x in owned):
            raise MediaCatalogProjectionError("invalid owned asset")
        result: list[dict[str, object]] = []
        seen: set[str] = set()
        count = 0
        for entry in verified_entries():
            count += 1
            if count > _MAX_ASSETS:
                raise MediaCatalogProjectionError("catalog too large")
            if not isinstance(entry, Mapping):
                raise MediaCatalogProjectionError("invalid catalog entry")
            asset_id = entry.get("asset_id")
            mime = entry.get("mime")
            size = entry.get("size")
            if (type(asset_id) is not str or not _ASSET_ID.fullmatch(asset_id)
                    or type(mime) is not str
                    or mime not in ("image/png", "image/jpeg", "image/webp", "video/mp4")
                    or type(size) is not int or size < 0
                    or asset_id in seen):
                raise MediaCatalogProjectionError("invalid catalog entry")
            seen.add(asset_id)
            if asset_id in owned and len(result) < limit:
                result.append({"asset_id": asset_id, "mime": mime, "size": size})
        return result
    except MediaCatalogProjectionError:
        raise
    except Exception as exc:
        raise MediaCatalogProjectionError("media catalog unavailable") from exc
