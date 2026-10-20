"""Operator-only one-shot ComfyUI result collection.

Run with PYTHONPATH=worker python -m app.video_comfy_collect_once.
Requires explicit KALIV_MEDIA_ROOT and COMFYUI_OUTPUT_DIRECTORY.
No worker routes, polling or background services are enabled.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .video_comfy_adapter import ComfyVideoClient
from .video_comfy_collector import VideoResultCollector
from .video_job_store import VideoJobStore
from .video_media_catalog import MediaCatalog
from .video_storage_config import configured_video_storage


def collect_once() -> str | None:
    storage = configured_video_storage()
    paths = storage.initialize_directories()
    output = os.environ.get("COMFYUI_OUTPUT_DIRECTORY", "").strip()
    if not output or not Path(output).is_absolute():
        raise ValueError("COMFYUI_OUTPUT_DIRECTORY must be an absolute path")
    output_root = Path(output).resolve(strict=True)
    if not output_root.is_relative_to(storage.root):
        raise ValueError("ComfyUI output must reside on configured external volume")
    store = VideoJobStore(paths["jobs"] / "video_jobs.sqlite")
    catalog = MediaCatalog(storage.root)
    collector = VideoResultCollector(store, ComfyVideoClient(), catalog, output_root)
    return collector.collect_one()


def main() -> int:
    try:
        media_id = collect_once()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Video collection unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2
    if media_id:
        print(f"Registered media ID: {media_id}")
    else:
        print("No completed video available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
