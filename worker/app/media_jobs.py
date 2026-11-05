"""Bounded in-memory media job admission and lifecycle.

No background worker, generator invocation or API route is activated here.
An orchestrator may use this state machine after authentication and policy gates.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from uuid import uuid4


class MediaJobError(ValueError):
    pass


class MediaJobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class MediaJob:
    id: str
    kind: str
    state: MediaJobState
    created_at: str
    output_name: str | None = None
    error_code: str | None = None


class MediaJobQueue:
    """Single-process bounded admission; not a durable distributed queue."""

    def __init__(self, *, capacity: int = 16, max_active: int = 1):
        if capacity < 1 or max_active < 1 or max_active > capacity:
            raise MediaJobError("Invalid queue limits")
        self._capacity = capacity
        self._max_active = max_active
        self._jobs: dict[str, MediaJob] = {}
        self._lock = RLock()

    def submit(self, kind: str) -> MediaJob:
        if kind not in {"image", "video"}:
            raise MediaJobError("Unsupported media kind")
        with self._lock:
            outstanding = sum(j.state in {MediaJobState.QUEUED, MediaJobState.RUNNING} for j in self._jobs.values())
            if outstanding >= self._capacity:
                raise MediaJobError("Media queue full")
            job = MediaJob(uuid4().hex, kind, MediaJobState.QUEUED, datetime.now(timezone.utc).isoformat())
            self._jobs[job.id] = job
            return job

    def get(self, job_id: str) -> MediaJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, job_id: str) -> MediaJob:
        with self._lock:
            job = self._require(job_id)
            if job.state != MediaJobState.QUEUED:
                raise MediaJobError("Job is not queued")
            if sum(j.state == MediaJobState.RUNNING for j in self._jobs.values()) >= self._max_active:
                raise MediaJobError("Media worker busy")
            return self._set(job, state=MediaJobState.RUNNING)

    def complete(self, job_id: str, output_name: str) -> MediaJob:
        with self._lock:
            job = self._require(job_id)
            if job.state != MediaJobState.RUNNING:
                raise MediaJobError("Job is not running")
            if not output_name or "/" in output_name or "\\" in output_name or output_name in {".", ".."}:
                raise MediaJobError("Invalid output name")
            return self._set(job, state=MediaJobState.SUCCEEDED, output_name=output_name)

    def fail(self, job_id: str, error_code: str = "generation_failed") -> MediaJob:
        with self._lock:
            job = self._require(job_id)
            if job.state not in {MediaJobState.QUEUED, MediaJobState.RUNNING}:
                raise MediaJobError("Job already terminal")
            if error_code not in {"generation_failed", "storage_unavailable", "timeout", "cancelled_by_worker"}:
                raise MediaJobError("Invalid error code")
            return self._set(job, state=MediaJobState.FAILED, error_code=error_code)

    def cancel(self, job_id: str) -> MediaJob:
        with self._lock:
            job = self._require(job_id)
            if job.state != MediaJobState.QUEUED:
                raise MediaJobError("Only queued jobs can be cancelled")
            return self._set(job, state=MediaJobState.CANCELLED)

    def _require(self, job_id: str) -> MediaJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise MediaJobError("Unknown job")
        return job

    def _set(self, job: MediaJob, **changes: object) -> MediaJob:
        updated = replace(job, **changes)
        self._jobs[job.id] = updated
        return updated
