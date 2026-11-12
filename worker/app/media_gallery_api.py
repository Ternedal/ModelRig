"""Internal gallery read routes: the installation's completed assets only (#2275 6819704169).

The device-facing half is ``backend/internal/httpapi/media_routes.go`` with the worker-backed
catalog (#2365). Go never reads the media volume itself:

    Android --Bearer--> Go authMW --loopback + internal secret--> worker /internal/media/assets

**Why the worker.** Two facts decide whether an asset may be shown, and the worker holds both:

- **who owns it.** Only the executor's account reads the job database (docs/MEDIA_WORK_AREA.md),
  and R17.5 runs the worker as that account. An asset is listed or served only if a *completed*
  job of the installation published it (``ImageJobStore.completed_assets_for`` /
  ``owns_completed_asset``). A failed, running, publishing or expired job's asset, and an indexed
  file no job produced, are not the installation's media, so they are 404 like an unknown id.
- **whether the bytes are the verified volume's.** Every request goes through the production
  ``MountedMediaVolume``: the marker and its id, no network or ``subst`` drive, not the system
  disk, and the identity pinned at the first build. The file is opened without following a link
  and then checked with ``require_descriptor`` before any byte is sent. A volume lost once stays
  lost for this process (the same sticky rule as the executor): 503 until the worker restarts.

**Order:** newest first, so a new result is on the first page. The cursor is the last id of the
previous page.

**Three states, never more.** Owned and verified → 200/206 (or 416 for a range past the end).
Not owned, or unknown → 404, decided from the job database *before* the volume is touched, so the
answer says nothing about what is on the disk. Cannot decide (database error, more than 10,000
assets, volume missing or changed, index invalid, an owned asset missing or of another size) →
503 with a code, never an empty 200 and never a 404.

**Default off.** Mounted with the job routes, only with ``KALIV_MEDIA_JOBS_API=1``. Without a
usable configuration it answers 503 with a code and opens nothing.

**Never in a response or a log line:** a path, the secret, a prompt.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from pathlib import Path
from typing import Callable, Iterator, Mapping

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .image_job_store import ImageJobError, ImageJobStore
from .media_gallery_catalog import GalleryUnavailable, _ID, _index, _root
from .media_generation_contract import ArtifactSinkUnavailable
from .media_job_api import (OWNER, JOB_DB_ENV, MediaJobsUnavailable, SECRET_ENV, _usable_secret,
                            MediaJobService)
from .netguard import is_loopback

MEDIA_ROOT_ENV = "KALIV_MEDIA_ROOT"
SCHEMA = "kaliv-media-gallery/v1"
MAX_PAGE = 100
CHUNK = 1024 * 1024
EXTENSIONS = {"image/png": ".png", "video/mp4": ".mp4", "image/jpeg": ".jpg", "image/webp": ".webp"}
_RANGE = re.compile(r"bytes=([0-9]*)-([0-9]*)\Z")
PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def refuse(status: int, code: str) -> HTTPException:
    """Every refusal is private too: an error says something about the installation's media."""
    return HTTPException(status_code=status, detail=code, headers=PRIVATE)


class MediaGalleryService:
    """The configured half: the job store (ownership), the verified volume and the gallery root."""

    def __init__(self, store: ImageJobStore, volume, media_root: str | os.PathLike, secret: str):
        if not isinstance(store, ImageJobStore):
            raise MediaJobsUnavailable("media_gallery_store_invalid")
        if not _usable_secret(secret):
            raise MediaJobsUnavailable("media_jobs_secret_invalid")
        self.store, self.volume, self.secret = store, volume, secret
        self.media_root = Path(media_root)

    authorized = MediaJobService.authorized

    # -- the volume ---------------------------------------------------------------------------
    def gallery_root(self) -> Path:
        """The gallery folder, verified on the pinned volume right now."""
        self.volume.require(self.media_root)
        try:
            return _root(self.media_root, verified_volume_root=self.volume.root)
        except GalleryUnavailable as exc:
            raise ArtifactSinkUnavailable(str(exc)) from None

    def index(self) -> list[dict]:
        root = self.gallery_root()
        try:
            return _index(root)
        except GalleryUnavailable as exc:
            raise ArtifactSinkUnavailable(str(exc)) from None

    # -- ownership ----------------------------------------------------------------------------
    def owned(self) -> frozenset[str]:
        try:
            return self.store.completed_assets_for(OWNER)
        except ImageJobError as exc:  # owner_asset_limit: a refusal, never a partial set
            raise ArtifactSinkUnavailable(str(exc)) from None

    def owns(self, asset_id: str) -> bool:
        return self.store.owns_completed_asset(OWNER, asset_id)

    # -- the routes' work ---------------------------------------------------------------------
    def page(self, limit: int, cursor: str | None) -> dict:
        owned = self.owned()  # before the volume: a database failure says nothing about the disk
        items = []
        for item in self.index():
            if item["id"] not in owned:
                continue
            if item["thumbnail_id"] is not None and item["thumbnail_id"] not in owned:
                item = {**item, "thumbnail_id": None, "thumbnail_url": None}  # never a link to a 404
            items.append(item)
        # Newest first (#2367 C6 G3): the sink appends to the index, so a new result is on the
        # first page instead of the last. The cursor is still the last id of the previous page.
        items.reverse()
        start = 0
        if cursor is not None:
            positions = [i for i, item in enumerate(items) if item["id"] == cursor]
            if not positions:
                raise refuse(400, "unknown_cursor")
            start = positions[0] + 1
        page = items[start:start + limit]
        next_cursor = page[-1]["id"] if start + limit < len(items) and page else None
        return {"schema": SCHEMA, "items": page, "next_cursor": next_cursor}

    def open_asset(self, asset_id: str) -> tuple[int, dict, os.stat_result]:
        """(fd, index entry, fstat) of an owned asset, verified on the volume. The caller closes fd."""
        if not self.owns(asset_id):
            raise refuse(404, "asset_not_found")
        entries = [item for item in self.index() if item["id"] == asset_id]
        if len(entries) != 1:
            raise ArtifactSinkUnavailable("media_asset_not_indexed")  # owned, yet not in the gallery
        entry = entries[0]
        extension = EXTENSIONS.get(entry["mime_type"])
        if extension is None:
            raise ArtifactSinkUnavailable("media_asset_type_refused")
        path = self.gallery_root() / f"{asset_id}{extension}"
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags)
        except OSError:
            raise ArtifactSinkUnavailable("media_asset_missing") from None
        try:
            opened = self.volume.require_descriptor(fd, path)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size != entry["size_bytes"]:
                raise ArtifactSinkUnavailable("media_asset_size_mismatch")
        except BaseException:
            os.close(fd)
            raise
        return fd, entry, opened


def byte_range(header: str | None, size: int) -> tuple[int, int, bool] | str:
    """(start, end inclusive, partial), "ignore" (serve 200) or "unsatisfiable" (416). One range
    only, as the Go side sends; the same rules as ``backend/internal/httpapi/media_range.go``."""
    if not header:
        return (0, size - 1, False)
    match = _RANGE.fullmatch(header.strip())
    if match is None:
        return "ignore"
    first, last = match.groups()
    if first == "" and last == "":
        return "ignore"
    if first == "":
        suffix = int(last)
        if suffix == 0 or size == 0:
            return "unsatisfiable"
        return (max(0, size - suffix), size - 1, True)
    start = int(first)
    end = int(last) if last else size - 1
    if last and end < start:
        return "ignore"
    if start >= size:
        return "unsatisfiable"
    return (start, min(end, size - 1), True)


def _chunks(fd: int, start: int, length: int) -> Iterator[bytes]:
    try:
        os.lseek(fd, start, os.SEEK_SET)
        left = length
        while left > 0:
            chunk = os.read(fd, min(CHUNK, left))
            if not chunk:
                return  # the file shrank under us: the client sees a short body and refuses it
            left -= len(chunk)
            yield chunk
    finally:
        os.close(fd)


def build_media_gallery_router(service: Callable[[], MediaGalleryService], *,
                               loopback: Callable[[str], bool] = is_loopback) -> APIRouter:
    router = APIRouter(prefix="/internal/media/assets", tags=["internal-media-gallery"])

    def ready(request: Request, x_internal_media_secret: str | None = Header(default=None)) -> MediaGalleryService:
        host = request.client.host if request.client else ""
        if not loopback(host):
            raise refuse(401, "loopback_required")
        try:
            configured = service()
        except (MediaJobsUnavailable, ArtifactSinkUnavailable) as exc:
            raise refuse(503, str(exc).split(":", 1)[0]) from None
        if not configured.authorized(x_internal_media_secret):
            raise refuse(401, "internal_authentication_required")
        return configured

    def guarded(call: Callable[[], object]) -> object:
        try:
            return call()
        except HTTPException:
            raise
        except ArtifactSinkUnavailable as exc:
            raise refuse(503, str(exc).split(":", 1)[0]) from None
        except (ImageJobError, OSError, ValueError, sqlite3.Error):
            raise refuse(503, "media_gallery_unavailable") from None

    private = PRIVATE

    @router.get("")
    def page(request: Request, configured: MediaGalleryService = Depends(ready)) -> Response:
        query = request.query_params
        if set(query) - {"limit", "cursor"} or len(query.getlist("limit")) > 1 or len(query.getlist("cursor")) > 1:
            raise refuse(400, "invalid_query")
        raw_limit, cursor = query.get("limit", "50"), query.get("cursor")
        if not re.fullmatch(r"[1-9][0-9]{0,2}", raw_limit) or not 1 <= int(raw_limit) <= MAX_PAGE:
            raise refuse(400, "invalid_limit")
        if cursor is not None and not _ID.fullmatch(cursor):
            raise refuse(400, "invalid_cursor")
        body = guarded(lambda: configured.page(int(raw_limit), cursor))
        return Response(json.dumps(body, separators=(",", ":")), media_type="application/json", headers=private)

    @router.api_route("/{asset_id}", methods=["GET", "HEAD"])
    def asset(asset_id: str, request: Request, configured: MediaGalleryService = Depends(ready)) -> Response:
        if not _ID.fullmatch(asset_id):
            raise refuse(404, "asset_not_found")
        fd, entry, opened = guarded(lambda: configured.open_asset(asset_id))
        size = opened.st_size
        ranged = byte_range(request.headers.get("range"), size)
        if ranged == "ignore":
            ranged = byte_range(None, size)
        if ranged == "unsatisfiable":
            os.close(fd)
            return Response(status_code=416, headers={**private, "Content-Range": f"bytes */{size}",
                                                      "Accept-Ranges": "bytes"})
        start, end, partial = ranged
        length = max(0, end - start + 1)
        headers = {**private, "Accept-Ranges": "bytes", "Content-Length": str(length)}
        if partial:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status = 206 if partial else 200
        if request.method == "HEAD":
            os.close(fd)
            return Response(status_code=status, headers=headers, media_type=entry["mime_type"])
        return StreamingResponse(_chunks(fd, start, length), status_code=status, headers=headers,
                                 media_type=entry["mime_type"])

    return router


def gallery_service_from_env(env: Mapping[str, str] | None = None, *, work_probe=None,
                             volume_probe=None) -> MediaGalleryService:
    """The production configuration: the same secret and job database as the job routes, plus the
    verified media volume. Raises MediaJobsUnavailable (a code) or ArtifactSinkUnavailable."""
    env = os.environ if env is None else env
    secret = env.get(SECRET_ENV, "")
    if not _usable_secret(secret):
        raise MediaJobsUnavailable("media_jobs_secret_invalid")
    from .media_volume import MediaVolumeConfigError, media_volume_from_env
    from .media_work_area import MediaWorkAreaConfigError, work_area_from_env
    try:
        work = work_area_from_env(env, probe=work_probe)
    except MediaWorkAreaConfigError as exc:
        raise MediaJobsUnavailable(str(exc).split(":", 1)[0]) from None
    job_db = env.get(JOB_DB_ENV, "")
    if not job_db or not os.path.isabs(job_db):
        raise MediaJobsUnavailable("media_jobs_db_invalid")
    job_dir = os.path.dirname(job_db)
    try:
        work.require(job_dir)
    except ArtifactSinkUnavailable:
        raise MediaJobsUnavailable("media_jobs_db_not_in_work_area") from None
    media_root = env.get(MEDIA_ROOT_ENV, "")
    if not media_root or not os.path.isabs(media_root):
        raise MediaJobsUnavailable("media_gallery_root_invalid")
    try:
        volume = media_volume_from_env(env, probe=volume_probe)
    except MediaVolumeConfigError as exc:
        raise MediaJobsUnavailable(str(exc).split(":", 1)[0].split(" ", 1)[0]) from None
    try:
        store = ImageJobStore(job_db, volume_guard=lambda: work.require(job_dir))
    except ArtifactSinkUnavailable:
        raise MediaJobsUnavailable("media_jobs_work_area_unavailable") from None
    except (ImageJobError, OSError, ValueError, sqlite3.DatabaseError):
        raise MediaJobsUnavailable("media_jobs_store_invalid") from None
    return MediaGalleryService(store, volume, media_root, secret)
