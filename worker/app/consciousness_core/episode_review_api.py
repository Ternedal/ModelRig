"""C30-O private loopback-only transport for trusted episode review.

The route set is independently default-off and delegates only to an already
constructed C30-N TrustedEpisodeReviewClaimService. It creates no mailbox,
review service, durable store, model call, Memory 4 call, or auth authority.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from ..netguard import is_loopback
from .episode_experience_review import TrustedEpisodeExperienceReview
from .episode_review_claim import (
    EpisodeReviewClaim,
    EpisodeReviewClaimAbandonReceipt,
    EpisodeReviewClaimCommitReceipt,
    EpisodeReviewClaimError,
    TrustedEpisodeReviewClaimService,
)
from .episode_review_mailbox import EpisodeExperienceReviewRequest
from .episode_review_status import build_episode_review_status
from .episode_review_attention import evaluate_episode_review_attention
from .experience import ExperienceCandidate


CONSCIOUSNESS_EPISODE_REVIEW_FLAG = (
    "KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED"
)
CONSCIOUSNESS_EPISODE_REVIEW_PREFIX = (
    "/experimental/consciousness/episode-review"
)
MAX_EPISODE_REVIEW_BODY_BYTES = 65536
_MOUNTED_STATE = "consciousness_episode_review_mounted"

LoopbackPolicy = Callable[[Request], bool]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeReviewClaimBody(StrictModel):
    request_id: StrictStr = Field(pattern=r"^ereq-[a-f0-9]{32}$")
    expected_request_ref: NonEmptyRef


class EpisodeReviewAbandonBody(StrictModel):
    claim_id: StrictStr = Field(pattern=r"^eclaim-[a-f0-9]{32}$")
    expected_request_ref: NonEmptyRef


class EpisodeReviewCommitBody(StrictModel):
    claim_id: StrictStr = Field(pattern=r"^eclaim-[a-f0-9]{32}$")
    expected_request_ref: NonEmptyRef
    review: TrustedEpisodeExperienceReview
    candidate: ExperienceCandidate | None = None


class EpisodeReviewClaimTransportReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-review-claim-transport/v1"
    ]
    request: EpisodeExperienceReviewRequest
    claim: EpisodeReviewClaim
    loopback_only: Literal[True]
    raw_chain_of_thought_included: Literal[False]
    durable_store_write_applied: Literal[False]
    memory4_called: Literal[False]
    model_calls: Literal[0]
    production_activation: Literal[False]


def consciousness_episode_review_enabled() -> bool:
    return os.getenv(CONSCIOUSNESS_EPISODE_REVIEW_FLAG, "0") == "1"


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
            detail="Consciousness episode review is loopback-only",
        )


def _service(request: Request) -> TrustedEpisodeReviewClaimService:
    service = getattr(
        request.app.state,
        "consciousness_episode_review_service",
        None,
    )
    if not isinstance(service, TrustedEpisodeReviewClaimService):
        raise HTTPException(
            status_code=503,
            detail="consciousness episode review unavailable",
        )
    return service


def _invalid_body() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="invalid consciousness episode-review request",
    )


async def _read_body(request: Request, model):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_body() from None
        if declared <= 0 or declared > MAX_EPISODE_REVIEW_BODY_BYTES:
            raise _invalid_body()

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_EPISODE_REVIEW_BODY_BYTES:
                raise _invalid_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_body() from None

    if not raw:
        raise _invalid_body()
    try:
        return model.model_validate_json(bytes(raw))
    except ValidationError:
        raise _invalid_body() from None


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="consciousness episode review state conflict",
    )


def build_consciousness_episode_review_router(
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(
        prefix=CONSCIOUSNESS_EPISODE_REVIEW_PREFIX,
        tags=["experimental-consciousness"],
    )

    @router.get("/status")
    async def status(request: Request) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        return build_episode_review_status(request.app).model_dump(
            mode="json"
        )

    @router.get("/attention")
    async def attention(request: Request) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        status = build_episode_review_status(request.app)
        return evaluate_episode_review_attention(status).model_dump(
            mode="json"
        )

    @router.get("/pending")
    async def list_pending(request: Request) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        raw_limit = request.query_params.get("limit", "8")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="invalid consciousness episode-review request",
            ) from None
        if limit < 1 or limit > 32 or str(limit) != raw_limit:
            raise HTTPException(
                status_code=422,
                detail="invalid consciousness episode-review request",
            )
        try:
            snapshot = _service(request).list_pending(limit=limit)
        except EpisodeReviewClaimError as exc:
            raise _conflict(exc) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness episode review unavailable",
            ) from exc
        return snapshot.model_dump(mode="json")

    @router.post("/claim")
    async def claim(request: Request) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        body = await _read_body(request, EpisodeReviewClaimBody)
        try:
            review_request, claim_receipt = _service(request).claim_exact(
                request_id=body.request_id,
                expected_request_ref=body.expected_request_ref,
            )
        except EpisodeReviewClaimError as exc:
            raise _conflict(exc) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness episode review unavailable",
            ) from exc

        receipt = EpisodeReviewClaimTransportReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-claim-transport/v1"
            ),
            request=review_request,
            claim=claim_receipt,
            loopback_only=True,
            raw_chain_of_thought_included=False,
            durable_store_write_applied=False,
            memory4_called=False,
            model_calls=0,
            production_activation=False,
        )
        return receipt.model_dump(mode="json")

    @router.post("/abandon")
    async def abandon(request: Request) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        body = await _read_body(request, EpisodeReviewAbandonBody)
        try:
            receipt: EpisodeReviewClaimAbandonReceipt = (
                _service(request).abandon(
                    claim_id=body.claim_id,
                    expected_request_ref=body.expected_request_ref,
                )
            )
        except EpisodeReviewClaimError as exc:
            raise _conflict(exc) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="consciousness episode review unavailable",
            ) from exc
        return receipt.model_dump(mode="json")

    @router.post("/commit")
    async def commit(request: Request) -> dict[str, object]:
        _require_loopback(request, loopback_allowed)
        body = await _read_body(request, EpisodeReviewCommitBody)
        try:
            receipt: EpisodeReviewClaimCommitReceipt = (
                _service(request).commit_decision(
                    claim_id=body.claim_id,
                    expected_request_ref=body.expected_request_ref,
                    review=body.review,
                    candidate=body.candidate,
                )
            )
        except EpisodeReviewClaimError as exc:
            raise _conflict(exc) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=409,
                detail="consciousness episode review state conflict",
            ) from exc
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_episode_review(
    app: FastAPI,
    *,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    if not consciousness_episode_review_enabled():
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
        app.include_router(
            build_consciousness_episode_review_router(**kwargs)
        )
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
