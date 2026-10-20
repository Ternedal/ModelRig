"""Small deterministic lifecycle for video-generation jobs.

This is a domain primitive only: it is not a persistent queue, HTTP route,
worker, or GPU scheduler. Those integrations must add durable ownership and
cancellation semantics before production use.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VideoJobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL = {VideoJobState.COMPLETED, VideoJobState.FAILED, VideoJobState.CANCELLED}
_ALLOWED = {
    VideoJobState.QUEUED: {VideoJobState.RUNNING, VideoJobState.CANCELLED, VideoJobState.FAILED},
    VideoJobState.RUNNING: {VideoJobState.COMPLETED, VideoJobState.CANCELLED, VideoJobState.FAILED},
}


@dataclass
class VideoJob:
    job_id: str
    state: VideoJobState = VideoJobState.QUEUED
    error_code: str | None = None

    def transition(self, target: VideoJobState, *, error_code: str | None = None) -> None:
        if self.state in _TERMINAL:
            raise ValueError("Terminal video job cannot transition")
        if target not in _ALLOWED.get(self.state, set()):
            raise ValueError(f"Invalid video job transition: {self.state.value} -> {target.value}")
        if target == VideoJobState.FAILED:
            if not error_code or len(error_code) > 64 or not error_code.isascii() or not all(c.islower() or c.isdigit() or c == "_" for c in error_code):
                raise ValueError("A bounded error code is required")
            self.error_code = error_code
        elif error_code is not None:
            raise ValueError("Error code only applies to failed jobs")
        self.state = target
