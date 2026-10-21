"""Internal image API router for the loopback-only worker.

This router must only be mounted behind the worker's existing loopback guard.
It is NOT a public authenticated API: the trusted backend must authenticate
clients and supply a verified owner identity before proxying these routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .image_job_store import ImageJobStore, ImageJobError
from .image_asset_service import ImageAssetService, ImageAssetNotFound
from .image_media_store import ExternalMediaStore

router = APIRouter(prefix="/internal/media/images", tags=["internal-images"])

# Initialized explicitly by a trusted worker bootstrap; no default media path.
_jobs: ImageJobStore | None = None
_assets: ImageAssetService | None = None


def configure_image_routes(jobs: ImageJobStore, media: ExternalMediaStore) -> None:
    global _jobs, _assets
    _jobs = jobs
    _assets = ImageAssetService(jobs, media)


def _ready() -> tuple[ImageJobStore, ImageAssetService]:
    if _jobs is None or _assets is None:
        raise HTTPException(status_code=503, detail="image generation disabled")
    return _jobs, _assets


def _owner(verified_owner: str | None) -> str:
    # Header values are only trustworthy across the backend->loopback boundary.
    if not verified_owner or not verified_owner.strip() or len(verified_owner) > 256:
        raise HTTPException(status_code=401, detail="verified owner required")
    return verified_owner


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


@router.post("/jobs", status_code=202)
def create_image_job(body: ImageRequest, x_verified_owner: str | None = Header(default=None)):
    jobs, _ = _ready()
    try:
        return jobs.submit(_owner(x_verified_owner), body.prompt)
    except ImageJobError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
def get_image_job(job_id: str, x_verified_owner: str | None = Header(default=None)):
    _, assets = _ready()
    job = assets.get_job(job_id, _owner(x_verified_owner))
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_image_job(job_id: str, x_verified_owner: str | None = Header(default=None)):
    jobs, _ = _ready()
    if not jobs.cancel(job_id, _owner(x_verified_owner)):
        raise HTTPException(status_code=409, detail="job cannot be cancelled")
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/assets/{asset_id}")
def get_image_asset(asset_id: str, x_verified_owner: str | None = Header(default=None)):
    from fastapi.responses import FileResponse
    _, assets = _ready()
    try:
        asset = assets.get_asset(asset_id, _owner(x_verified_owner))
    except ImageAssetNotFound as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    return FileResponse(asset.path, media_type=asset.media_type,
                        headers={"Cache-Control": "private, no-store",
                                 "X-Content-Type-Options": "nosniff"})
