"""Offline opt-in video queue dispatcher.

Does not mount routes or execute a Wan workflow by itself. The workflow_factory
must be operator-owned and must never accept arbitrary graph JSON from clients.
"""
from __future__ import annotations

import json
from typing import Callable

from .video_comfy_adapter import ComfyVideoClient, VideoBackendError
from .video_contract import VideoRequest
from .video_job_store import VideoJobStore
from .video_storage_config import configured_video_storage


class VideoDispatcher:
    def __init__(self, store: VideoJobStore, client: ComfyVideoClient,
                 workflow_factory: Callable[[VideoRequest], dict]):
        self.store = store
        self.client = client
        self.workflow_factory = workflow_factory

    def dispatch_one(self) -> str | None:
        """Claim one queued job and submit it. No background loop is started."""
        # Storage admission precedes claiming a job or contacting ComfyUI.
        # If the external volume is absent, leave the job queued.
        configured_video_storage().assert_ready()
        for row in self.store.queued(limit=1):
            job_id = row["job_id"]
            if not self.store.transition(job_id, "queued", "running"):
                return None
            try:
                request = VideoRequest(**json.loads(row["request_json"]))
                workflow = self.workflow_factory(request)
                if not isinstance(workflow, dict) or not workflow:
                    raise ValueError("Missing trusted workflow")
                prompt_id = self.client.submit_trusted_workflow(workflow)
                # Persist correlation before a separate collector verifies output.
                if not self.store.record_prompt(job_id, prompt_id):
                    raise VideoBackendError("Cannot persist backend prompt ID")
                return prompt_id
            except (VideoBackendError, ValueError, TypeError, KeyError, OSError):
                self.store.transition(job_id, "running", "failed", error_code="submission_failed")
                return None
        return None
