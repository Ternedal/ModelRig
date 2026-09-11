from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ..netguard import is_loopback
from .candidates import (
    MAX_TURN_ID_CHARS,
    MAX_TURN_TEXT_CHARS,
    CandidateForTurnRequest,
    MemoryCandidateExtractionError,
    MemoryCandidateExtractor,
    MemoryCandidateRequestError,
)


MEMORY4_CANDIDATE_PREFIX = "/experimental/memory4"
LoopbackPolicy = Callable[[Request], bool]


class CandidateForTurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: StrictStr = Field(min_length=1, max_length=MAX_TURN_ID_CHARS)
    user_text: StrictStr = Field(min_length=1, max_length=MAX_TURN_TEXT_CHARS)


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
            detail="Memory 4 candidate extraction is loopback-only",
        )


def build_memory4_candidate_router(
    extractor: MemoryCandidateExtractor,
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not isinstance(extractor, MemoryCandidateExtractor):
        raise TypeError("MemoryCandidateExtractor is required")
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(prefix=MEMORY4_CANDIDATE_PREFIX, tags=["experimental-memory4"])

    @router.post("/candidates-for-turn")
    async def candidates_for_turn(body: CandidateForTurnBody, request: Request) -> dict:
        _require_loopback(request, loopback_allowed)
        try:
            result = await extractor.candidates_for_turn(
                CandidateForTurnRequest(
                    turn_id=body.turn_id,
                    user_text=body.user_text,
                )
            )
        except MemoryCandidateRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MemoryCandidateExtractionError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"memory candidate extraction unavailable: {type(exc).__name__}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="memory candidate extraction unavailable",
            ) from exc
        return result.to_dict()

    return router
