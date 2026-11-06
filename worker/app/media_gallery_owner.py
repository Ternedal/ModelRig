"""Owner-scoped gallery projection. No HTTP or authentication is implemented here.

Callers MUST supply an authenticated owner, never an owner from query parameters.
The completed-job authority is checked before any metadata is returned.
"""
from __future__ import annotations

from pathlib import Path

from .media_gallery_catalog import (
    GalleryBadRequest, _ID, _MAX_PAGE, _index, _root,
)


def list_owned_gallery(jobs, authenticated_owner: str, root_path: str | Path, *,
                       limit: int = 30, cursor: str | None = None,
                       verified_volume_root: str | Path | None = None) -> dict:
    """Page *authorized* assets, never page the raw index before filtering.

    A cursor for an asset not owned by the principal is indistinguishable from
    an unknown cursor. No prompt, job owner or unfinished asset is projected.
    """
    if not isinstance(authenticated_owner, str) or not authenticated_owner:
        raise GalleryBadRequest("missing_authenticated_owner")
    if type(limit) is not int or not 1 <= limit <= _MAX_PAGE:
        raise GalleryBadRequest("invalid_limit")
    if cursor is not None and (not isinstance(cursor, str) or not _ID.fullmatch(cursor)):
        raise GalleryBadRequest("invalid_cursor")

    # Verify volume and parse the bounded index before exposing metadata.
    entries = _index(_root(root_path, verified_volume_root=verified_volume_root))
    owned = [entry for entry in entries
             if jobs.owns_completed_asset(authenticated_owner, entry["id"])]
    start = 0
    if cursor is not None:
        for i, entry in enumerate(owned):
            if entry["id"] == cursor:
                start = i + 1
                break
        else:
            raise GalleryBadRequest("unknown_cursor")
    page = owned[start:start + limit]
    next_cursor = page[-1]["id"] if start + limit < len(owned) and page else None
    return {"schema": "kaliv-media-gallery/v1", "items": page, "next_cursor": next_cursor}
