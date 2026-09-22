"""C22-C private required-event one-shot cognition HTTP surface.

This surface is independently default-off and loopback-only. It accepts no
prompt, model, profile, state, memory, tool or action input from the caller.
The only caller-selected value is the exact pending CognitionEvent id. The
production CognitiveProfile is resolved locally through C22-B.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..netguard import is_loopback
from .cycle import cognitive_profile_ref, self_state_ref, workspace_ref, world_state_ref
from .production_profile import (
    ProductionCognitiveProfileError,
    ProductionCognitiveProfileResolution,
    resolve_production_cognitive_profile,
)
from .session_lifecycle import (
    CognitiveSessionLifecycleError,
    ProductionCognitiveSession,
)
from .supervisor_lifecycle import SupervisorLifecycleError


TURN_COGNITION_FLAG = "KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED"
COGNITION_STEP_PREFIX = "/experimental/consciousness"
MAX_COGNITION_STEP_BODY_BYTES = 4 * 1024
_MOUNTED_STATE = "consciousness_cognition_step_mounted"

ProfileResolver = Callable[[], ProductionCognitiveProfileResolution | None]
LoopbackPolicy = Callable[[Request], bool]
EventId = Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CognitionStepBody(StrictModel):
    required_event_id: EventId


class CognitionStepReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/cognition-step-receipt/v1"]
    required_event_id: EventId
    decision: Literal["WAIT", "RUN"]
    selected_event_ids: Annotated[list[EventId], Field(max_length=16)]
    thought_engine_invoked: bool
    model_calls: Annotated[int, Field(ge=0, le=1, strict=True)]
    profile_ref: str = Field(min_length=1, max_length=256)
    profile_config_ref: str = Field(min_length=1, max_length=256)
    self_state_ref: str = Field(min_length=1, max_length=256)
    world_state_ref: str = Field(min_length=1, max_length=256)
    workspace_ref: str = Field(min_length=1, max_length=256)
    transition_receipt_ref: str | None = Field(default=None, max_length=256)
    completed_cycles: Annotated[int, Field(ge=0, strict=True)]
    context_updated: bool
    automatic_repeat: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def turn_cognition_enabled() -> bool:
    return (
        os.getenv("KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED", "0")
        == "1"
    )


def _loopback_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_loopback(request: Request, allowed: LoopbackPolicy) -> None:
    try:
        admitted = bool(allowed(request))
    except Exception:
        admitted = False
    if not admitted:
        raise HTTPException(
            status_code=403,
            detail="Consciousness cognition step is loopback-only",
        )


def _invalid_step_body() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="invalid consciousness cognition-step request",
    )


async def _read_step_body(request: Request) -> CognitionStepBody:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_step_body() from None
        if declared < 0 or declared > MAX_COGNITION_STEP_BODY_BYTES:
            raise _invalid_step_body()

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_COGNITION_STEP_BODY_BYTES:
                raise _invalid_step_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_step_body() from None

    if not raw:
        raise _invalid_step_body()
    try:
        return CognitionStepBody.model_validate_json(bytes(raw))
    except ValidationError:
        raise _invalid_step_body() from None


def build_consciousness_cognition_step_router(
    *,
    profile_resolver: ProfileResolver = resolve_production_cognitive_profile,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not callable(profile_resolver):
        raise TypeError("profile_resolver must be callable")
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(
        prefix=COGNITION_STEP_PREFIX,
        tags=["experimental-consciousness"],
    )

    @router.post("/step")
    async def cognition_step(request: Request) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        body = await _read_step_body(request)

        session = getattr(request.app.state, "consciousness_session", None)
        if not isinstance(session, ProductionCognitiveSession):
            raise HTTPException(
                status_code=503,
                detail="consciousness session unavailable",
            )

        try:
            resolution = profile_resolver()
        except ProductionCognitiveProfileError as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            ) from exc
        if resolution is None:
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            )
        if not isinstance(resolution, ProductionCognitiveProfileResolution):
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            )

        try:
            result = await session.step(
                profile=resolution.profile,
                required_event_id=body.required_event_id,
            )
        except (SupervisorLifecycleError, CognitiveSessionLifecycleError) as exc:
            raise HTTPException(
                status_code=409,
                detail="required cognition event is not runnable",
            ) from exc
        except Exception as exc:
            # ThoughtEngine/provider details, prompts and raw output never cross
            # this private control surface.
            raise HTTPException(
                status_code=502,
                detail="consciousness cognition step failed",
            ) from exc

        plan = result.supervisor_step.plan
        if plan.decision not in ("WAIT", "RUN"):
            raise HTTPException(
                status_code=409,
                detail="required cognition event is not runnable",
            )

        live = result.live_state
        receipt = CognitionStepReceipt(
            schema="kaliv-consciousness-core/cognition-step-receipt/v1",
            required_event_id=body.required_event_id,
            decision=plan.decision,
            selected_event_ids=plan.selected_event_ids,
            thought_engine_invoked=result.supervisor_step.thought_engine_invoked,
            model_calls=(
                1 if result.supervisor_step.thought_engine_invoked else 0
            ),
            profile_ref=cognitive_profile_ref(resolution.profile),
            profile_config_ref=resolution.receipt.config_ref,
            self_state_ref=self_state_ref(live.state),
            world_state_ref=world_state_ref(live.world),
            workspace_ref=workspace_ref(live.workspace),
            transition_receipt_ref=(
                live.last_transition_receipt_ref
                if result.context_updated
                else None
            ),
            completed_cycles=live.completed_cycles,
            context_updated=result.context_updated,
            automatic_repeat=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_cognition_step(
    app: FastAPI,
    *,
    profile_resolver: ProfileResolver | None = None,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    """Mount C22-C only after its own exact opt-in."""
    if not turn_cognition_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    kwargs = {}
    if profile_resolver is not None:
        if not callable(profile_resolver):
            raise TypeError("profile_resolver must be callable")
        kwargs["profile_resolver"] = profile_resolver
    if loopback_allowed is not None:
        if not callable(loopback_allowed):
            raise TypeError("loopback policy must be callable")
        kwargs["loopback_allowed"] = loopback_allowed

    route_count = len(app.router.routes)
    try:
        app.include_router(build_consciousness_cognition_step_router(**kwargs))
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
