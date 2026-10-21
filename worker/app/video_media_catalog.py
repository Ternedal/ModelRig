"""SQLite catalog for app-visible media on the configured external volume.

This is a repository layer, not an HTTP route. Authenticated application APIs
must enforce ownership/authorization before exposing records or bytes.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from .video_media_contract import MediaItem
from .video_storage_config import configured_video_storage

_ALLOWED_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
}
_KIND_DIRS = {"image": "Images", "video": "Videos"}


def _validated_metadata(raw: str, media_id: str, kind: str) -> dict:
    """Reject corrupt records and return only contract-defined client fields."""
    try:
        metadata = json.loads(raw)
        if not isinstance(metadata, dict) or metadata.get("id") != media_id or metadata.get("kind") != kind:
            raise ValueError("Catalog metadata identity mismatch")
        item = MediaItem(
            media_id=metadata["id"],
            kind=metadata["kind"],
            projection=metadata["projection"],
            stereo=metadata["stereo"],
            mime_type=metadata["mime_type"],
            duration_seconds=metadata["duration_seconds"],
            thumbnail_id=metadata["thumbnail_id"],
        )
        canonical = item.public_metadata()
        if metadata.get("playback") != canonical["playback"]:
            raise ValueError("Invalid catalog playback metadata")
        return canonical
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid catalog media metadata") from exc


class MediaCatalog:
    def __init__(self, root: Path):
        self.root = Path(root).resolve(strict=True)
        self.media_root = self.root / "Media"
        self.db_path = self.root / "Jobs" / "media_catalog.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS media_items ("
                "media_id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                "relative_path TEXT NOT NULL UNIQUE, metadata_json TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )

    @classmethod
    def on_external_volume(cls) -> "MediaCatalog":
        storage = configured_video_storage()
        storage.initialize_directories()
        return cls(storage.root)

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def register(self, item: MediaItem, file_path: Path) -> None:
        """Register an existing file under the approved media root only."""
        if not isinstance(item, MediaItem):
            raise TypeError("Validated media metadata required")
        source = Path(file_path)
        if source.is_symlink() or not source.is_file():
            raise ValueError("Media must be a regular non-symlink file")
        resolved = source.resolve(strict=True)
        directory = self.media_root / _KIND_DIRS[item.kind]
        if not resolved.is_relative_to(directory.resolve(strict=True)):
            raise ValueError("Media file is outside approved kind directory")
        if resolved.suffix.lower() != _ALLOWED_EXTENSIONS[item.mime_type]:
            raise ValueError("Media extension does not match MIME type")
        relative = resolved.relative_to(self.root).as_posix()
        with self._connect() as db:
            db.execute(
                "INSERT INTO media_items(media_id,kind,relative_path,metadata_json) "
                "VALUES(?,?,?,?)",
                (item.media_id, item.kind, relative, json.dumps(item.public_metadata())),
            )

    def list_items(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid limit")
        if type(offset) is not int or offset < 0:
            raise ValueError("Invalid offset")
        with self._connect() as db:
            rows = db.execute(
                "SELECT media_id,kind,metadata_json FROM media_items "
                "ORDER BY created_at DESC, media_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        items = []
        for row in rows:
            items.append(_validated_metadata(row["metadata_json"], row["media_id"], row["kind"]))
        return items

    def resolve(self, media_id: str) -> tuple[Path, dict] | None:
        if not isinstance(media_id, str) or not 1 <= len(media_id) <= 128 or not media_id.isascii() or not all(
            c.isalnum() or c in "-_" for c in media_id
        ):
            raise ValueError("Invalid media ID")
        with self._connect() as db:
            row = db.execute(
                "SELECT relative_path,kind,metadata_json FROM media_items WHERE media_id=?",
                (media_id,),
            ).fetchone()
        if row is None:
            return None
        relative = Path(row["relative_path"])
        if relative.is_absolute() or ".." in relative.parts or relative.drive:
            raise ValueError("Invalid catalog media path")
        candidate = self.root / relative
        if candidate.is_symlink() or not candidate.is_file():
            return None
        resolved = candidate.resolve(strict=True)
        if row["kind"] not in _KIND_DIRS:
            raise ValueError("Invalid catalog media kind")
        directory = (self.media_root / _KIND_DIRS[row["kind"]]).resolve(strict=True)
        if not resolved.is_relative_to(directory):
            raise ValueError("Catalog entry escaped approved media directory")
        metadata = _validated_metadata(row["metadata_json"], media_id, row["kind"])
        if resolved.suffix.lower() != _ALLOWED_EXTENSIONS[metadata["mime_type"]]:
            raise ValueError("Catalog MIME type does not match file extension")
        return resolved, metadata
