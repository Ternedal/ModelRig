from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from ..netguard import is_loopback
from .context_service import (
    MAX_TURN_CONTEXT_CHARS,
    MAX_TURN_QUERY_CHARS,
    MAX_TURN_RESULTS,
    MAX_TURN_SUBJECTS,
    ContextForTurnRequest,
    MemoryContextForTurnService,
    MemoryContextRequestError,
    MemoryContextServiceError,
)
from .semantic import SemanticMemoryError
from .storage import SharedMemoryReadError


MEMORY4_CONTEXT_PREFIX = "/experimental/memory4"
MAX_MEMORY4_CONTEXT_BODY_BYTES = 256 * 1024
_INVALID_CONTEXT_BODY_DETAIL = "invalid memory context request"
LoopbackPolicy = Callable[[Request], bool]


class ContextForTurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: StrictStr = Field(min_length=1, max_length=MAX_TURN_QUERY_CHARS)
    target: Literal["local", "cloud"] = "local"
    subjects: list[StrictStr] = Field(default_factory=list, max_length=MAX_TURN_SUBJECTS)
    max_results: StrictInt = Field(default=12, ge=1, le=MAX_TURN_RESULTS)
    max_context_chars: StrictInt = Field(
        default=MAX_TURN_CONTEXT_CHARS,
        ge=1,
        le=MAX_TURN_CONTEXT_CHARS,
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
            detail="Memory 4 context-for-turn is loopback-only",
        )


def _invalid_context_body() -> HTTPException:
    return HTTPException(status_code=422, detail=_INVALID_CONTEXT_BODY_DETAIL)


async def _read_context_for_turn_body(request: Request) -> ContextForTurnBody:
    """Read one bounded JSON body without reflecting private validation input."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_context_body() from None
        if declared_length < 0 or declared_length > MAX_MEMORY4_CONTEXT_BODY_BYTES:
            raise _invalid_context_body() from None

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_MEMORY4_CONTEXT_BODY_BYTES:
                raise _invalid_context_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_context_body() from None

    if not raw:
        raise _invalid_context_body() from None

    try:
        return ContextForTurnBody.model_validate_json(bytes(raw))
    except ValidationError:
        # Pydantic validation errors can include the rejected ``input``. Never
        # expose that structure at this private context-for-turn boundary.
        raise _invalid_context_body() from None


def build_memory4_context_router(
    service: MemoryContextForTurnService,
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not isinstance(service, MemoryContextForTurnService):
        raise TypeError("MemoryContextForTurnService is required")
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(prefix=MEMORY4_CONTEXT_PREFIX, tags=["experimental-memory4"])

    @router.post("/context-for-turn")
    async def context_for_turn(request: Request) -> dict:
        # Admission deliberately precedes request-body consumption. A remote
        # caller cannot make this route parse private memory-query material.
        _require_loopback(request, loopback_allowed)
        body = await _read_context_for_turn_body(request)
        try:
            result = await service.context_for_turn(
                ContextForTurnRequest(
                    query=body.query,
                    target=body.target,
                    subjects=tuple(body.subjects),
                    max_results=body.max_results,
                    max_context_chars=body.max_context_chars,
                )
            )
        except MemoryContextRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (
            MemoryContextServiceError,
            SharedMemoryReadError,
            SemanticMemoryError,
        ) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"memory context unavailable: {type(exc).__name__}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="memory context unavailable",
            ) from exc
        return result.to_dict()

    return router
