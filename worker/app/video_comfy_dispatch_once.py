"""Operator-only one-shot dispatch of a queued text-to-video job.

No routes, background polling, model downloads or ComfyUI process launches.
Requires an operator-installed ComfyUI API-format JSON template on the
configured external media volume.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .video_comfy_adapter import ComfyVideoClient
from .video_dispatcher import VideoDispatcher
from .video_job_store import VideoJobStore
from .video_storage_config import configured_video_storage
from .video_workflow_template import trusted_text_to_video_factory


def dispatch_once() -> str | None:
    storage = configured_video_storage()
    paths = storage.initialize_directories()
    value = os.environ.get("KALIV_COMFY_WORKFLOW_TEMPLATE", "").strip()
    if not value:
        raise ValueError("KALIV_COMFY_WORKFLOW_TEMPLATE is required")
    template = Path(value)
    if not template.is_absolute() or template.is_symlink():
        raise ValueError("Workflow template must be an absolute regular file")
    root = storage.root.resolve(strict=True)
    if not template.resolve(strict=True).is_relative_to(root):
        raise ValueError("Workflow template must be on the external media volume")
    factory = trusted_text_to_video_factory(template)
    store = VideoJobStore(paths["jobs"] / "video_jobs.sqlite")
    return VideoDispatcher(store, ComfyVideoClient(), factory).dispatch_one()


def main() -> int:
    try:
        prompt_id = dispatch_once()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Video dispatch unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2
    if prompt_id:
        print(f"Submitted ComfyUI prompt ID: {prompt_id}")
    else:
        print("No queued video submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
