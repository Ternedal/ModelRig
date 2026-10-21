"""Read-only preflight CLI for an isolated Qwen Image worker.

Example from the worker directory:
    python -m app.image_preflight --gpu 1 --media-root /mnt/external/kaliv-media --external-root /mnt/external

No model weights are downloaded or loaded. No files are written.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

from .image_gpu_admission import ImageGpuAdmissionError, inspect_cuda_budget
from .image_media_store import MediaStorageError


def check_media(root: str, external_root: str, min_free_gib: float) -> dict:
    if min_free_gib < 0:
        raise MediaStorageError("invalid free-space floor")
    media = Path(root)
    external = Path(external_root)
    if not media.is_absolute() or not external.is_absolute():
        raise MediaStorageError("absolute paths required")
    if media.is_symlink() or external.is_symlink() or not media.is_dir() or not external.is_dir():
        raise MediaStorageError("existing non-symlink directories required")
    media_real, external_real = media.resolve(strict=True), external.resolve(strict=True)
    if media_real != external_real and external_real not in media_real.parents:
        raise MediaStorageError("media root outside configured external root")
    # Ensure the configured external root is a distinct mount, not an ordinary
    # folder on the OS filesystem. This is necessary but not sufficient to prove
    # the backing drive is physically external (USB/SATA/other).
    if os.path.ismount(external_real) is False:
        raise MediaStorageError("configured external root is not a mount point")
    usage = shutil.disk_usage(media_real)
    if usage.free < int(min_free_gib * 1024**3):
        raise MediaStorageError("insufficient media disk space")
    return {"media_root": str(media_real), "external_mount": str(external_real),
            "free_bytes": usage.free, "total_bytes": usage.total}


def run_preflight(gpu: int, media_root: str, external_root: str,
                  reserve_gib: float, min_usable_gib: float, min_disk_gib: float) -> dict:
    media = check_media(media_root, external_root, min_disk_gib)
    budget = inspect_cuda_budget(gpu, reserve_gib=reserve_gib,
                                 min_usable_gib=min_usable_gib)
    return {"status": "ready_for_model_qualification", "media": media,
            "gpu": {"index": budget.index, "total_bytes": budget.total_bytes,
                    "free_bytes": budget.free_bytes, "reserved_bytes": budget.reserved_bytes,
                    "usable_bytes": budget.usable_bytes}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", type=int, default=1)
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--external-root", required=True)
    parser.add_argument("--reserve-gib", type=float, default=3)
    parser.add_argument("--min-usable-gib", type=float, default=6)
    parser.add_argument("--min-disk-gib", type=float, default=2)
    args = parser.parse_args()
    try:
        report = run_preflight(args.gpu, args.media_root, args.external_root,
                               args.reserve_gib, args.min_usable_gib, args.min_disk_gib)
    except (MediaStorageError, ImageGpuAdmissionError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}))
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
