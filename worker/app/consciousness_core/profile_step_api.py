"""C22-B profile-backed private one-shot cognitive session step.

The route is separately default-off and loopback-only. It accepts an empty body
and no caller-selected prompt, model, profile, state, event, memory, tool or
authority input. Each admitted request loads the current local C22-A
CognitiveProfile and calls the existing live C19-B session exactly once.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..netguard import is_loopback
from .cycle import cognitive_profile_ref, self_state_ref, workspace_ref, world_state_ref
from .profile_source import (
    CognitiveProfileLoadResult,
    CognitiveProfileSourceError,
    load_cognitive_profile,
)
from .session_lifecycle import (
    CognitiveSessionLifecycleError,
    ProductionCognitiveSession,
)
from .supervisor_lifecycle import SupervisorLifecycleError


CONSCIOUSNESS_STEP_FLAG = "KALIV_CONSCIOUSNESS_STEP_ENABLED"
COGNITION_STEP_PREFIX = "/experimental/consciousness"
_MOUNTED_STATE = "consciousness_profile_step_mounted"

ProfileLoader = Callable[[], CognitiveProfileLoadResult | None]
LoopbackPolicy = Callable[[Request], bool]
EventId = Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ProfileBackedStepReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/profile-backed-step-receipt/v1"]
    decision: Literal["IDLE", "WAIT", "RUN"]
    selected_event_ids: Annotated[list[EventId], Field(max_length=16)]
    thought_engine_invoked: bool
    model_calls: Annotated[int, Field(ge=0, le=1, strict=True)]
    profile_ref: NonEmptyRef
    profile_id: Annotated[str, Field(pattern=r"^cog-[a-f0-9]{32}$")]
    profile_config_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    profile_calibration_refs: Annotated[
        list[NonEmptyRef],
        Field(min_length=1, max_length=32),
    ]
    self_state_ref: NonEmptyRef
    world_state_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    transition_receipt_ref: NonEmptyRef | None
    completed_cycles: Annotated[int, Field(ge=0, strict=True)]
    context_updated: bool
    automatic_repeat: Literal[False]
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_step_shape(self) -> "ProfileBackedStepReceipt":
        if self.decision == "RUN":
            if not self.thought_engine_invoked or self.model_calls != 1:
                raise ValueError("RUN must report exactly one ThoughtEngine call")
            if not self.context_updated or self.transition_receipt_ref is None:
                raise ValueError("RUN must report one live context transition")
            if not self.selected_event_ids:
                raise ValueError("RUN must be bound to selected events")
        else:
            if self.thought_engine_invoked or self.model_calls != 0:
                raise ValueError("IDLE/WAIT cannot report a ThoughtEngine call")
            if self.context_updated or self.transition_receipt_ref is not None:
                raise ValueError("IDLE/WAIT cannot report a context transition")
            if self.selected_event_ids:
                raise ValueError("IDLE/WAIT cannot report selected events")
        return self


def profile_step_enabled(env: dict[str, str] | None = None) -> bool:
    if env is None:
        return os.getenv("KALIV_CONSCIOUSNESS_STEP_ENABLED", "0") == "1"
    return env.get(CONSCIOUSNESS_STEP_FLAG, "0") == "1"


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


async def _require_empty_body(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="consciousness cognition step requires an empty body",
            ) from None
        if size != 0:
            raise HTTPException(
                status_code=422,
                detail="consciousness cognition step requires an empty body",
            )

    try:
        async for chunk in request.stream():
            if chunk:
                raise HTTPException(
                    status_code=422,
                    detail="consciousness cognition step requires an empty body",
                )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=422,
            detail="consciousness cognition step requires an empty body",
        ) from None


def _load_receipt_ref(result: CognitiveProfileLoadResult) -> str:
    payload = result.receipt.model_dump(mode="json")
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "cognitive-profile-load:" + hashlib.sha256(raw).hexdigest()


def build_consciousness_profile_step_router(
    *,
    profile_loader: ProfileLoader = load_cognitive_profile,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not callable(profile_loader):
        raise TypeError("profile_loader must be callable")
    if not callable(loopback_allowed):
        raise TypeError("loopback_allowed must be callable")

    router = APIRouter(
        prefix=COGNITION_STEP_PREFIX,
        tags=["experimental-consciousness"],
    )

    @router.post("/step")
    async def cognition_step(request: Request) -> dict[str, Any]:
        # Network boundary is checked before body consumption or local config IO.
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
                detail="consciousness cognitive profile unavailable",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            ) from exc

        if loaded is None or not isinstance(loaded, CognitiveProfileLoadResult):
            raise HTTPException(
                status_code=503,
                detail="consciousness cognitive profile unavailable",
            )

        try:
            result = await session.step(profile=loaded.profile)
        except (SupervisorLifecycleError, CognitiveSessionLifecycleError) as exc:
            raise HTTPException(
                status_code=409,
                detail="consciousness cognitive session is not runnable",
            ) from exc
        except Exception as exc:
            # Provider prompts, outputs and error text remain private.
            raise HTTPException(
                status_code=502,
                detail="consciousness cognition step failed",
            ) from exc

        plan = result.supervisor_step.plan
        live = result.live_state
        receipt = ProfileBackedStepReceipt(
            schema="kaliv-consciousness-core/profile-backed-step-receipt/v1",
            decision=plan.decision,
            selected_event_ids=plan.selected_event_ids,
            thought_engine_invoked=result.supervisor_step.thought_engine_invoked,
            model_calls=1 if result.supervisor_step.thought_engine_invoked else 0,
            profile_ref=cognitive_profile_ref(loaded.profile),
            profile_id=loaded.profile.profile_id,
            profile_config_sha256=loaded.receipt.config_sha256,
            profile_calibration_refs=loaded.receipt.calibration_refs,
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
            internal_thread_created=False,
            internal_timer_created=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
        # The load receipt itself is deliberately not returned. This call exists
        # only to make it explicit that the profile configuration has an auditable
        # canonical receipt even though the HTTP surface remains minimal.
        _load_receipt_ref(loaded)
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_profile_step(
    app: FastAPI,
    *,
    profile_loader: ProfileLoader | None = None,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    """Mount C22-B only after its own exact opt-in."""
    if not profile_step_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    kwargs: dict[str, Any] = {}
    if profile_loader is not None:
        if not callable(profile_loader):
            raise TypeError("profile_loader must be callable")
        kwargs["profile_loader"] = profile_loader
    if loopback_allowed is not None:
        if not callable(loopback_allowed):
            raise TypeError("loopback_allowed must be callable")
        kwargs["loopback_allowed"] = loopback_allowed

    route_count = len(app.router.routes)
    try:
        app.include_router(build_consciousness_profile_step_router(**kwargs))
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
