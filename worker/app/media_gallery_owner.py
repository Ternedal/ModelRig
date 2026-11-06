"""Owner-scoped gallery projection. No HTTP or authentication is implemented here.

Callers MUST supply an authenticated owner, never an owner from query parameters.
The completed-job authority is checked before any metadata is returned.
"""
from __future__ import annotations

from pathlib import Path

from .media_gallery_catalog import (
    GalleryBadRequest, GalleryUnavailable, _ID, _MAX_PAGE, _index, _root,
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

    if verified_volume_root is None:
        raise GalleryUnavailable("verified_volume_required")
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
    # A thumbnail can point at a separate indexed asset. Never disclose its ID
    # or URL unless that referenced asset is independently completed for owner.
    # Avoid modifying the catalog's cached/index objects in place.
    page = []
    for entry in owned[start:start + limit]:
        safe = dict(entry)
        thumb = safe.get("thumbnail_id")
        if thumb is not None and not jobs.owns_completed_asset(authenticated_owner, thumb):
            safe["thumbnail_id"] = None
            safe["thumbnail_url"] = None
        page.append(safe)
    next_cursor = page[-1]["id"] if start + limit < len(owned) and page else None
    return {"schema": "kaliv-media-gallery/v1", "items": page, "next_cursor": next_cursor}


def open_owned_asset(jobs, authenticated_owner: str, root_path: str | Path,
                     verified_volume_root: str | Path, asset_id: str):
    """Open an asset only after completed-job ownership is established.

    Return the same (handle, entry) contract as open_asset. Unknown, invalid,
    incomplete and foreign assets all return the same not-found exception.
    The caller owns the handle and must close it.
    """
    from .media_gallery_asset import GalleryAssetNotFound, open_asset
    if (not isinstance(authenticated_owner, str) or not authenticated_owner
            or not isinstance(asset_id, str) or not _ID.fullmatch(asset_id)):
        raise GalleryAssetNotFound("unknown_asset")
    if not jobs.owns_completed_asset(authenticated_owner, asset_id):
        raise GalleryAssetNotFound("unknown_asset")
    return open_asset(root_path, verified_volume_root, asset_id)
