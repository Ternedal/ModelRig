"""Internal image API router for trusted backend-to-worker requests only.

This router is disabled unless configured and is not mounted on the running
worker. An owner header alone is NOT authentication. Require a separate
high-entropy shared secret before processing any request.
"""
from __future__ import annotations

import hmac
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .image_job_store import ImageJobStore, ImageJobError
from .image_asset_service import ImageAssetService, ImageAssetNotFound
from .image_media_store import ExternalMediaStore

router = APIRouter(prefix="/internal/media/images", tags=["internal-images"])
_jobs: ImageJobStore | None = None
_assets: ImageAssetService | None = None
_internal_secret: str | None = None


def configure_image_routes(jobs: ImageJobStore, media: ExternalMediaStore,
                           *, internal_secret: str) -> None:
    if not isinstance(internal_secret, str) or len(internal_secret) < 32:
        raise ValueError("internal media secret must be at least 32 characters")
    global _jobs, _assets, _internal_secret
    _jobs = jobs
    _assets = ImageAssetService(jobs, media)
    _internal_secret = internal_secret


def _ready() -> tuple[ImageJobStore, ImageAssetService]:
    if _jobs is None or _assets is None or _internal_secret is None:
        raise HTTPException(status_code=503, detail="image generation disabled")
    return _jobs, _assets


def _owner(verified_owner: str | None, supplied_secret: str | None) -> str:
    if _internal_secret is None or supplied_secret is None or not hmac.compare_digest(
            supplied_secret, _internal_secret):
        raise HTTPException(status_code=401, detail="internal authentication required")
    if not verified_owner or not verified_owner.strip() or len(verified_owner) > 256:
        raise HTTPException(status_code=401, detail="verified owner required")
    return verified_owner


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


@router.post("/jobs", status_code=202)
def create_image_job(body: ImageRequest, x_verified_owner: str | None = Header(default=None),
                     x_internal_media_secret: str | None = Header(default=None)):
    jobs, _ = _ready()
    owner = _owner(x_verified_owner, x_internal_media_secret)
    try:
        return jobs.submit(owner, body.prompt)
    except ImageJobError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
def get_image_job(job_id: str, x_verified_owner: str | None = Header(default=None),
                  x_internal_media_secret: str | None = Header(default=None)):
    _, assets = _ready()
    job = assets.get_job(job_id, _owner(x_verified_owner, x_internal_media_secret))
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_image_job(job_id: str, x_verified_owner: str | None = Header(default=None),
                     x_internal_media_secret: str | None = Header(default=None)):
    jobs, _ = _ready()
    if not jobs.cancel(job_id, _owner(x_verified_owner, x_internal_media_secret)):
        raise HTTPException(status_code=409, detail="job cannot be cancelled")
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/assets/{asset_id}")
def get_image_asset(asset_id: str, x_verified_owner: str | None = Header(default=None),
                    x_internal_media_secret: str | None = Header(default=None)):
    from fastapi.responses import FileResponse
    _, assets = _ready()
    try:
        asset = assets.get_asset(asset_id, _owner(x_verified_owner, x_internal_media_secret))
    except ImageAssetNotFound as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    return FileResponse(asset.path, media_type=asset.media_type,
                        headers={"Cache-Control": "private, no-store",
                                 "X-Content-Type-Options": "nosniff"})
