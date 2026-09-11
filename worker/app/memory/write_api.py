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
# A valid completed turn contains at most 33,000 Unicode code points across its
# three caller fields. 512 KiB leaves room for worst-case JSON escaping while
# still bounding bytes before JSON/Pydantic parsing.
MAX_COMPLETED_TURN_WRITE_BODY_BYTES = 512 * 1024
INVALID_COMPLETED_TURN_WRITE_DETAIL = "invalid memory completed-turn write request"
LoopbackPolicy = Callable[[Request], bool]


class CompletedTurnWriteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_text: StrictStr = Field(min_length=1, max_length=MAX_COMPLETED_TURN_CHARS)
    assistant_text: StrictStr = Field(
        min_length=1,
        max_length=MAX_COMPLETED_TURN_CHARS,
    )
    source_ref: StrictStr = Field(min_length=1, max_length=MAX_SOURCE_REF_CHARS)


class _InvalidCompletedTurnWriteBody(ValueError):
    """The W04-A wire body is malformed or exceeds its pre-parse byte bound."""


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


async def _read_bounded_completed_turn_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as exc:
            raise _InvalidCompletedTurnWriteBody from exc
        if declared_length < 0 or declared_length > MAX_COMPLETED_TURN_WRITE_BODY_BYTES:
            raise _InvalidCompletedTurnWriteBody

    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_COMPLETED_TURN_WRITE_BODY_BYTES:
                raise _InvalidCompletedTurnWriteBody
            if chunk:
                chunks.append(bytes(chunk))
    except _InvalidCompletedTurnWriteBody:
        raise
    except Exception as exc:
        raise _InvalidCompletedTurnWriteBody from exc

    raw = b"".join(chunks)
    if not raw:
        raise _InvalidCompletedTurnWriteBody
    return raw


def _parse_completed_turn_body(raw: bytes) -> CompletedTurnWriteBody:
    try:
        return CompletedTurnWriteBody.model_validate_json(raw)
    except Exception as exc:
        # Never surface Pydantic/JSON diagnostics here: they may contain the
        # rejected user_text, assistant_text or source_ref.
        raise _InvalidCompletedTurnWriteBody from exc


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
        # Admission is deliberately the first operation. Keeping the request body
        # out of the FastAPI endpoint signature prevents framework validation from
        # reading or echoing private turn data before this loopback check runs.
        _require_loopback(request, loopback_allowed)
        try:
            raw = await _read_bounded_completed_turn_body(request)
            body = _parse_completed_turn_body(raw)
        except _InvalidCompletedTurnWriteBody as exc:
            raise HTTPException(
                status_code=422,
                detail=INVALID_COMPLETED_TURN_WRITE_DETAIL,
            ) from exc

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
