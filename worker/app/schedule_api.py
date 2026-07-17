"""Local operator API for schedules.

There is intentionally no model-visible tool here. Schedule administration is
loopback-only even when ``KALIV_WORKER_ALLOW_LAN=1`` deliberately exposes other
worker routes: this is an unauthenticated control surface and must not become a
LAN write API by inheritance. A backend/client may later expose a human UI
through its authenticated boundary.

Writes use preview -> authenticated backend approval -> signed single-use token ->
create/renew; no endpoint accepts changed arguments or standing-grant terms under
an old approval token.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .netguard import is_loopback
from .schedule_admin import (
    MAX_RUN_BUDGET,
    MAX_TTL_DAYS,
    ScheduleAdmin,
    ScheduleAdminConflict,
    ScheduleAdminError,
    ScheduleAdminNotFound,
    ScheduleAdminUnavailable,
)
from .scheduler import DEFAULT_MAX_RUNS, DEFAULT_TTL_DAYS, ScheduleError, enabled


class PreviewScheduleReq(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    args: dict[str, Any] = Field(default_factory=dict)
    cadence: str = Field(min_length=1, max_length=100)
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)
    max_runs: int = Field(default=DEFAULT_MAX_RUNS, ge=0, le=MAX_RUN_BUDGET)


class CreateScheduleReq(PreviewScheduleReq):
    approval_token: str | None = Field(default=None, min_length=32, max_length=4096)


class SetScheduleEnabledReq(BaseModel):
    enabled: bool


class RenewPreviewReq(BaseModel):
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)
    max_runs: int = Field(default=DEFAULT_MAX_RUNS, ge=0, le=MAX_RUN_BUDGET)
    # None preserves pause/resume state. True is an explicit fresh start and
    # schedules the next future occurrence; False renews but leaves it paused.
    enable: bool | None = None


class RenewScheduleReq(RenewPreviewReq):
    approval_token: str | None = Field(default=None, min_length=32, max_length=4096)


def _raise(exc: Exception) -> None:
    if isinstance(exc, ScheduleAdminNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ScheduleAdminConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ScheduleAdminUnavailable):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, (ScheduleAdminError, ScheduleError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def _loopback_operator_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    # Starlette's in-process TestClient uses this synthetic scope value. A real
    # socket peer cannot choose it through headers, so admitting it weakens no
    # production boundary and lets the full API contract run in CI.
    return host == "testclient" or is_loopback(host)


def _require_operator(
    request: Request, allowed: Callable[[Request], bool]
) -> None:
    try:
        ok = bool(allowed(request))
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(
            status_code=403,
            detail=(
                "schedule administration is loopback-only, even when "
                "KALIV_WORKER_ALLOW_LAN=1"
            ),
        )


def _runtime_status(request: Request, service: ScheduleAdmin) -> dict[str, Any]:
    runtime = getattr(request.app.state, "scheduler_runtime", None)
    if runtime is None:
        return {
            "configured": enabled(),
            "running": False,
            "resources_open": False,
            "approval_verifier_configured": service.approval_verifier_configured(),
            "last_error": None,
        }
    try:
        state = runtime.status()
    except Exception as exc:
        return {
            "configured": enabled(),
            "running": False,
            "resources_open": True,
            "approval_verifier_configured": service.approval_verifier_configured(),
            "last_error": f"{type(exc).__name__}: {exc}"[:500],
        }
    return {
        "configured": bool(state.configured),
        "running": bool(state.running),
        "resources_open": bool(state.resources_open),
        "approval_verifier_configured": service.approval_verifier_configured(),
        "last_error": state.last_error,
    }


def _preview_payload(preview) -> dict[str, Any]:
    return {
        "preview": preview.to_dict(),
        "executed": False,
        # No schedule row was created. The first operator call may still
        # initialise the existing ToolGate/audit layer while reading the
        # canonical registry; this field is intentionally narrower.
        "schedule_persisted": False,
    }


def build_schedule_router(
    admin: ScheduleAdmin | None = None,
    *,
    operator_allowed: Callable[[Request], bool] = _loopback_operator_allowed,
) -> APIRouter:
    """Build an inert router; resource access starts only after local admission."""
    router = APIRouter(prefix="/schedules", tags=["schedules"])
    service = admin or ScheduleAdmin()

    # Static routes must be registered before /{schedule_id}.
    @router.get("/status")
    def schedule_status(request: Request) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        # Status does not open the schedule DB or import ToolGate.
        return _runtime_status(request, service)

    @router.post("/preview")
    def preview_schedule(
        request: Request, req: PreviewScheduleReq
    ) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
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
        return _preview_payload(preview)

    @router.get("")
    def list_schedules(request: Request) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        try:
            schedules = service.list_all()
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedules": schedules}

    @router.post("")
    def create_schedule(
        request: Request, req: CreateScheduleReq
    ) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        try:
            schedule = service.create(
                req.tool,
                req.args,
                req.cadence,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                approval_token=req.approval_token,
            )
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    @router.get("/{schedule_id}")
    def get_schedule(request: Request, schedule_id: str) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        try:
            schedule = service.get(schedule_id)
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule}

    @router.post("/{schedule_id}/enabled")
    def set_schedule_enabled(
        request: Request, schedule_id: str, req: SetScheduleEnabledReq
    ) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        try:
            schedule = service.set_enabled(schedule_id, req.enabled)
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    @router.post("/{schedule_id}/renew/preview")
    def preview_schedule_renewal(
        request: Request, schedule_id: str, req: RenewPreviewReq
    ) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        try:
            preview = service.preview_renew(
                schedule_id,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                enable=req.enable,
            )
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return _preview_payload(preview)

    @router.post("/{schedule_id}/renew")
    def renew_schedule(
        request: Request, schedule_id: str, req: RenewScheduleReq
    ) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        try:
            schedule = service.renew(
                schedule_id,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                approval_token=req.approval_token,
                enable=req.enable,
            )
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    return router
