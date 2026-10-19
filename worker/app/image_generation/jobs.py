"""Bounded in-process image job state machine.

This is an opt-in building block, not a production route or persistent queue.
Jobs never run on import. The caller owns authentication, workflow selection,
artifact retrieval and startup/shutdown.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ImageJob:
    id: str
    owner_id: str
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    result: str | None = None
    error: str | None = None


class ImageJobManager:
    """Single-worker, owner-scoped jobs with cancellation and bounded admission."""

    def __init__(self, *, max_jobs: int = 32, timeout_seconds: float = 600):
        if not 1 <= max_jobs <= 1000:
            raise ValueError("Invalid job capacity")
        if not 0 < timeout_seconds <= 3600:
            raise ValueError("Invalid job timeout")
        self.max_jobs = max_jobs
        self.timeout_seconds = timeout_seconds
        self._jobs: dict[str, ImageJob] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._worker = asyncio.Semaphore(1)

    async def submit(
        self, owner_id: str, run: Callable[[], Awaitable[str]]
    ) -> ImageJob:
        if not owner_id or len(owner_id) > 128:
            raise ValueError("Invalid owner")
        async with self._lock:
            if len(self._jobs) >= self.max_jobs:
                # Reclaim the oldest completed record only. Running/queued
                # jobs are never evicted, and all eviction is under the lock.
                finished = [
                    job for job in self._jobs.values()
                    if job.status in (
                        JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED
                    ) and job.id not in self._tasks
                ]
                if not finished:
                    raise RuntimeError("Image job capacity reached")
                oldest = min(finished, key=lambda job: job.created_at)
                self._jobs.pop(oldest.id, None)
            job = ImageJob(id=str(uuid.uuid4()), owner_id=owner_id)
            self._jobs[job.id] = job
            self._tasks[job.id] = asyncio.create_task(self._execute(job, run))
            return job

    async def _execute(
        self, job: ImageJob, run: Callable[[], Awaitable[str]]
    ) -> None:
        try:
            async with self._worker:
                if job.status == JobStatus.CANCELLED:
                    return
                job.status = JobStatus.RUNNING
                result = await asyncio.wait_for(run(), timeout=self.timeout_seconds)
                if not isinstance(result, str) or not result:
                    raise ValueError("Image engine returned no artifact reference")
                job.result = result
                job.status = JobStatus.SUCCEEDED
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            raise
        except Exception:
            job.status = JobStatus.FAILED
            job.error = "Image generation failed"
        finally:
            job.completed_at = time.time()
            self._tasks.pop(job.id, None)

    def get(self, owner_id: str, job_id: str) -> ImageJob | None:
        job = self._jobs.get(job_id)
        return job if job is not None and job.owner_id == owner_id else None

    async def cancel(self, owner_id: str, job_id: str) -> bool:
        async with self._lock:
            job = self.get(owner_id, job_id)
            if job is None or job.status in (
                JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED
            ):
                return False
            job.status = JobStatus.CANCELLED
            task = self._tasks.get(job_id)
            if task is not None:
                task.cancel()
            return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
