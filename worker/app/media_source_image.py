"""Fail-closed, read-only source image access for future image-to-video integration.

No route, model invocation, media copy, or activation. Consumers receive bytes,
never a filesystem path. The gallery catalog is not an authorization decision:
the caller must authorize the asset owner before invoking this function.
"""
from __future__ import annotations

import os
import stat

from .media_gallery_catalog import GalleryUnavailable, _ID, _index
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import ArtifactSinkUnavailable
from .media_source_png_validation import InvalidSourcePng, validate_png_container

MAX_SOURCE_IMAGE_BYTES = 32 * 1024 * 1024


def read_source_png(sink: ExternalMediaSink, asset_id: str) -> bytes:
    """Read one indexed PNG from the verified external volume, without following links.

    Caller is responsible for pairing and per-owner authorization. No public
    endpoint must call this helper with an untrusted asset ID alone.
    """
    if type(asset_id) is not str or not _ID.fullmatch(asset_id):
        raise ValueError("invalid_asset_id")
    root = sink._root()
    try:
        matches = [entry for entry in _index(root) if entry["id"] == asset_id]
    except GalleryUnavailable as exc:
        raise ArtifactSinkUnavailable("source_index_unavailable") from exc
    if len(matches) != 1 or matches[0]["kind"] != "image" or matches[0]["mime_type"] != "image/png":
        raise ArtifactSinkUnavailable("source_image_not_indexed_png")
    expected = matches[0]["size_bytes"]
    if not 0 < expected <= MAX_SOURCE_IMAGE_BYTES:
        raise ArtifactSinkUnavailable("source_image_size_refused")
    path = root / (asset_id + ".png")
    try:
        path_before = os.lstat(path)
    except OSError as exc:
        raise ArtifactSinkUnavailable("source_image_unavailable") from exc
    if not stat.S_ISREG(path_before.st_mode):
        raise ArtifactSinkUnavailable("source_image_not_regular")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ArtifactSinkUnavailable("source_image_unavailable") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_size != expected
                or before.st_dev != path_before.st_dev or before.st_ino != path_before.st_ino):
            raise ArtifactSinkUnavailable("source_image_identity_mismatch")
        payload = bytearray()
        while len(payload) <= expected:
            chunk = os.read(fd, min(1024 * 1024, expected + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(fd)
        if (len(payload) != expected or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            raise ArtifactSinkUnavailable("source_image_changed")
        sink._root()
        try:
            path_after = os.lstat(path)
        except OSError as exc:
            raise ArtifactSinkUnavailable("source_image_changed") from exc
        if (not stat.S_ISREG(path_after.st_mode) or path_after.st_dev != before.st_dev
                or path_after.st_ino != before.st_ino):
            raise ArtifactSinkUnavailable("source_image_changed")
        try:
            validate_png_container(bytes(payload))
        except InvalidSourcePng as exc:
            raise ArtifactSinkUnavailable("source_image_invalid_png") from exc
        return bytes(payload)
    except OSError as exc:
        raise ArtifactSinkUnavailable("source_image_read_failed") from exc
    finally:
        os.close(fd)
