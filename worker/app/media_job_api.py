"""Internal job routes for media generation: submit, status, cancel (#2275 6764090458, backlog item 4).

The missing first step of the image path: until now nothing outside the tests called
``ImageJobStore.submit``. The paired device reaches these routes only through the Go backend
(``backend/internal/httpapi/media_jobs.go``):

    Android --Bearer--> Go authMW --loopback + internal secret--> worker /internal/media/jobs

**Two boundaries, both checked here.** The client must be loopback, and ``X-Internal-Media-Secret``
must match ``KALIV_MEDIA_INTERNAL_SECRET`` (at least 32 characters). Either failure gives 401, and
nothing is read. The secret is never sent to a device.

**Owner.** Always ``"installation"``, the same constant as the gallery routes (#2365
``mediaInstallationOwner``). So a job submitted here is the one ``completed_assets_for`` and
``owns_completed_asset`` list and serve. No owner header is read: there is nothing to spoof.

**Default off.** The router is mounted only with ``KALIV_MEDIA_JOBS_API=1`` (``app/main.py``).
Without a usable configuration it answers 503 with a reason code and never opens the database:

- ``KALIV_MEDIA_INTERNAL_SECRET``: at least 32 characters, no line break;
- ``KALIV_MEDIA_WORK_ROOT`` and ``KALIV_MEDIA_JOB_DB``: the job database is in the private work
  area (``media_work_area``), checked before every database access, as the executor does;
- ``KALIV_MEDIA_PROFILE_DIR`` and ``KALIV_MEDIA_PROFILES_ENABLED``: only enabled profiles are
  accepted. A video profile also needs ``KALIV_MEDIA_VIDEO=1``, and image-to-video is refused:
  the executor serves neither otherwise (#2366), so such a job would only wait 24 hours and expire.

**Validated at submit, with the executor's own rule** (``validate_request`` on the profile), so a
request the executor would refuse is a 400 now, not a failed job later.

**Never in a response or a log line:** the prompt or the parameters. Errors are codes.
"""
from __future__ import annotations

import hmac
import os
import sqlite3
from typing import Callable, Mapping

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .image_job_store import ImageJobError, ImageJobStore, public_error
from .media_generation_contract import ArtifactSinkUnavailable, GenerationError, GenerationRequest
from .media_generation_profiles import ModelProfile, enabled_profiles, load_profile_dir, validate_request
from .netguard import is_loopback

SWITCH_ENV = "KALIV_MEDIA_JOBS_API"
SECRET_ENV = "KALIV_MEDIA_INTERNAL_SECRET"
SECRET_HEADER = "X-Internal-Media-Secret"
JOB_DB_ENV = "KALIV_MEDIA_JOB_DB"
PROFILE_DIR_ENV = "KALIV_MEDIA_PROFILE_DIR"
VIDEO_ENV = "KALIV_MEDIA_VIDEO"
OWNER = "installation"  # #2365 mediaInstallationOwner
MIN_SECRET_CHARS = 32
REQUEST_PARAMS = ("width", "height", "steps", "seed", "input_asset_id", "frames")  # media_executor._REQUEST_PARAMS
NOT_SERVED_TASKS = frozenset({"image_to_video"})  # #2366: the owner-gated source reader is not wired

_ERRORS = {  # ImageJobStore messages -> codes; anything else is invalid_request
    "image job queue full": (429, "queue_full"),
    "owner image job limit reached": (429, "active_limit"),
}


class MediaJobsUnavailable(RuntimeError):
    """The routes cannot serve: a reason code, never a path or a secret."""


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile_id: str = Field(min_length=1, max_length=48)
    prompt: str = Field(min_length=1, max_length=4000)
    task: str | None = Field(default=None, max_length=32)
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    seed: int | None = None
    frames: int | None = None
    input_asset_id: str | None = Field(default=None, max_length=128)


class MediaJobService:
    """The configured half: a store, the served profiles and the secret."""

    def __init__(self, store: ImageJobStore, profiles: Mapping[str, ModelProfile], secret: str, *,
                 video_enabled: bool = False):
        if not isinstance(store, ImageJobStore):
            raise MediaJobsUnavailable("media_jobs_store_invalid")
        if not _usable_secret(secret):
            raise MediaJobsUnavailable("media_jobs_secret_invalid")
        self.store, self.profiles, self.secret = store, dict(profiles), secret
        self.video_enabled = video_enabled

    def authorized(self, supplied: str | None) -> bool:
        return isinstance(supplied, str) and hmac.compare_digest(supplied.encode(), self.secret.encode())

    def request_for(self, body: SubmitRequest) -> tuple[ModelProfile, GenerationRequest]:
        profile = self.profiles.get(body.profile_id)
        if profile is None:
            raise HTTPException(status_code=400, detail="profile_not_enabled")
        if profile.modality == "video" and not self.video_enabled:
            raise HTTPException(status_code=400, detail="video_not_enabled")
        task = body.task if body.task is not None else sorted(profile.tasks)[0]
        if task in NOT_SERVED_TASKS:
            raise HTTPException(status_code=400, detail="task_not_served")
        try:
            request = validate_request(profile, GenerationRequest(
                profile_id=profile.profile_id, task=task, prompt=body.prompt,
                **{key: getattr(body, key) for key in REQUEST_PARAMS}))
        except GenerationError:
            raise HTTPException(status_code=400, detail="invalid_request") from None
        return profile, request


def _usable_secret(secret: object) -> bool:
    return isinstance(secret, str) and len(secret) >= MIN_SECRET_CHARS and not any(c in secret for c in "\r\n")


def job_view(job: dict) -> dict:
    """What a device may see of a job: no prompt, no parameters, no internal claim."""
    asset_id = job.get("asset_id") if job.get("state") == "completed" else None
    return {
        "schema": "kaliv-media-job/v1",
        "id": job["id"],
        "state": job["state"],
        "profile_id": job.get("profile_id"),
        "asset_id": asset_id,
        "asset_url": f"/api/v1/media/{asset_id}" if asset_id else None,
        "error": public_error(job.get("error")),
        "cancel_requested": bool(job.get("cancel_requested")),
        "created": job.get("created"),
        "updated": job.get("updated"),
    }


def build_media_job_router(service: Callable[[], MediaJobService], *,
                           loopback: Callable[[str], bool] = is_loopback) -> APIRouter:
    """``service()`` returns the configured service or raises MediaJobsUnavailable (503)."""
    router = APIRouter(prefix="/internal/media/jobs", tags=["internal-media-jobs"])

    def ready(request: Request, x_internal_media_secret: str | None = Header(default=None)) -> MediaJobService:
        # A dependency, so it runs before the body is validated: without loopback and the secret a
        # caller learns nothing, not even the request schema (401, never 422).
        secret = x_internal_media_secret
        host = request.client.host if request.client else ""
        if not loopback(host):
            raise HTTPException(status_code=401, detail="loopback_required")
        try:
            configured = service()
        except MediaJobsUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        if not configured.authorized(secret):
            raise HTTPException(status_code=401, detail="internal_authentication_required")
        return configured

    def store_call(call: Callable[[], object]) -> object:
        try:
            return call()
        except ArtifactSinkUnavailable as exc:  # the work area failed its check: nothing was read
            raise HTTPException(status_code=503, detail=str(exc).split(":", 1)[0]) from None

    @router.get("/profiles")
    def profiles(configured: MediaJobService = Depends(ready)) -> dict:
        """Only profiles whose tasks are currently served; never expose model paths or pins."""
        available = []
        for profile in sorted(configured.profiles.values(), key=lambda p: p.profile_id):
            if profile.modality == "video" and not configured.video_enabled:
                continue
            tasks = sorted(profile.tasks - NOT_SERVED_TASKS)
            if not tasks:
                continue
            available.append({
                "profile_id": profile.profile_id,
                "modality": profile.modality,
                "tasks": tasks,
                "sizes": [list(size) for size in profile.limits.sizes],
                "max_steps": profile.limits.max_steps,
                "max_prompt_chars": profile.limits.max_prompt_chars,
            })
        return {"schema": "kaliv-media-job/v1", "profiles": available}

    @router.post("", status_code=202)
    def submit(body: SubmitRequest, configured: MediaJobService = Depends(ready)) -> dict:
        profile, generation = configured.request_for(body)
        if generation.input_asset_id is not None and not store_call(
                lambda: configured.store.owns_completed_asset(OWNER, generation.input_asset_id)):
            raise HTTPException(status_code=400, detail="source_not_found")
        params = {key: getattr(body, key) for key in REQUEST_PARAMS if getattr(body, key) is not None}
        if body.task is not None:
            params["task"] = body.task
        try:
            created = store_call(lambda: configured.store.submit(OWNER, body.prompt, profile_id=profile.profile_id,
                                                                 params=params))
        except ImageJobError as exc:
            status, code = _ERRORS.get(str(exc), (400, "invalid_request"))
            raise HTTPException(status_code=status, detail=code) from None
        job = store_call(lambda: configured.store.get(created["job_id"], OWNER))
        if job is None:  # just written in this process: only a broken store gets here
            raise HTTPException(status_code=503, detail="media_jobs_store_inconsistent")
        return job_view(job)

    @router.get("/{job_id}")
    def status(job_id: str, configured: MediaJobService = Depends(ready)) -> dict:
        if not _valid_job_id(job_id):
            raise HTTPException(status_code=404, detail="job_not_found")
        job = store_call(lambda: configured.store.get(job_id, OWNER))
        if job is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return job_view(job)

    @router.post("/{job_id}/cancel")
    def cancel(job_id: str, configured: MediaJobService = Depends(ready)) -> dict:
        if not _valid_job_id(job_id):
            raise HTTPException(status_code=404, detail="job_not_found")
        result = store_call(lambda: configured.store.request_cancel(job_id, OWNER))
        if result is None:
            raise HTTPException(status_code=404, detail="job_not_found_or_finished")
        job = store_call(lambda: configured.store.get(job_id, OWNER))
        return {"result": result, "job": job_view(job) if job else None}

    return router


def _valid_job_id(job_id: str) -> bool:
    return len(job_id) == 32 and all(c in "0123456789abcdef" for c in job_id)


def service_from_env(env: Mapping[str, str] | None = None, *, work_probe=None) -> MediaJobService:
    """The production configuration. Raises MediaJobsUnavailable with a reason code."""
    env = os.environ if env is None else env
    secret = env.get(SECRET_ENV, "")
    if not _usable_secret(secret):
        raise MediaJobsUnavailable("media_jobs_secret_invalid")
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
    profile_dir = env.get(PROFILE_DIR_ENV, "")
    if not profile_dir or not os.path.isabs(profile_dir):
        raise MediaJobsUnavailable("media_jobs_profile_dir_invalid")
    try:
        profiles = enabled_profiles(load_profile_dir(profile_dir), env)
    except (GenerationError, OSError, ValueError):
        raise MediaJobsUnavailable("media_jobs_profiles_invalid") from None
    if not profiles:
        raise MediaJobsUnavailable("media_jobs_no_enabled_profiles")
    try:
        store = ImageJobStore(job_db, volume_guard=lambda: work.require(job_dir))
    except ArtifactSinkUnavailable:
        raise MediaJobsUnavailable("media_jobs_work_area_unavailable") from None
    except (ImageJobError, OSError, ValueError, sqlite3.DatabaseError):
        raise MediaJobsUnavailable("media_jobs_store_invalid") from None
    return MediaJobService(store, profiles, secret, video_enabled=env.get(VIDEO_ENV) == "1")


def cached_service(factory: Callable[[], MediaJobService] = service_from_env) -> Callable[[], MediaJobService]:
    """Build the service on first use and keep it; a failed build is retried on the next request,
    so a work area fixed after the worker started is picked up without a restart."""
    built: list[MediaJobService] = []

    def get() -> MediaJobService:
        if not built:
            built.append(factory())
        return built[0]
    return get
