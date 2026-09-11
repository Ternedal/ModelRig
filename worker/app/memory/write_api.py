from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ..netguard import is_loopback
from .extraction import (
    MAX_COMPLETED_TURN_CHARS,
    MAX_SOURCE_REF_CHARS,
    CompletedMemoryTurn,
)
from .write_service import MemoryCompletedTurnWriteService, MemoryTurnWriteError


MEMORY4_WRITE_PREFIX = "/experimental/memory4"
LoopbackPolicy = Callable[[Request], bool]


class CompletedTurnWriteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_text: StrictStr = Field(min_length=1, max_length=MAX_COMPLETED_TURN_CHARS)
    assistant_text: StrictStr = Field(
        min_length=1,
        max_length=MAX_COMPLETED_TURN_CHARS,
    )
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

    router = APIRouter(prefix=MEMORY4_WRITE_PREFIX, tags=["experimental-memory4"])

    @router.post("/commit-completed-turn")
    async def commit_completed_turn(
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
                detail="memory completed-turn write unavailable",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="memory completed-turn write unavailable",
            ) from exc
        return receipt.to_dict()

    return router
