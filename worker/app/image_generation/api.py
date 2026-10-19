"""Opt-in image API router factory; never mounted by import.

The host must provide a trusted authenticated owner dependency. No route may
derive ownership from client-supplied headers, query parameters or JSON.
"""
from __future__ import annotations

from typing import Callable
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .jobs import ImageJobManager
from .service import ImageGenerationService
from .artifacts import ImageArtifactStore
from .ingest import ingest_completed_job
from .jobs import JobStatus


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


def build_image_router(
    service: ImageGenerationService,
    *,
    authenticated_owner: Callable,
    artifact_store: ImageArtifactStore | None = None,
) -> APIRouter:
    """Construct routes only when an operator injects a trusted auth resolver."""
    if not callable(authenticated_owner):
        raise ValueError("An authenticated owner dependency is required")
    router = APIRouter(prefix="/experimental/images", tags=["experimental-images"])
    ingestion_locks: dict[str, asyncio.Lock] = {}

    def owner_id(value: object) -> str:
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise HTTPException(status_code=401, detail="Authentication required")
        return value

    def public_job(job):
        return {
            "id": job.id,
            "status": job.status.value,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "error": job.error,
        }

    @router.post("/jobs", status_code=202)
    async def submit_image(
        request: ImageRequest, identity=Depends(authenticated_owner)
    ):
        owner = owner_id(identity)
        try:
            job = await service.submit(owner, request.prompt, request.seed)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid image request") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Image capacity unavailable") from exc
        return public_job(job)

    @router.get("/jobs/{job_id}")
    async def get_image_job(job_id: str, identity=Depends(authenticated_owner)):
        job = service.manager.get(owner_id(identity), job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Image job not found")
        return public_job(job)

    @router.delete("/jobs/{job_id}", status_code=204)
    async def cancel_image_job(job_id: str, identity=Depends(authenticated_owner)):
        if not await service.manager.cancel(owner_id(identity), job_id):
            raise HTTPException(status_code=404, detail="Image job not found")

    if artifact_store is not None:
        @router.post("/jobs/{job_id}/ingest")
        async def ingest_image_job(
            job_id: str, identity=Depends(authenticated_owner)
        ):
            owner = owner_id(identity)
            job = service.manager.get(owner, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Image job not found")
            if job.status != JobStatus.SUCCEEDED:
                raise HTTPException(status_code=409, detail="Image job is not completed")
            # Prevent concurrent duplicate ingestion of the same completed job.
            # A durable ingestion ledger is required before multi-process enablement.
            lock = ingestion_locks.setdefault(job_id, asyncio.Lock())
            if lock.locked():
                raise HTTPException(status_code=409, detail="Image ingestion in progress")
            try:
                async with lock:
                    try:
                        artifact_id = await ingest_completed_job(
                            owner, job_id, manager=service.manager,
                            adapter=service.adapter, store=artifact_store,
                        )
                    except (ValueError, RuntimeError) as exc:
                        raise HTTPException(status_code=422, detail="Image ingestion failed") from exc
                    return {"artifact_id": artifact_id}
            finally:
                # Do not retain a lock for every historical job indefinitely.
                # A simultaneous caller observes the held lock and gets 409.
                if ingestion_locks.get(job_id) is lock:
                    ingestion_locks.pop(job_id, None)

        @router.get("/artifacts/{artifact_id}")
        async def get_image_artifact(
            artifact_id: str, identity=Depends(authenticated_owner)
        ):
            owner = owner_id(identity)
            payload = artifact_store.get_png(owner, artifact_id)
            if payload is None:
                raise HTTPException(status_code=404, detail="Image artifact not found")
            return Response(
                content=payload,
                media_type="image/png",
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Content-Disposition": 'attachment; filename="generated.png"',
                },
            )

    return router
