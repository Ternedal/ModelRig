"""Opt-in image API router factory; never mounted by import.

The host must provide a trusted authenticated owner dependency. No route may
derive ownership from client-supplied headers, query parameters or JSON.
"""
from __future__ import annotations

from typing import Callable
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, Query
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
    ingested_artifacts: dict[str, str] = {}

    def owner_id(value: object) -> str:
        if (not isinstance(value, str) or not 1 <= len(value) <= 128
                or value != value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
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
        @router.get("/artifacts")
        async def list_image_artifacts(
            limit: int = Query(default=50, ge=1, le=200),
            offset: int = Query(default=0, ge=0, le=10000),
            identity=Depends(authenticated_owner),
        ):
            owner = owner_id(identity)
            try:
                artifact_ids = artifact_store.list_png_ids(owner, limit=limit, offset=offset)
            except (ValueError, RuntimeError, OSError) as exc:
                raise HTTPException(status_code=503, detail="Image storage unavailable") from exc
            return {"artifacts": [
                {"id": artifact_id, "media_type": "image/png"}
                for artifact_id in artifact_ids
            ]}

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
            # Keep the in-process ledger bounded to jobs still retained by the manager.
            for old_id in tuple(ingested_artifacts):
                if old_id not in service.manager._jobs:
                    ingested_artifacts.pop(old_id, None)
                    ingestion_locks.pop(old_id, None)
            if job_id in ingested_artifacts:
                return {"artifact_id": ingested_artifacts[job_id]}
            # Prevent concurrent duplicate ingestion of the same completed job.
            # A durable ingestion ledger is required before multi-process enablement.
            lock = ingestion_locks.setdefault(job_id, asyncio.Lock())
            if lock.locked():
                raise HTTPException(status_code=409, detail="Image ingestion in progress")
            try:
                async with lock:
                    # Recheck after acquiring: another request may have finished
                    # ingestion while this coroutine was waiting for the lock.
                    if job_id in ingested_artifacts:
                        return {"artifact_id": ingested_artifacts[job_id]}
                    try:
                        artifact_id = await ingest_completed_job(
                            owner, job_id, manager=service.manager,
                            adapter=service.adapter, store=artifact_store,
                        )
                    except (RuntimeError, OSError) as exc:
                        raise HTTPException(status_code=503, detail="Image ingestion storage unavailable") from exc
                    except ValueError as exc:
                        raise HTTPException(status_code=422, detail="Image ingestion failed") from exc
                    ingested_artifacts[job_id] = artifact_id
                    return {"artifact_id": artifact_id}
            finally:
                # Keep the lock associated with its retained job. Removing it
                # here allows a third request to create a different lock while
                # an earlier waiter is still blocked on the first one.
                # Prune locks only when their jobs leave the manager.
                pass

        @router.get("/artifacts/{artifact_id}/thumbnail")
        async def get_image_thumbnail(
            artifact_id: str, identity=Depends(authenticated_owner)
        ):
            owner = owner_id(identity)
            try:
                payload = artifact_store.get_thumbnail_png(owner, artifact_id)
            except (RuntimeError, OSError) as exc:
                raise HTTPException(status_code=503, detail="Thumbnail service unavailable") from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Invalid stored image") from exc
            if payload is None:
                raise HTTPException(status_code=404, detail="Image artifact not found")
            return Response(
                content=payload, media_type="image/png",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )

        @router.get("/artifacts/{artifact_id}")
        async def get_image_artifact(
            artifact_id: str, identity=Depends(authenticated_owner)
        ):
            owner = owner_id(identity)
            try:
                payload = artifact_store.get_png(owner, artifact_id)
            except (ValueError, RuntimeError, OSError) as exc:
                raise HTTPException(status_code=503, detail="Image storage unavailable") from exc
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
