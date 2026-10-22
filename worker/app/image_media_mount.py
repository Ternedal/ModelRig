"""Explicitly gated image API mount for the production worker.

Never creates directories on the system disk and never exposes routes without
an operator-selected, verified mounted media volume.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from .image_internal_api import configure_image_routes, router
from .image_job_store import ImageJobStore
from .image_media_store import ExternalMediaStore


def mount_image_media(app: FastAPI) -> bool:
    if os.getenv("KALIV_IMAGE_MEDIA_PILOT", "0") != "1":
        return False

    secret = os.getenv("KALIV_IMAGE_INTERNAL_SECRET", "")
    root = os.getenv("KALIV_IMAGE_MEDIA_ROOT", "")
    volume = os.getenv("KALIV_IMAGE_EXTERNAL_MOUNT", "")
    database = os.getenv("KALIV_IMAGE_JOBS_DB", "")
    if len(secret) < 32 or not all((root, volume, database)):
        raise RuntimeError("image media pilot requires secret, mounted volume, media root and jobs DB")

    # The SQLite queue belongs on the same verified volume as generated assets.
    # Do not allow its first connection to create an internal-disk file.
    store = ExternalMediaStore(root, [volume])
    db_path = Path(database)
    if not db_path.is_absolute() or db_path.is_symlink():
        raise RuntimeError("image jobs database path must be absolute and non-symlink")
    resolved_parent = db_path.parent.resolve(strict=True)
    if resolved_parent != store.root and store.root not in resolved_parent.parents:
        raise RuntimeError("image jobs database must live under the external media root")
    store._check_mount()
    jobs = ImageJobStore(str(db_path), volume_guard=store._check_mount)
    configure_image_routes(jobs, store, internal_secret=secret)
    app.include_router(router)
    return True
