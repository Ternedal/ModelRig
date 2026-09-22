"""C23-B private one-shot response-guidance consume surface.

This route exposes only the outward-facing C23-A ResponseGuidanceEnvelope.
It cannot access or return the remaining ThoughtProposal / inner-monologue
fields and performs no model call.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from ..netguard import is_loopback
from .response_guidance import response_guidance_ref
from .session_lifecycle import (
    CognitiveSessionLifecycleError,
    ProductionCognitiveSession,
)


CONSCIOUSNESS_GUIDANCE_FLAG = "KALIV_CONSCIOUSNESS_GUIDANCE_ENABLED"
CONSCIOUSNESS_GUIDANCE_PREFIX = "/experimental/consciousness"
MAX_GUIDANCE_CONSUME_BODY_BYTES = 4096
_MOUNTED_STATE = "consciousness_guidance_mounted"

LoopbackPolicy = Callable[[Request], bool]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ResponseGuidanceConsumeBody(StrictModel):
    user_turn_event_id: StrictStr = Field(pattern=r"^cevt-[a-f0-9]{32}$")


class ResponseGuidanceConsumeReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/response-guidance-consume/v1"]
    guidance_ref: NonEmptyRef
    guidance_id: Annotated[str, Field(pattern=r"^rguid-[a-f0-9]{32}$")]
    user_turn_event_id: Annotated[str, Field(pattern=r"^cevt-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    proposal_ref: NonEmptyRef
    cognitive_profile_ref: NonEmptyRef
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    self_revision: Annotated[int, Field(ge=1, strict=True)]
    text: Annotated[str, Field(min_length=1, max_length=4096)]
    source_field: Literal["thought-proposal.response_intent"]
    contains_only_response_intent: Literal[True]
    raw_chain_of_thought_included: Literal[False]
    consumed: Literal[True]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    automatic_repeat: Literal[False]
    production_activation: Literal[False]


def consciousness_guidance_enabled() -> bool:
    """Only exact string 1 exposes the C23-B outward-guidance boundary."""
    return os.getenv("KALIV_CONSCIOUSNESS_GUIDANCE_ENABLED", "0") == "1"


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
            detail="Consciousness response guidance is loopback-only",
        )


def _invalid_body() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="invalid consciousness response-guidance request",
    )


async def _read_body(request: Request) -> ResponseGuidanceConsumeBody:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_body() from None
        if declared <= 0 or declared > MAX_GUIDANCE_CONSUME_BODY_BYTES:
            raise _invalid_body()

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_GUIDANCE_CONSUME_BODY_BYTES:
                raise _invalid_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_body() from None

    if not raw:
        raise _invalid_body()
    try:
        return ResponseGuidanceConsumeBody.model_validate_json(bytes(raw))
    except ValidationError:
        raise _invalid_body() from None


def build_consciousness_guidance_router(
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(
        prefix=CONSCIOUSNESS_GUIDANCE_PREFIX,
        tags=["experimental-consciousness"],
    )

    @router.post("/response-guidance/consume")
    async def consume_guidance(request: Request) -> dict[str, object]:
        # Remote callers are rejected before private body parsing or session
        # inspection.
        _require_loopback(request, loopback_allowed)
        body = await _read_body(request)

        session = getattr(request.app.state, "consciousness_session", None)
        if not isinstance(session, ProductionCognitiveSession):
            raise HTTPException(
                status_code=503,
                detail="consciousness session unavailable",
            )

        try:
            guidance = session.consume_response_guidance(
                user_turn_event_id=body.user_turn_event_id,
            )
        except CognitiveSessionLifecycleError as exc:
            raise HTTPException(
                status_code=409,
                detail="response guidance belongs to another user turn or session",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="response guidance unavailable",
            ) from exc

        if guidance is None:
            raise HTTPException(
                status_code=404,
                detail="response guidance not available",
            )

        receipt = ResponseGuidanceConsumeReceipt(
            schema="kaliv-consciousness-core/response-guidance-consume/v1",
            guidance_ref=response_guidance_ref(guidance),
            guidance_id=guidance.guidance_id,
            user_turn_event_id=guidance.user_turn_event_id,
            cycle_id=guidance.cycle_id,
            proposal_ref=guidance.proposal_ref,
            cognitive_profile_ref=guidance.cognitive_profile_ref,
            person_revision=guidance.person_revision,
            self_revision=guidance.self_revision,
            text=guidance.text,
            source_field=guidance.source_field,
            contains_only_response_intent=True,
            raw_chain_of_thought_included=False,
            consumed=True,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            automatic_repeat=False,
            production_activation=False,
        )
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_guidance(
    app: FastAPI,
    *,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    """Mount only after the independent exact guidance opt-in."""
    if not consciousness_guidance_enabled():
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
        app.include_router(build_consciousness_guidance_router(**kwargs))
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
