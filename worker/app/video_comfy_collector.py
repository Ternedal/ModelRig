"""One-shot collector for a trusted ComfyUI MP4 output directory.

This module has no HTTP routes or automatic background execution.
"""
from __future__ import annotations

import shutil
import uuid
import os
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
        storage = configured_video_storage()
        storage.assert_ready()
        approved_root = Path(storage.root).resolve(strict=True)
        if not self.output_root.is_relative_to(approved_root):
            raise ValueError("ComfyUI output root must be inside approved external storage")
        if not self.catalog.media_root.resolve().is_relative_to(approved_root):
            raise ValueError("Media catalog must be inside approved external storage")
        # Production database paths must remain on the approved volume.
        for row in self.store.awaiting_result(limit=1):
            try:
                outputs = self.client.completed_outputs(row["prompt_id"])
                if outputs is None:
                    return None
                if not isinstance(outputs, dict):
                    raise ValueError("Malformed ComfyUI output collection")
                files = []
                malformed_output = False
                for node in outputs.values():
                    if not isinstance(node, dict):
                        malformed_output = True
                        continue
                    for key in ("gifs", "videos"):
                        entries = node.get(key, [])
                        if not isinstance(entries, list):
                            malformed_output = True
                            continue
                        for entry in entries:
                            if not isinstance(entry, dict):
                                malformed_output = True
                                continue
                            if entry.get("type") != "output":
                                continue
                            name = entry.get("filename")
                            folder = entry.get("subfolder", "")
                            if not isinstance(name, str) or not isinstance(folder, str):
                                malformed_output = True
                                continue
                            if Path(name).name != name or "\\" in name or ":" in name or not name.lower().endswith(".mp4"):
                                malformed_output = True
                                continue
                            if Path(folder).is_absolute() or ".." in Path(folder).parts or "\\" in folder or ":" in folder:
                                malformed_output = True
                                continue
                            # Reject symlinked parent directories too: resolving
                            # a path inside the root is not sufficient if a
                            # subfolder is an alias to another writable tree.
                            relative = Path(folder) / name
                            cursor = self.output_root
                            symlinked = False
                            for part in relative.parts:
                                cursor = cursor / part
                                if cursor.is_symlink():
                                    symlinked = True
                                    break
                            if symlinked or not cursor.is_file():
                                malformed_output = True
                                continue
                            resolved = cursor.resolve(strict=True)
                            if resolved.is_relative_to(self.output_root):
                                files.append(resolved)
                            else:
                                malformed_output = True
                if malformed_output or len(files) != 1 or not 0 < files[0].stat().st_size <= 2 * 1024 ** 3:
                    raise ValueError("Expected exactly one valid MP4 output")
                # A file that is still being written must not be published.
                initial_stat = files[0].stat()
                initial_size = initial_stat.st_size
                with files[0].open("rb") as probe:
                    header = probe.read(12)
                if len(header) != 12 or header[4:8] != b"ftyp" or int.from_bytes(header[:4], "big") < 12:
                    raise ValueError("ComfyUI output is not an MP4 container")
                media_id = uuid.uuid4().hex
                target = self.catalog.media_root / "Videos" / (media_id + ".mp4")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.parent.is_symlink() or not target.parent.resolve(strict=True).is_relative_to(approved_root):
                    raise ValueError("Video destination must remain on approved external storage")
                try:
                    with files[0].open("rb") as source, target.open("xb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                        destination.flush()
                        os.fsync(destination.fileno())
                    final_stat = files[0].stat()
                    if (final_stat.st_size != initial_size or
                        final_stat.st_mtime_ns != initial_stat.st_mtime_ns or
                        target.stat().st_size != initial_size):
                        raise ValueError("ComfyUI output changed during copy")
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                # Only a successful catalog insert makes the copied file durable.
                try:
                    self.catalog.register(MediaItem(media_id=media_id, kind="video"), target)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                # Never delete a registered asset if the final job update fails.
                if not self.store.transition(row["job_id"], "running", "completed", artifact_id=media_id):
                    raise ValueError("Job transition failed")
                return media_id
            except (OSError, ValueError, VideoBackendError):
                self.store.transition(row["job_id"], "running", "failed", error_code="invalid_backend_output")
                return None
        return None
