"""Pure media catalog contract shared by future Android, Windows and Quest APIs.

No route is mounted here. The authenticated backend must own authorization;
never expose raw filesystem paths or allow a client-provided path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MediaKind = Literal["image", "video"]
Projection = Literal["flat", "equirectangular_180", "equirectangular_360"]
Stereo = Literal["mono", "left_right", "top_bottom"]


@dataclass(frozen=True)
class MediaItem:
    media_id: str
    kind: MediaKind
    projection: Projection = "flat"
    stereo: Stereo = "mono"
    mime_type: str = "video/mp4"
    duration_seconds: float | None = None
    thumbnail_id: str | None = None

    def __post_init__(self) -> None:
        for identifier in (self.media_id, self.thumbnail_id):
            if identifier is not None and (
                not isinstance(identifier, str) or not 1 <= len(identifier) <= 128
                or not identifier.isascii()
                or not all(ch.isalnum() or ch in "-_" for ch in identifier)
            ):
                raise ValueError("Invalid media identifier")
        if self.kind not in ("image", "video"):
            raise ValueError("Invalid media kind")
        if self.projection not in ("flat", "equirectangular_180", "equirectangular_360"):
            raise ValueError("Invalid projection")
        if self.stereo not in ("mono", "left_right", "top_bottom"):
            raise ValueError("Invalid stereo layout")
        if self.kind == "image" and self.mime_type not in ("image/jpeg", "image/png", "image/webp"):
            raise ValueError("Invalid image MIME type")
        if self.kind == "video" and self.mime_type != "video/mp4":
            raise ValueError("Only MP4 playback qualified initially")
        if self.duration_seconds is not None and (
            isinstance(self.duration_seconds, bool) or not isinstance(self.duration_seconds, (int, float))
            or not 0 <= self.duration_seconds <= 86400
        ):
            raise ValueError("Invalid duration")

    def public_metadata(self) -> dict:
        """Client-safe metadata: no paths, mounts or storage credentials."""
        return {
            "id": self.media_id,
            "kind": self.kind,
            "projection": self.projection,
            "stereo": self.stereo,
            "mime_type": self.mime_type,
            "duration_seconds": self.duration_seconds,
            "thumbnail_id": self.thumbnail_id,
            "playback": {"supports_range": self.kind == "video"},
        }
