"""C21-A private reported user-turn admission surface.

This is the first reviewed runtime event-source adapter for Consciousness Core.
It is independently default-off and loopback-only. It never runs cognition; it
only admits one bounded authenticated user turn into the already-existing live
C19/C20 session as reported evidence plus pending user-turn attention.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from ..netguard import is_loopback
from .session_lifecycle import (
    CognitiveSessionLifecycleError,
    ProductionCognitiveSession,
)
from .supervisor import SupervisorContractError
from .world_reducer import WorldReducerError


CONSCIOUSNESS_CHAT_FLAG = "KALIV_CONSCIOUSNESS_CHAT_ENABLED"
CONSCIOUSNESS_TURN_PREFIX = "/experimental/consciousness"
MAX_USER_TURN_BODY_BYTES = 16 * 1024
_MOUNTED_STATE = "consciousness_user_turn_mounted"

LoopbackPolicy = Callable[[Request], bool]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class UserTurnAdmissionBody(StrictModel):
    turn_id: StrictStr = Field(min_length=1, max_length=128)
    user_text: StrictStr = Field(min_length=1, max_length=2048)
    source_ref: StrictStr = Field(min_length=1, max_length=256)


class UserTurnAdmissionReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/user-turn-admission/v1"]
    turn_ref: NonEmptyRef
    evidence_ref: NonEmptyRef
    cognition_event_id: str | None
    world_changed: bool
    replayed: bool
    cognition_event_queued: bool
    epistemic_status: Literal["reported"]
    confidence: Literal[1.0]
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def consciousness_chat_enabled() -> bool:
    """Only the exact string 1 enables normal-chat admission."""
    return os.getenv("KALIV_CONSCIOUSNESS_CHAT_ENABLED", "0") == "1"


def _turn_ref(turn_id: str) -> str:
    return "chat-turn:" + hashlib.sha256(turn_id.encode("utf-8")).hexdigest()


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
            detail="Consciousness user-turn admission is loopback-only",
        )


def _invalid_turn_body() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="invalid consciousness user-turn request",
    )


async def _read_turn_body(request: Request) -> UserTurnAdmissionBody:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_turn_body() from None
        if declared < 0 or declared > MAX_USER_TURN_BODY_BYTES:
            raise _invalid_turn_body()

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_USER_TURN_BODY_BYTES:
                raise _invalid_turn_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_turn_body() from None

    if not raw:
        raise _invalid_turn_body()

    try:
        body = UserTurnAdmissionBody.model_validate_json(bytes(raw))
    except ValidationError:
        # Never reflect rejected private chat input through a validation detail.
        raise _invalid_turn_body() from None

    if not body.turn_id.strip() or not body.user_text.strip() or not body.source_ref.strip():
        raise _invalid_turn_body()
    return body


def build_consciousness_user_turn_router(
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(
        prefix=CONSCIOUSNESS_TURN_PREFIX,
        tags=["experimental-consciousness"],
    )

    @router.post("/user-turn")
    async def admit_user_turn(request: Request) -> dict[str, object]:
        # Admission precedes parsing. A remote caller never makes this private
        # boundary inspect or deserialize user text.
        _require_loopback(request, loopback_allowed)
        body = await _read_turn_body(request)

        session = getattr(request.app.state, "consciousness_session", None)
        if not isinstance(session, ProductionCognitiveSession):
            raise HTTPException(
                status_code=503,
                detail="consciousness session unavailable",
            )

        try:
            result = session.submit_reported_user_turn(
                turn_id=body.turn_id,
                user_text=body.user_text,
                source_ref=body.source_ref,
            )
        except (WorldReducerError, SupervisorContractError, CognitiveSessionLifecycleError) as exc:
            raise HTTPException(
                status_code=409,
                detail="consciousness user-turn admission conflict",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness user-turn admission unavailable",
            ) from exc

        event = result.cognition_event
        receipt = UserTurnAdmissionReceipt(
            schema="kaliv-consciousness-core/user-turn-admission/v1",
            turn_ref=_turn_ref(body.turn_id),
            evidence_ref=result.evidence_ref,
            cognition_event_id=event.event_id if event is not None else None,
            world_changed=result.world_transition.world_changed,
            replayed=result.world_transition.idempotent_replay,
            cognition_event_queued=result.cognition_event_queued,
            epistemic_status="reported",
            confidence=1.0,
            observed_sequence=(
                event.observed_sequence
                if event is not None
                else next(
                    item.observed_sequence
                    for item in session.supervisor_state.pending_events
                    if item.source_ref == result.evidence_ref
                )
                if any(
                    item.source_ref == result.evidence_ref
                    for item in session.supervisor_state.pending_events
                )
                else next(
                    (
                        obs_index
                        for obs_index, obs in enumerate(
                            session.live_state.world.observations,
                            start=1,
                        )
                        if result.evidence_ref in obs.source_refs
                    ),
                    0,
                )
            ),
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_user_turn(
    app: FastAPI,
    *,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    """Mount the C21-A surface only after its independent exact opt-in."""
    if not consciousness_chat_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    kwargs = {}
    if loopback_allowed is not None:
        if not callable(loopback_allowed):
            raise TypeError("loopback policy must be callable")
        kwargs["loopback_allowed"] = loopback_allowed

    route_count = len(app.router.routes)
    try:
        app.include_router(build_consciousness_user_turn_router(**kwargs))
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
