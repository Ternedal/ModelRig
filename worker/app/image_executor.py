"""Single-process opt-in image executor.

Run as a separate operator-managed process, never as a FastAPI import side
effect. A real renderer is loaded only after all storage admission checks.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .image_job_runner import ImageJobRunner
from .image_job_store import ImageJobStore
from .image_media_store import ExternalMediaStore
from .qwen_image_adapter import QwenImageAdapter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in Qwen image job processor")
    parser.add_argument("--once", action="store_true", help="process at most one queued job")
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--device", choices=("cuda:0", "cuda:1"), default="cuda:1")
    args = parser.parse_args(argv)
    if args.poll_seconds < 1 or args.poll_seconds > 300:
        parser.error("poll-seconds must be 1..300")

    if os.getenv("KALIV_IMAGE_MEDIA_PILOT", "0") != "1":
        print("Image media pilot is disabled", file=sys.stderr)
        return 2
    root = os.getenv("KALIV_IMAGE_MEDIA_ROOT", "")
    volume = os.getenv("KALIV_IMAGE_EXTERNAL_MOUNT", "")
    database = os.getenv("KALIV_IMAGE_JOBS_DB", "")
    model = os.getenv("KALIV_IMAGE_MODEL_ID", "")
    cache = os.getenv("HF_HOME", "")
    offline = os.getenv("HF_HUB_OFFLINE", "")
    if not all((root, volume, database, model, cache)) or offline != "1":
        print("Image executor requires external volume, root, database, model, HF_HOME and HF_HUB_OFFLINE=1", file=sys.stderr)
        return 2

    # The mount guard is checked for every database connection, including
    # recovery and claim. Never create a queue on an unmounted system disk.
    media = ExternalMediaStore(root, [volume])
    db_path = Path(database)
    if not db_path.is_absolute() or db_path.is_symlink():
        raise RuntimeError("image database must be an absolute non-symlink path")
    parent = db_path.parent.resolve(strict=True)
    if parent != media.root and media.root not in parent.parents:
        raise RuntimeError("image database must reside on external media volume")
    cache_path = Path(cache)
    if not cache_path.is_absolute() or cache_path.is_symlink():
        raise RuntimeError("HF_HOME must be an absolute non-symlink path")
    cache_root = cache_path.resolve(strict=True)
    if cache_root != media.root and media.root not in cache_root.parents:
        raise RuntimeError("HF_HOME must be on the external media volume")
    media._check_mount()
    jobs = ImageJobStore(str(db_path), volume_guard=media._check_mount)
    jobs.recover_interrupted()

    # No automatic model downloads on the normal worker path. The operator
    # explicitly starts this process after choosing a model/cache location.
    renderer = QwenImageAdapter(model, device=args.device, cpu_offload=True)
    renderer.load()
    runner = ImageJobRunner(jobs, media, renderer)
    while True:
        result = runner.run_one()
        if args.once:
            return 0
        if result is None:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
