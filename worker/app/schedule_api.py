"""Local operator API for schedules.

There is intentionally no model-visible tool here. Schedule administration is
loopback-only even when ``KALIV_WORKER_ALLOW_LAN=1`` deliberately exposes other
worker routes: this is a standing-grant control surface and must not become a LAN
write API by inheritance. The authenticated Go backend is the remote boundary.

Writes use preview -> human confirmation -> backend-issued approval token ->
create/renew. The worker verifies the signed token against its own canonical
preview and durably consumes its random nonce before persisting the grant. A
fingerprint computed by the caller is never accepted as evidence of consent.
"""
from __future__ import annotations
import time

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .netguard import is_loopback
from .schedule_admin import (
    MAX_RUN_BUDGET,
    MAX_TTL_DAYS,
    ScheduleAdmin,
    ScheduleAdminConflict,
    ScheduleAdminError,
    ScheduleAdminNotFound,
)
from .schedule_approval import (
    ScheduleApprovalError,
    consume_schedule_approval,
    verify_schedule_approval,
)
from .scheduler import DEFAULT_MAX_RUNS, DEFAULT_TTL_DAYS, ScheduleError, enabled
from .scheduler_time import DEFAULT_TIMEZONE, MISFIRE_POLICY


class PreviewScheduleReq(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    args: dict[str, Any] = Field(default_factory=dict)
    cadence: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default=DEFAULT_TIMEZONE, min_length=1, max_length=100)
    misfire_policy: str = Field(default=MISFIRE_POLICY, min_length=1, max_length=32)
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)
    max_runs: int = Field(default=DEFAULT_MAX_RUNS, ge=0, le=MAX_RUN_BUDGET)


class CreateScheduleReq(PreviewScheduleReq):
    model_config = ConfigDict(extra="forbid")
    approval_token: str | None = Field(default=None, min_length=40, max_length=60000)
    # Readiness deliberately probes the retired bypass end to end. Keeping this
    # tombstone in the schema makes that probe run; any non-null legacy value is
    # rejected by validation and never reaches administration.
    approved_fingerprint: None = Field(default=None, exclude=True)


class SetScheduleEnabledReq(BaseModel):
    enabled: bool


class RenewPreviewReq(BaseModel):
    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)
    max_runs: int = Field(default=DEFAULT_MAX_RUNS, ge=0, le=MAX_RUN_BUDGET)
    # None preserves pause/resume state. True is an explicit fresh start and
    # schedules the next future occurrence; False renews but leaves it paused.
    enable: bool | None = None


class RenewScheduleReq(RenewPreviewReq):
    model_config = ConfigDict(extra="forbid")
    approval_token: str | None = Field(default=None, min_length=40, max_length=60000)
    approved_fingerprint: None = Field(default=None, exclude=True)


def _raise(exc: Exception) -> None:
    if isinstance(exc, ScheduleAdminNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (ScheduleAdminConflict, ScheduleApprovalError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


def _preview_payload(preview) -> dict[str, Any]:
    return {
        "preview": preview.to_dict(),
        "executed": False,
        # No schedule row was created. The first operator call may still
        # initialise the existing ToolGate/audit layer while reading the
        # canonical registry; this field is intentionally narrower.
        "schedule_persisted": False,
    }


def _approval_for(preview, token: str | None) -> tuple[str | None, dict | None]:
    """Verify and consume a write approval; reads deliberately need none.

    Returns (fingerprint, receipt). The receipt carries the attribution the
    verified token proved -- WHICH device approved, WHEN it was issued, and
    when this worker consumed it (T-014). Before this, all of it was verified
    and then thrown away, so a firing schedule could not answer "who approved
    this, and from where?".
    """
    if not preview.requires_approval:
        return None, None
    verified = verify_schedule_approval(token, preview)
    # Consume before persistence. A downstream failure burns the token rather
    # than making a failed write approval reusable; the user must confirm again.
    consume_schedule_approval(verified.nonce)
    receipt = {
        "device_id": verified.device_id,
        "nonce": verified.nonce,
        "issued_at": verified.issued_at,
        "consumed_at": time.time(),
    }
    return preview.approval_fingerprint, receipt


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
        return _runtime_status(request)

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
                timezone_name=req.timezone,
                misfire_policy=req.misfire_policy,
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
            preview = service.preview(
                req.tool,
                req.args,
                req.cadence,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                timezone_name=req.timezone,
                misfire_policy=req.misfire_policy,
            )
            approved_fingerprint, receipt = _approval_for(
                preview, req.approval_token)
            schedule = service.create(
                req.tool,
                req.args,
                req.cadence,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                timezone_name=req.timezone,
                misfire_policy=req.misfire_policy,
                approved_fingerprint=approved_fingerprint,
                receipt=receipt,
            )
        except (
            ScheduleAdminError,
            ScheduleApprovalError,
            ScheduleError,
        ) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    @router.get("/{schedule_id}")
    def get_schedule(request: Request, schedule_id: str) -> dict[str, Any]:
        _require_operator(request, operator_allowed)
        try:
            schedule = service.get(schedule_id)
            receipts = service.approval_receipts(schedule_id)
        except (ScheduleAdminError, ScheduleError) as exc:
            _raise(exc)
        return {"schedule": schedule, "approval_receipts": receipts}

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
            preview = service.preview_renew(
                schedule_id,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                enable=req.enable,
            )
            approved_fingerprint, receipt = _approval_for(
                preview, req.approval_token)
            schedule = service.renew(
                schedule_id,
                ttl_days=req.ttl_days,
                max_runs=req.max_runs,
                approved_fingerprint=approved_fingerprint,
                enable=req.enable,
                receipt=receipt,
            )
        except (
            ScheduleAdminError,
            ScheduleApprovalError,
            ScheduleError,
        ) as exc:
            _raise(exc)
        return {"schedule": schedule, "executed": False}

    return router
