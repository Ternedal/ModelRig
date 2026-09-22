"""C22-B explicit loopback-only single cognitive step surface.

The route has no request payload. It cannot inject cognitive state, events or a
model profile. It only asks the already-live C19-B session to evaluate at most
one supervisor step using the current C22-A operator calibration.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..netguard import is_loopback
from .profile_source import (
    CognitiveProfileSourceError,
    load_cognitive_profile,
)
from .session_lifecycle import (
    CognitiveSessionLifecycleError,
    ProductionCognitiveSession,
)
from .supervisor_lifecycle import SupervisorLifecycleError
from .thought_engine import ThoughtEngineContractError


CONSCIOUSNESS_STEP_FLAG = "KALIV_CONSCIOUSNESS_STEP_ENABLED"
CONSCIOUSNESS_STEP_PREFIX = "/experimental/consciousness"
_MOUNTED_STATE = "consciousness_step_mounted"

LoopbackPolicy = Callable[[Request], bool]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class CognitiveStepReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/explicit-step-receipt/v1"]
    decision: Literal["RUN", "WAIT", "IDLE"]
    selected_event_ids: Annotated[list[str], Field(max_length=16)]
    wait_remaining_ms: Annotated[int | None, Field(ge=0, strict=True)]
    thought_engine_invoked: bool
    thought_engine_calls: Literal[0, 1]
    profile_ref: NonEmptyRef
    profile_id: Annotated[str, Field(pattern=r"^cog-[a-f0-9]{32}$")]
    profile_config_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    self_revision_before: Annotated[int, Field(ge=1, strict=True)]
    self_revision_after: Annotated[int, Field(ge=1, strict=True)]
    completed_cycles_before: Annotated[int, Field(ge=0, strict=True)]
    completed_cycles_after: Annotated[int, Field(ge=0, strict=True)]
    context_updated: bool
    transition_receipt_ref: NonEmptyRef | None
    model_output_exposed: Literal[False]
    raw_chain_of_thought_exposed: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    automatic_repeat: Literal[False]
    production_activation: Literal[False]


def consciousness_step_enabled() -> bool:
    """Only exact string 1 enables the explicit model-step surface."""
    return os.getenv("KALIV_CONSCIOUSNESS_STEP_ENABLED", "0") == "1"


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
            detail="Consciousness cognitive step is loopback-only",
        )


async def _require_empty_body(request: Request) -> None:
    """Reject every payload after loopback admission, before any step/profile load."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="consciousness step request must have an empty body",
            ) from None
        if declared != 0:
            raise HTTPException(
                status_code=422,
                detail="consciousness step request must have an empty body",
            )

    try:
        async for chunk in request.stream():
            if chunk:
                raise HTTPException(
                    status_code=422,
                    detail="consciousness step request must have an empty body",
                )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=422,
            detail="consciousness step request must have an empty body",
        ) from None


def build_consciousness_step_router(
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
    profile_loader=load_cognitive_profile,
) -> APIRouter:
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")
    if not callable(profile_loader):
        raise TypeError("profile loader must be callable")

    router = APIRouter(
        prefix=CONSCIOUSNESS_STEP_PREFIX,
        tags=["experimental-consciousness"],
    )

    @router.post("/step")
    async def explicit_step(request: Request) -> dict[str, object]:
        # Remote callers are rejected before the private boundary reads even one
        # request-body byte or touches profile/session state.
        _require_loopback(request, loopback_allowed)
        await _require_empty_body(request)

        session = getattr(request.app.state, "consciousness_session", None)
        if not isinstance(session, ProductionCognitiveSession):
            raise HTTPException(
                status_code=503,
                detail="consciousness session unavailable",
            )

        try:
            loaded = profile_loader()
        except CognitiveProfileSourceError as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile invalid",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            ) from exc

        if loaded is None:
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            )

        before = session.live_state
        try:
            result = await session.step(profile=loaded.profile)
        except (SupervisorLifecycleError, CognitiveSessionLifecycleError) as exc:
            raise HTTPException(
                status_code=409,
                detail="consciousness cognitive step already in progress or unavailable",
            ) from exc
        except ThoughtEngineContractError as exc:
            raise HTTPException(
                status_code=502,
                detail="consciousness thought engine returned an invalid proposal",
            ) from exc
        except Exception as exc:
            # Provider/network failures remain secondary and are never reflected
            # with internal exception text.
            raise HTTPException(
                status_code=502,
                detail="consciousness thought engine step failed",
            ) from exc

        after = result.live_state
        plan = result.supervisor_step.plan
        receipt = CognitiveStepReceipt(
            schema="kaliv-consciousness-core/explicit-step-receipt/v1",
            decision=plan.decision,
            selected_event_ids=plan.selected_event_ids,
            wait_remaining_ms=plan.wait_remaining_ms,
            thought_engine_invoked=result.supervisor_step.thought_engine_invoked,
            thought_engine_calls=(
                1 if result.supervisor_step.thought_engine_invoked else 0
            ),
            profile_ref=loaded.receipt.profile_ref,
            profile_id=loaded.profile.profile_id,
            profile_config_sha256=loaded.receipt.config_sha256,
            self_revision_before=before.state.revision,
            self_revision_after=after.state.revision,
            completed_cycles_before=before.completed_cycles,
            completed_cycles_after=after.completed_cycles,
            context_updated=result.context_updated,
            transition_receipt_ref=after.last_transition_receipt_ref,
            model_output_exposed=False,
            raw_chain_of_thought_exposed=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            automatic_repeat=False,
            production_activation=False,
        )
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_step(
    app: FastAPI,
    *,
    loopback_allowed: LoopbackPolicy | None = None,
    profile_loader=None,
) -> bool:
    """Mount only after the independent exact step opt-in."""
    if not consciousness_step_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    kwargs = {}
    if loopback_allowed is not None:
        if not callable(loopback_allowed):
            raise TypeError("loopback policy must be callable")
        kwargs["loopback_allowed"] = loopback_allowed
    if profile_loader is not None:
        if not callable(profile_loader):
            raise TypeError("profile loader must be callable")
        kwargs["profile_loader"] = profile_loader

    route_count = len(app.router.routes)
    try:
        app.include_router(build_consciousness_step_router(**kwargs))
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
