"""Explicit, synchronous ComfyUI media job coordinator.

This is an opt-in library, not a background worker or API endpoint.
The caller must authenticate requests and provide a trusted workflow.
"""
from __future__ import annotations

from pathlib import Path

from worker.app.comfy_transport import ComfyTransport
from worker.app.comfy_history import poll_history
from worker.app.comfy_media_import import import_comfy_output
from worker.app.media_jobs import MediaJobQueue, MediaJobError, MediaJobState


class MediaCoordinator:
    def __init__(self, queue: MediaJobQueue, transport: ComfyTransport, media_root: Path):
        self.queue = queue
        self.transport = transport
        self.media_root = media_root
        self._prompts: dict[str, str] = {}

    def submit(self, kind: str, workflow: dict) -> str:
        job = self.queue.submit(kind)
        try:
            self.queue.start(job.id)
            prompt_id = self.transport.submit_prompt(workflow, job.id)
            self._prompts[job.id] = prompt_id
        except Exception:
            self.queue.fail(job.id, "generation_failed")
            raise
        return job.id

    def poll(self, job_id: str):
        job = self.queue.get(job_id)
        if job is None:
            raise MediaJobError("Unknown job")
        if job.state != MediaJobState.RUNNING:
            return job
        prompt_id = self._prompts.get(job_id)
        if not prompt_id:
            self.queue.fail(job_id, "generation_failed")
            raise MediaJobError("Missing prompt mapping")
        try:
            status = poll_history(self.transport, prompt_id)
            if status["state"] == "pending":
                return job
            if status["state"] == "failed":
                return self.queue.fail(job_id, "generation_failed")
            # Single-output admission until a multi-asset atomic manifest exists.
            filenames = status["filenames"]
            if len(filenames) != 1:
                raise MediaJobError("Expected exactly one output")
            source = filenames[0]
            suffix = Path(source).suffix.lower()
            allowed = {".png", ".jpg", ".jpeg", ".webp"} if job.kind == "image" else {".mp4", ".webm"}
            if suffix not in allowed:
                raise MediaJobError("Unexpected output format")
            destination = f"{job.id}{suffix}"
            import_comfy_output(self.transport, source, self.media_root, destination)
            return self.queue.complete(job_id, destination)
        except Exception:
            self.queue.fail(job_id, "generation_failed")
            raise
