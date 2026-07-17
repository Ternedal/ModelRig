"""Local operator API for schedules.

There is intentionally no model-visible tool here.  The production worker is
loopback-only by default, and the backend/client may later choose to expose a
human UI for these routes.  Writes use preview -> matching fingerprint ->
create/renew; no endpoint accepts changed arguments under an old approval.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .schedule_admin import (
    MAX_RUN_BUDGET,
    MAX_TTL_DAYS,
    ScheduleAdmin,
    ScheduleAdminConflict,
    ScheduleAdminError,
    ScheduleAdminNotFound,
)
from .scheduler import DEFAULT_MAX_RUNS, DEFAULT_TTL_DAYS, ScheduleError, enabled


class PreviewScheduleReq(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    args: dict[str, Any] = Field(default_factory=dict)
    cadence: str = Field(min_length=1, max_length=100)
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)
    max_runs: int = Field(default=DEFAULT_MAX_RUNS, ge=0, le=MAX_RUN_BUDGET)


class CreateScheduleReq(PreviewScheduleReq):
    approved_fingerprint: str | None = Field(
        default=None, pattern="^[0-9a-f]{32}$"
    )


class SetScheduleEnabledReq(BaseModel):
    enabled: bool


class RenewScheduleReq(BaseModel):
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)
    max_runs: int = Field(default=DEFAULT_MAX_RUNS, ge=0, le=MAX_RUN_BUDGET)
    approved_fingerprint: str | None = Field(
        default=None, pattern="^[0-9a-f]{32}$"
    )
    # None preserves pause/resume state. True is an explicit fresh start and
    # schedules the next future occurrence; False renews but leaves it paused.
    enable: bool | None = None


def _raise(exc: Exception) -> None:
    if isinstance(exc, ScheduleAdminNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ScheduleAdminConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (ScheduleAdminError, ScheduleError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def _runtime_status(request: Request) -> dict[str, Any]:
    runtime = getattr(request.app.state, "scheduler_runtime", None)
    if runtime is None:
        return {
            "configured": enabled(),
            "running": False,
            "resources_open": False,
            "last_error": None,
        }
    try:
        state = runtime.status()
    except Exception as exc:
        return {
            "configured": enabled(),
            "running": False,
            "resources_open": True,
            "last_error": f"{type(exc).__name__}: {exc}"[:500],
        }
    return {
        "configured": bool(state.configured),
        "running": bool(state.running),
        "resources_open": bool(state.resources_open),
        "last_error": state.last_error,
    }


def build_schedule_router(admin: ScheduleAdmin | None = None) -> APIRouter:
    """Build a side-effect-free router; stores open only for explicit requests."""
    router = APIRouter(prefix="/schedules", tags=["schedules"])
    service = admin or ScheduleAdmin()

    # Static routes must be registered before /{schedule_id}.
    @router.get("/status")
    def schedule_status(request: Request) -> dict[str, Any]:
        # Status does not open the schedule DB or import ToolGate.
        return _runtime_status(request)

    @router.post("/preview")
    def preview_schedule(req: PreviewScheduleReq) -> dict[str, Any]:
        try:
            preview = service.preview(
                req.tool,
                req.args,
                req.cadence,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
            )
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"preview": preview.to_dict(), "executed": False, "persisted": False}

    @router.get("")
    def list_schedules() -> dict[str, Any]:
        try:
            schedules = service.list_all()
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedules": schedules}

    @router.post("")
    def create_schedule(req: CreateScheduleReq) -> dict[str, Any]:
        try:
            schedule = service.create(
                req.tool,
                req.args,
                req.cadence,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                approved_fingerprint=req.approved_fingerprint,
            )
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    @router.get("/{schedule_id}")
    def get_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            schedule = service.get(schedule_id)
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule}

    @router.post("/{schedule_id}/enabled")
    def set_schedule_enabled(
        schedule_id: str, req: SetScheduleEnabledReq
    ) -> dict[str, Any]:
        try:
            schedule = service.set_enabled(schedule_id, req.enabled)
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    @router.post("/{schedule_id}/renew")
    def renew_schedule(schedule_id: str, req: RenewScheduleReq) -> dict[str, Any]:
        try:
            schedule = service.renew(
                schedule_id,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                approved_fingerprint=req.approved_fingerprint,
                enable=req.enable,
            )
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    return router
