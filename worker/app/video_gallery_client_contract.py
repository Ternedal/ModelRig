"""Framework-neutral Kaliv gallery client contract.

The caller owns trusted API origin, TLS, session authorization and playback.
Do not use untrusted absolute URLs returned by a server; only relative paths
from the validated media gallery contract are accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class GalleryAsset:
    media_id: str
    kind: str
    url: str
    thumbnail_url: str | None
    projection: str
    stereo: str

    @classmethod
    def from_api(cls, item: dict) -> "GalleryAsset":
        if not isinstance(item, dict):
            raise ValueError("Invalid gallery item")
        media_id = item.get("id")
        if not isinstance(media_id, str) or not media_id.isascii() or not media_id or not all(
            ch.isalnum() or ch in "-_" for ch in media_id
        ):
            raise ValueError("Invalid media ID")
        kind = item.get("kind")
        if kind not in ("image", "video"):
            raise ValueError("Invalid media kind")
        url = item.get("url")
        expected = "/experimental/media/" + media_id
        if url != expected:
            raise ValueError("Unexpected media URL")
        thumbnail_url = item.get("thumbnail_url")
        if thumbnail_url is not None:
            thumbnail_id = item.get("thumbnail_id")
            if not isinstance(thumbnail_id, str) or not thumbnail_id.isascii() or not thumbnail_id or not all(
                ch.isalnum() or ch in "-_" for ch in thumbnail_id
            ) or thumbnail_url != "/experimental/media/" + thumbnail_id:
                raise ValueError("Unexpected thumbnail URL")
        projection = item.get("projection", "flat")
        stereo = item.get("stereo", "mono")
        if projection not in ("flat", "equirectangular_180", "equirectangular_360"):
            raise ValueError("Unknown projection")
        if stereo not in ("mono", "left_right", "top_bottom"):
            raise ValueError("Unknown stereo")
        return cls(media_id, kind, url, thumbnail_url, projection, stereo)


def validate_api_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("HTTPS API origin required")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("API origin must not contain a path or query")
    return origin.rstrip("/")
