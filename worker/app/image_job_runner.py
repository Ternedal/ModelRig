"""Pluggable image job executor.

No model weights are downloaded and no inference is activated on import.
The backend must supply a vetted renderer and authenticated job owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .image_job_store import ImageJobStore
from .image_media_store import ExternalMediaStore, MediaStorageError


@dataclass(frozen=True)
class RenderedImage:
    data: bytes
    extension: str = ".png"


ImageRenderer = Callable[[str], RenderedImage]


class ImageJobRunner:
    def __init__(self, jobs: ImageJobStore, media: ExternalMediaStore, renderer: ImageRenderer):
        self.jobs = jobs
        self.media = media
        self.renderer = renderer

    def run_one(self) -> dict | None:
        job = self.jobs.claim()
        if job is None:
            return None
        job_id = job["id"]
        try:
            rendered = self.renderer(job["prompt"])
            if not isinstance(rendered, RenderedImage):
                raise TypeError("renderer must return RenderedImage")
            published = self.media.publish(rendered.data, rendered.extension)
            if not self.jobs.finish(job_id, asset_id=str(published["asset_id"])):
                # This should not happen without an external writer modifying job state.
                # Keep the published asset for reconciliation rather than silently
                # returning success; garbage collection is a separate concern.
                raise RuntimeError("job completion transition rejected")
            return {"job_id": job_id, "state": "completed", "asset_id": published["asset_id"]}
        except MediaStorageError:
            # A disappeared external disk is a fatal safety event. Do not
            # touch SQLite or attempt to create a fallback on the system disk.
            raise
        except Exception:
            # Do not persist model exceptions containing prompts or local paths.
            # If the volume vanished during inference, the guarded database
            # connection will raise and terminate the executor.
            self.jobs.finish(job_id, error="image_generation_failed")
            return {"job_id": job_id, "state": "failed", "error": "image_generation_failed"}
