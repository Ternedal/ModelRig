from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from ..netguard import is_loopback
from .extraction import (
    MAX_COMPLETED_TURN_CHARS,
    MAX_SOURCE_REF_CHARS,
    CompletedMemoryTurn,
)
from .write_service import MemoryCompletedTurnWriteService, MemoryTurnWriteError


MEMORY4_WRITE_PREFIX = "/experimental/memory4"
MAX_MEMORY4_WRITE_BODY_BYTES = 512 * 1024
_INVALID_WRITE_BODY_DETAIL = "invalid memory completed-turn request"
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


def _invalid_write_body() -> HTTPException:
    return HTTPException(status_code=422, detail=_INVALID_WRITE_BODY_DETAIL)


async def _read_completed_turn_body(request: Request) -> CompletedTurnWriteBody:
    """Read one bounded JSON body without reflecting private validation input."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_write_body() from None
        if declared_length < 0 or declared_length > MAX_MEMORY4_WRITE_BODY_BYTES:
            raise _invalid_write_body() from None

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_MEMORY4_WRITE_BODY_BYTES:
                raise _invalid_write_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_write_body() from None

    if not raw:
        raise _invalid_write_body() from None

    try:
        return CompletedTurnWriteBody.model_validate_json(bytes(raw))
    except ValidationError:
        # Pydantic validation errors can include the rejected ``input``. Never
        # expose that structure at this private completed-turn boundary.
        raise _invalid_write_body() from None


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
    async def commit_completed_turn(request: Request) -> dict[str, object]:
        # Admission deliberately precedes request-body consumption. A remote
        # caller cannot make this route parse private completed-turn payloads.
        _require_loopback(request, loopback_allowed)
        body = await _read_completed_turn_body(request)
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
