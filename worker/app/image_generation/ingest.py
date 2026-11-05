"""Owner-authorized ingestion of completed ComfyUI image jobs.

This remains a separately invoked service, not a public API endpoint.
"""
from __future__ import annotations

from .artifacts import ImageArtifactStore
from .comfyui_adapter import ComfyUIAdapter, ComfyUIError
from .jobs import ImageJobManager, JobStatus
from .outputs import select_output_image
from .sanitize import sanitize_to_png


async def ingest_completed_job(
    owner_id: str,
    job_id: str,
    *,
    manager: ImageJobManager,
    adapter: ComfyUIAdapter,
    store: ImageArtifactStore,
) -> str:
    job = manager.get(owner_id, job_id)
    if job is None or job.status != JobStatus.SUCCEEDED or not job.result:
        raise ValueError("Completed image job not found")
    history = await adapter.history(job.result)
    entry = history.get(job.result)
    if not isinstance(entry, dict):
        raise ComfyUIError("Image history unavailable")
    status = entry.get("status")
    if isinstance(status, dict) and status.get("status_str") in {
        "error", "failed", "cancelled", "interrupted"
    }:
        raise ComfyUIError("Image job failed before ingestion")
    descriptor = select_output_image(entry.get("outputs"))
    source = await adapter.fetch_output(descriptor)
    clean_png = sanitize_to_png(source, max_input_bytes=store.max_bytes)
    return store.put_png(owner_id, clean_png)
