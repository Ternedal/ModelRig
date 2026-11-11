"""Ownership-gated facade over the existing gallery v1 catalog and asset opener.

No HTTP route is registered here. The caller must authenticate the installation
and supply the G1 descriptor verifier; this module must not be used as a raw
filesystem-based authorization boundary.
"""
from __future__ import annotations

from .media_catalog_projection import owned_completed_media, open_owned_completed_media
from .media_gallery_catalog import _index, _root
from .media_gallery_asset import open_asset


def list_owned_gallery(owner, job_store, media_root, verified_volume_root, volume, *, limit=30):
    """Filter validated gallery-index v1 entries against completed job ownership."""
    volume.verify()
    result = owned_completed_media(
        owner, job_store.completed_assets_for,
        lambda: _index(_root(media_root, verified_volume_root=verified_volume_root)),
        limit=limit,
    )
    volume.verify()
    return result


def open_owned_gallery_asset(owner, asset_id, job_store, media_root,
                             verified_volume_root, volume, verify_descriptor):
    """Return an owned descriptor, MIME and length, never a path.

    verify_descriptor(handle, asset_id) must check the exact open descriptor
    against the pinned G1 volume identity; the existing gallery opener alone
    does not prove descriptor-to-volume identity.
    """
    def verified_open(identifier):
        handle, entry = open_asset(media_root, verified_volume_root, identifier)
        return handle, entry["mime_type"], entry["size_bytes"]

    return open_owned_completed_media(
        owner, asset_id, job_store.owns_completed_asset,
        verified_open, volume.verify, verify_descriptor,
    )
