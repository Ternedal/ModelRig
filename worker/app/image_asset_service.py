"""Owner-scoped image job query service, independent of HTTP authentication.

Only a trusted backend may supply the owner identifier. Never accept an
unverified owner string from a public request as proof of identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .image_job_store import ImageJobStore
from .image_media_store import ExternalMediaStore, MediaStorageError


class ImageAssetNotFound(LookupError):
    pass


@dataclass(frozen=True)
class ImageAsset:
    asset_id: str
    path: Path
    media_type: str


_MEDIA_TYPES = {".png": "image/png", ".webp": "image/webp",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class ImageAssetService:
    def __init__(self, jobs: ImageJobStore, media: ExternalMediaStore):
        self.jobs = jobs
        self.media = media

    def get_job(self, job_id: str, owner: str) -> dict | None:
        job = self.jobs.get(job_id, owner)
        if job is None:
            return None
        # Never expose prompts or local file paths through the client DTO.
        return {"job_id": job["id"], "status": job["state"],
                "asset_id": job["asset_id"] if job["state"] == "completed" else None,
                "error": job["error"] if job["state"] == "failed" else None}

    def get_asset(self, asset_id: str, owner: str) -> ImageAsset:
        # The ownership relationship is derived from a completed job; callers
        # cannot retrieve an asset just by guessing its identifier.
        with self.jobs._db() as db:
            row = db.execute(
                "SELECT id FROM image_jobs WHERE asset_id=? AND owner=? AND state='completed' LIMIT 1",
                (asset_id, owner),
            ).fetchone()
        if row is None:
            raise ImageAssetNotFound("asset not found")
        for extension, media_type in _MEDIA_TYPES.items():
            try:
                path = self.media.resolve(asset_id, extension)
            except MediaStorageError:
                continue
            return ImageAsset(asset_id, path, media_type)
        raise ImageAssetNotFound("asset not found")
