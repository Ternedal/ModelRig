"""Opt-in image orchestration: fixed workflow -> ComfyUI -> bounded polling.

No production route is registered by importing this module. The caller must
provide an operator-reviewed workflow, authenticated owner, and artifact policy.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from .comfyui_adapter import ComfyUIAdapter, ComfyUIError
from .jobs import ImageJob, ImageJobManager
from .workflow import WorkflowSlots, render_workflow


class ImageGenerationService:
    def __init__(
        self,
        adapter: ComfyUIAdapter,
        template: dict[str, Any],
        slots: WorkflowSlots,
        *,
        poll_interval: float = 1.0,
        max_polls: int = 300,
        manager: ImageJobManager | None = None,
    ):
        if not 0 < poll_interval <= 30 or not 1 <= max_polls <= 3600:
            raise ValueError("Invalid polling limits")
        self.adapter = adapter
        self.template = template
        self.slots = slots
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.manager = manager or ImageJobManager()

    async def submit(self, owner_id: str, prompt: str, seed: int | None = None) -> ImageJob:
        # Validate synchronously before admitting an asynchronous job.
        workflow = render_workflow(self.template, self.slots, prompt=prompt, seed=seed)

        async def run() -> str:
            prompt_id = await self.adapter.submit(workflow, client_id=str(uuid.uuid4()))
            for _ in range(self.max_polls):
                history = await self.adapter.history(prompt_id)
                entry = history.get(prompt_id)
                if isinstance(entry, dict):
                    status = entry.get("status")
                    if isinstance(status, dict) and status.get("status_str") == "error":
                        raise ComfyUIError("Image generation failed")
                    if isinstance(entry.get("outputs"), dict) and entry["outputs"]:
                        # No arbitrary ComfyUI filename is exposed to clients.
                        # An artifact ingestion service must resolve validated outputs.
                        return prompt_id
                await asyncio.sleep(self.poll_interval)
            raise ComfyUIError("Image generation timed out")

        return await self.manager.submit(owner_id, run)

    async def shutdown(self) -> None:
        await self.manager.shutdown()
