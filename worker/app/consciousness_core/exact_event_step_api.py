"""C22-C exact-event profile-backed one-shot cognition surface.

This private route accepts exactly one pending CognitionEvent id and no other
cognitive input. The event must be present and selected by the canonical
supervisor plan before ThoughtEngine invocation is possible.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..netguard import is_loopback
from .cycle import cognitive_profile_ref, self_state_ref, workspace_ref, world_state_ref
from .policy_checkpoint import (
    PolicyDrivenCheckpointResult,
    PolicyDrivenSelfStateCheckpointAdapter,
)
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


EVENT_STEP_FLAG = "KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED"
EVENT_CHECKPOINT_FLAG = "KALIV_CONSCIOUSNESS_EVENT_CHECKPOINT_ENABLED"
EVENT_STEP_PREFIX = "/experimental/consciousness"
MAX_EVENT_STEP_BODY_BYTES = 1024
_MOUNTED_STATE = "consciousness_exact_event_step_mounted"

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


class ExactEventStepBody(StrictModel):
    required_event_id: EventId


class ExactEventStepReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/exact-event-step-receipt/v1"]
    required_event_id: EventId
    decision: Literal["WAIT", "RUN"]
    selected_event_ids: Annotated[list[EventId], Field(max_length=16)]
    required_event_selected: bool
    thought_engine_invoked: bool
    model_calls: Annotated[int, Field(ge=0, le=1, strict=True)]
    profile_ref: NonEmptyRef
    profile_id: Annotated[str, Field(pattern=r"^cog-[a-f0-9]{32}$")]
    profile_config_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    self_state_ref: NonEmptyRef
    world_state_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    transition_receipt_ref: NonEmptyRef | None
    completed_cycles: Annotated[int, Field(ge=0, strict=True)]
    context_updated: bool
    automatic_repeat: Literal[False]
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    checkpoint_enabled: bool = False
    checkpoint_evaluation_count: Annotated[
        int,
        Field(ge=0, le=2, strict=True),
    ] = 0
    checkpoint_commit_count: Annotated[
        int,
        Field(ge=0, le=2, strict=True),
    ] = 0
    checkpoint_last_outcome: (
        Literal["IDLE", "HOLD", "COMMITTED"] | None
    ) = None
    checkpoint_last_pressure: (
        Literal["IDLE", "HOLD", "CHECKPOINT", "REQUIRED"] | None
    ) = None
    self_state_store_write_applied: bool = False
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "ExactEventStepReceipt":
        if self.decision == "WAIT":
            if self.required_event_selected:
                raise ValueError("WAIT cannot report required event selected")
            if self.selected_event_ids:
                raise ValueError("WAIT cannot expose selected events")
            if self.thought_engine_invoked or self.model_calls != 0:
                raise ValueError("WAIT cannot report a model call")
            if self.context_updated or self.transition_receipt_ref is not None:
                raise ValueError("WAIT cannot report a context transition")
        else:
            if not self.required_event_selected:
                raise ValueError("RUN must select the required event")
            if self.required_event_id not in self.selected_event_ids:
                raise ValueError("RUN selection does not contain required event")
            if not self.thought_engine_invoked or self.model_calls != 1:
                raise ValueError("RUN must report exactly one ThoughtEngine call")
            if not self.context_updated or self.transition_receipt_ref is None:
                raise ValueError("RUN must report one context transition")

        if not self.checkpoint_enabled:
            if (
                self.checkpoint_evaluation_count != 0
                or self.checkpoint_commit_count != 0
                or self.checkpoint_last_outcome is not None
                or self.checkpoint_last_pressure is not None
                or self.self_state_store_write_applied
            ):
                raise ValueError(
                    "checkpoint-disabled receipt cannot claim checkpoint work"
                )
        else:
            if self.checkpoint_evaluation_count < 1:
                raise ValueError(
                    "checkpoint-enabled receipt requires one evaluation"
                )
            if (
                self.checkpoint_last_outcome is None
                or self.checkpoint_last_pressure is None
            ):
                raise ValueError(
                    "checkpoint-enabled receipt requires bounded outcome metadata"
                )
            if self.checkpoint_commit_count > self.checkpoint_evaluation_count:
                raise ValueError(
                    "checkpoint commit count exceeds evaluation count"
                )
            if self.self_state_store_write_applied != (
                self.checkpoint_commit_count > 0
            ):
                raise ValueError(
                    "checkpoint write flag/count mismatch"
                )
        return self


def exact_event_step_enabled(env: dict[str, str] | None = None) -> bool:
    if env is None:
        return os.getenv("KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED", "0") == "1"
    return env.get(EVENT_STEP_FLAG, "0") == "1"


def exact_event_checkpoint_enabled(
    env: dict[str, str] | None = None,
) -> bool:
    if env is None:
        return (\n            os.getenv(\n                "KALIV_CONSCIOUSNESS_EVENT_CHECKPOINT_ENABLED",\n                "0",\n            )\n            == "1"\n        )
    return env.get(EVENT_CHECKPOINT_FLAG, "0") == "1"


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
            detail="Consciousness exact-event step is loopback-only",
        )


def _invalid_body() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="invalid consciousness exact-event step request",
    )


async def _read_body(request: Request) -> ExactEventStepBody:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except (TypeError, ValueError):
            raise _invalid_body() from None
        if size <= 0 or size > MAX_EVENT_STEP_BODY_BYTES:
            raise _invalid_body()

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_EVENT_STEP_BODY_BYTES:
                raise _invalid_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_body() from None

    if not raw:
        raise _invalid_body()
    try:
        return ExactEventStepBody.model_validate_json(bytes(raw))
    except ValidationError:
        raise _invalid_body() from None


def build_consciousness_exact_event_step_router(
    *,
    profile_loader: ProfileLoader = load_cognitive_profile,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not callable(profile_loader):
        raise TypeError("profile_loader must be callable")
    if not callable(loopback_allowed):
        raise TypeError("loopback_allowed must be callable")

    router = APIRouter(
        prefix=EVENT_STEP_PREFIX,
        tags=["experimental-consciousness"],
    )

    @router.post("/step-event")
    async def exact_event_step(request: Request) -> dict[str, Any]:
        _require_loopback(request, loopback_allowed)
        body = await _read_body(request)

        session = getattr(request.app.state, "consciousness_session", None)
        if not isinstance(session, ProductionCognitiveSession):
            raise HTTPException(
                status_code=503,
                detail="consciousness session unavailable",
            )

        checkpoint_service = None
        checkpoint_results: list[PolicyDrivenCheckpointResult] = []
        if exact_event_checkpoint_enabled():
            checkpoint_service = getattr(
                request.app.state,
                "consciousness_policy_checkpoint",
                None,
            )
            if not isinstance(
                checkpoint_service,
                PolicyDrivenSelfStateCheckpointAdapter,
            ):
                raise HTTPException(
                    status_code=503,
                    detail="consciousness checkpoint service unavailable",
                )
            try:
                checkpoint_before = (
                    checkpoint_service.maybe_checkpoint_once()
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail="consciousness checkpoint preflight failed",
                ) from exc
            if not isinstance(
                checkpoint_before,
                PolicyDrivenCheckpointResult,
            ):
                raise HTTPException(
                    status_code=503,
                    detail="consciousness checkpoint preflight failed",
                )
            checkpoint_results.append(checkpoint_before)

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
            result = await session.step(
                profile=loaded.profile,
                required_event_id=body.required_event_id,
            )
        except (SupervisorLifecycleError, CognitiveSessionLifecycleError) as exc:
            raise HTTPException(
                status_code=409,
                detail="required cognition event is not runnable",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="consciousness cognition step failed",
            ) from exc

        plan = result.supervisor_step.plan
        if plan.decision not in {"WAIT", "RUN"}:
            # required_event_id preflight guarantees the event is pending, so
            # IDLE here would be internally inconsistent.
            raise HTTPException(
                status_code=409,
                detail="required cognition event is not runnable",
            )

        if (
            checkpoint_service is not None
            and result.context_updated
        ):
            try:
                checkpoint_after = (
                    checkpoint_service.maybe_checkpoint_once()
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "consciousness cognition completed but "
                        "checkpoint failed"
                    ),
                ) from exc
            if not isinstance(
                checkpoint_after,
                PolicyDrivenCheckpointResult,
            ):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "consciousness cognition completed but "
                        "checkpoint failed"
                    ),
                )
            checkpoint_results.append(checkpoint_after)

        checkpoint_last = (
            checkpoint_results[-1]
            if checkpoint_results
            else None
        )
        checkpoint_commits = sum(
            1
            for item in checkpoint_results
            if item.outcome == "COMMITTED"
        )

        live = result.live_state
        receipt = ExactEventStepReceipt(
            schema="kaliv-consciousness-core/exact-event-step-receipt/v1",
            required_event_id=body.required_event_id,
            decision=plan.decision,
            selected_event_ids=plan.selected_event_ids,
            required_event_selected=(
                body.required_event_id in plan.selected_event_ids
            ),
            thought_engine_invoked=result.supervisor_step.thought_engine_invoked,
            model_calls=1 if result.supervisor_step.thought_engine_invoked else 0,
            profile_ref=cognitive_profile_ref(loaded.profile),
            profile_id=loaded.profile.profile_id,
            profile_config_sha256=loaded.receipt.config_sha256,
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
            checkpoint_enabled=checkpoint_service is not None,
            checkpoint_evaluation_count=len(checkpoint_results),
            checkpoint_commit_count=checkpoint_commits,
            checkpoint_last_outcome=(
                None
                if checkpoint_last is None
                else checkpoint_last.outcome
            ),
            checkpoint_last_pressure=(
                None
                if checkpoint_last is None
                else checkpoint_last.pressure.decision
            ),
            self_state_store_write_applied=checkpoint_commits > 0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_exact_event_step(
    app: FastAPI,
    *,
    profile_loader: ProfileLoader | None = None,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    if not exact_event_step_enabled():
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
        app.include_router(build_consciousness_exact_event_step_router(**kwargs))
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
