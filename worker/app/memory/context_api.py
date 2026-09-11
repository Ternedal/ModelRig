from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

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
    async def context_for_turn(body: ContextForTurnBody, request: Request) -> dict:
        _require_loopback(request, loopback_allowed)
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
