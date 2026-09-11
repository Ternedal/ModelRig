from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ..netguard import is_loopback
from .context_api import MEMORY4_CONTEXT_PREFIX
from .extraction import MAX_COMPLETED_TURN_CHARS, MAX_SOURCE_REF_CHARS, CompletedMemoryTurn
from .write_service import MemoryCompletedTurnWriteService, MemoryTurnWriteError


MEMORY4_WRITE_ROUTE = "/completed-turn"
LoopbackPolicy = Callable[[Request], bool]


class CompletedTurnWriteBody(BaseModel):
    """Strict bounded wire shape for one already-completed text turn."""

    model_config = ConfigDict(extra="forbid")

    user_text: StrictStr = Field(min_length=1, max_length=MAX_COMPLETED_TURN_CHARS)
    assistant_text: StrictStr = Field(min_length=1, max_length=MAX_COMPLETED_TURN_CHARS)
    source_ref: StrictStr = Field(min_length=1, max_length=MAX_SOURCE_REF_CHARS)


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
            detail="Memory 4 completed-turn write is loopback-only",
        )


def build_memory4_write_router(
    service: MemoryCompletedTurnWriteService,
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not isinstance(service, MemoryCompletedTurnWriteService):
        raise TypeError("MemoryCompletedTurnWriteService is required")
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(prefix=MEMORY4_CONTEXT_PREFIX, tags=["experimental-memory4"])

    @router.post(MEMORY4_WRITE_ROUTE)
    async def write_completed_turn(
        body: CompletedTurnWriteBody,
        request: Request,
    ) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        try:
            receipt = await service.commit_completed_turn(
                CompletedMemoryTurn(
                    user_text=body.user_text,
                    assistant_text=body.assistant_text,
                    source_ref=body.source_ref,
                )
            )
        except MemoryTurnWriteError as exc:
            raise HTTPException(
                status_code=503,
                detail="memory write unavailable",
            ) from exc
        except Exception as exc:
            # The HTTP boundary never reflects extractor/storage exception text,
            # types, candidate values, evidence or protected payloads.
            raise HTTPException(
                status_code=503,
                detail="memory write unavailable",
            ) from exc
        return receipt.to_dict()

    return router
