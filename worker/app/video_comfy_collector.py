"""One-shot collector for a trusted ComfyUI MP4 output directory.

This module has no HTTP routes or automatic background execution.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from .video_comfy_adapter import ComfyVideoClient, VideoBackendError
from .video_job_store import VideoJobStore
from .video_media_catalog import MediaCatalog
from .video_media_contract import MediaItem
from .video_storage_config import configured_video_storage


class VideoResultCollector:
    def __init__(self, store: VideoJobStore, client: ComfyVideoClient,
                 catalog: MediaCatalog, output_root: Path):
        self.store = store
        self.client = client
        self.catalog = catalog
        supplied_root = Path(output_root)
        if supplied_root.is_symlink():
            raise ValueError("Symlinked ComfyUI output root is forbidden")
        self.output_root = supplied_root.resolve(strict=True)
        if not self.output_root.is_dir():
            raise ValueError("ComfyUI output root is required")

    def collect_one(self) -> str | None:
        configured_video_storage().assert_ready()
        for row in self.store.awaiting_result(limit=1):
            try:
                outputs = self.client.completed_outputs(row["prompt_id"])
                if outputs is None:
                    return None
                files = []
                for node in outputs.values():
                    if not isinstance(node, dict):
                        continue
                    for key in ("gifs", "videos"):
                        entries = node.get(key, [])
                        if not isinstance(entries, list):
                            continue
                        for entry in entries:
                            if not isinstance(entry, dict) or entry.get("type") != "output":
                                continue
                            name = entry.get("filename")
                            folder = entry.get("subfolder", "")
                            if not isinstance(name, str) or not isinstance(folder, str):
                                continue
                            if Path(name).name != name or not name.lower().endswith(".mp4"):
                                continue
                            if Path(folder).is_absolute() or ".." in Path(folder).parts or "\\\\" in folder or ":" in folder:
                                continue
                            candidate = self.output_root / folder / name
                            if candidate.is_symlink() or not candidate.is_file():
                                continue
                            resolved = candidate.resolve(strict=True)
                            if resolved.is_relative_to(self.output_root):
                                files.append(resolved)
                if len(files) != 1 or not 0 < files[0].stat().st_size <= 2 * 1024 ** 3:
                    raise ValueError("Expected exactly one valid MP4 output")
                media_id = uuid.uuid4().hex
                target = self.catalog.media_root / "Videos" / (media_id + ".mp4")
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with files[0].open("rb") as source, target.open("xb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                try:
                    self.catalog.register(MediaItem(media_id=media_id, kind="video"), target)
                    if not self.store.transition(row["job_id"], "running", "completed", artifact_id=media_id):
                        raise ValueError("Job transition failed")
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                return media_id
            except (OSError, ValueError, VideoBackendError):
                self.store.transition(row["job_id"], "running", "failed", error_code="invalid_backend_output")
                return None
        return None
