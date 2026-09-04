"""Read-only FastAPI adapter for the canonical Agent 4 operator services.

The adapter owns no storage or runtime composition. It receives the two
transport-independent read services, preserves their canonical ``to_dict``
payloads and exposes only bounded GET operations.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .campaign_list_query import (
    CampaignListQueryCursor,
    CampaignListQueryError,
)
from .domain import CampaignStatus, CampaignValidationError
from .operator import Agent4CampaignOverview, Agent4OperatorReadService
from .operator_evidence import (
    Agent4OperatorEvidenceReadService,
    CampaignEvidenceRecordNotFoundError,
)
from .repository import CampaignRepositoryError
from .service import CampaignNotFoundError
from .timeline import TimelineStoreError
from .timeline_evidence import EvidenceRecordStoreError
from .timeline_evidence_query import (
    CampaignEvidenceQueryCursor,
    CampaignEvidenceQueryError,
)
from .timeline_query import (
    CampaignTimelineQueryCursor,
    CampaignTimelineQueryError,
)

OPERATOR_API_SCHEMA = "modelrig-agent4/operator-api/v1"
OPERATOR_MEDIA_TYPE = "application/vnd.modelrig.agent4.operator+json"
MAX_CURSOR_QUERY_BYTES = 16_384

CursorValue = (
    CampaignListQueryCursor
    | CampaignTimelineQueryCursor
    | CampaignEvidenceQueryCursor
)
CursorType = (
    type[CampaignListQueryCursor]
    | type[CampaignTimelineQueryCursor]
    | type[CampaignEvidenceQueryCursor]
)


class Agent4OperatorApiRequestError(ValueError):
    """Raised when the transport request cannot map to a canonical read call."""


def _response(**payload: Any) -> JSONResponse:
    return JSONResponse(
        content={"schema": OPERATOR_API_SCHEMA, **payload},
        media_type=OPERATOR_MEDIA_TYPE,
    )


def _single_query(request: Request, name: str) -> str | None:
    values = request.query_params.getlist(name)
    if len(values) > 1:
        raise Agent4OperatorApiRequestError(
            f"agent4 operator query parameter {name!r} is repeated"
        )
    return values[0] if values else None


def _limit(request: Request, *, default: int = 100) -> int:
    raw = _single_query(request, "limit")
    if raw is None:
        return default
    if not raw or raw.strip() != raw or not raw.isascii() or not raw.isdecimal():
        raise Agent4OperatorApiRequestError("agent4 operator limit is invalid")
    try:
        return int(raw, 10)
    except (TypeError, ValueError, OverflowError) as exc:
        raise Agent4OperatorApiRequestError(
            "agent4 operator limit is invalid"
        ) from exc


def _statuses(request: Request) -> tuple[CampaignStatus, ...] | None:
    values = request.query_params.getlist("status")
    if not values:
        return None
    if len(values) != len(set(values)):
        raise Agent4OperatorApiRequestError(
            "agent4 operator status values must be unique"
        )
    try:
        return tuple(CampaignStatus(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise Agent4OperatorApiRequestError(
            "agent4 operator status is unsupported"
        ) from exc


def _cursor(
    request: Request,
    name: str,
    cursor_type: CursorType,
) -> CursorValue | None:
    raw = _single_query(request, name)
    if raw is None:
        return None
    if not raw or len(raw.encode("utf-8")) > MAX_CURSOR_QUERY_BYTES:
        raise Agent4OperatorApiRequestError(
            "agent4 operator cursor is outside the allowed size"
        )
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise Agent4OperatorApiRequestError(
            "agent4 operator cursor is invalid"
        ) from exc
    if not isinstance(decoded, Mapping):
        raise Agent4OperatorApiRequestError(
            "agent4 operator cursor must be an object"
        )
    try:
        return cursor_type.from_dict(decoded)
    except (CampaignValidationError, TypeError, ValueError, KeyError) as exc:
        raise Agent4OperatorApiRequestError(
            "agent4 operator cursor is invalid"
        ) from exc


def _overview(value: Agent4CampaignOverview) -> dict[str, Any]:
    return {
        "record": value.record.to_dict(),
        "timeline_entries": value.timeline_entries,
        "event_entries": value.event_entries,
        "evidence_entries": value.evidence_entries,
        "latest_timeline_hash": (
            f"sha256:{value.latest_timeline_hash}"
            if value.latest_timeline_hash is not None
            else None
        ),
    }


def _timeline_page(value: Any) -> dict[str, Any]:
    return {
        "campaign_id": value.campaign_id,
        "entries": [entry.to_dict() for entry in value.entries],
        "start_cursor": value.start_cursor.to_dict(),
        "next_cursor": value.next_cursor.to_dict(),
        "head_cursor": value.head_cursor.to_dict(),
        "has_more": value.has_more,
    }


def _evidence_page(value: Any) -> dict[str, Any]:
    return {
        "campaign_id": value.campaign_id,
        "records": [record.to_dict() for record in value.records],
        "start_cursor": value.start_cursor.to_dict(),
        "next_cursor": value.next_cursor.to_dict(),
        "head_cursor": value.head_cursor.to_dict(),
        "has_more": value.has_more,
    }


def _verification(value: Any) -> dict[str, Any]:
    return {
        "campaign_id": value.campaign_id,
        "record_count": value.record_count,
        "head_hash": (
            f"sha256:{value.head_hash}" if value.head_hash is not None else None
        ),
        "latest_timeline_head_hash": (
            f"sha256:{value.latest_timeline_head_hash}"
            if value.latest_timeline_head_hash is not None
            else None
        ),
    }


def _raise_public(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        (CampaignNotFoundError, CampaignEvidenceRecordNotFoundError),
    ):
        raise HTTPException(
            status_code=404,
            detail="agent4 operator resource not found",
        ) from exc
    if isinstance(
        exc,
        (
            Agent4OperatorApiRequestError,
            CampaignValidationError,
            CampaignListQueryError,
            CampaignTimelineQueryError,
            CampaignEvidenceQueryError,
        ),
    ):
        raise HTTPException(
            status_code=422,
            detail="agent4 operator request rejected",
        ) from exc
    if isinstance(
        exc,
        (CampaignRepositoryError, TimelineStoreError, EvidenceRecordStoreError),
    ):
        raise HTTPException(
            status_code=503,
            detail="agent4 operator read unavailable",
        ) from exc
    raise exc


def build_agent4_operator_router(
    operator: Agent4OperatorReadService,
    evidence_operator: Agent4OperatorEvidenceReadService,
) -> APIRouter:
    """Build the read-only router over one already composed object graph."""

    if not isinstance(operator, Agent4OperatorReadService):
        raise CampaignValidationError(
            "operator must be an Agent4OperatorReadService"
        )
    if not isinstance(evidence_operator, Agent4OperatorEvidenceReadService):
        raise CampaignValidationError(
            "evidence_operator must be an Agent4OperatorEvidenceReadService"
        )
    if evidence_operator.scheduler is not operator.scheduler:
        raise CampaignValidationError(
            "operator services must share the same campaign scheduler"
        )

    router = APIRouter(
        prefix="/experimental/agent4/operator",
        tags=["experimental-agent4-operator"],
    )

    @router.get("/campaigns")
    def list_campaigns(request: Request) -> JSONResponse:
        try:
            after = _cursor(request, "after", CampaignListQueryCursor)
            snapshot_head = _cursor(
                request,
                "snapshot_head",
                CampaignListQueryCursor,
            )
            assert after is None or isinstance(after, CampaignListQueryCursor)
            assert snapshot_head is None or isinstance(
                snapshot_head,
                CampaignListQueryCursor,
            )
            page = operator.campaign_page(
                statuses=_statuses(request),
                after=after,
                limit=_limit(request),
                snapshot_head=snapshot_head,
            )
            return _response(
                campaigns=[_overview(value) for value in page.campaigns],
                start_cursor=page.start_cursor.to_dict(),
                next_cursor=page.next_cursor.to_dict(),
                head_cursor=page.head_cursor.to_dict(),
                has_more=page.has_more,
            )
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}")
    def campaign(campaign_id: str) -> JSONResponse:
        try:
            return _response(campaign=_overview(operator.campaign(campaign_id)))
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/timeline")
    def timeline(campaign_id: str, request: Request) -> JSONResponse:
        try:
            after = _cursor(request, "after", CampaignTimelineQueryCursor)
            snapshot_head = _cursor(
                request,
                "snapshot_head",
                CampaignTimelineQueryCursor,
            )
            assert after is None or isinstance(after, CampaignTimelineQueryCursor)
            assert snapshot_head is None or isinstance(
                snapshot_head,
                CampaignTimelineQueryCursor,
            )
            page = operator.timeline_page(
                campaign_id,
                after=after,
                limit=_limit(request),
                snapshot_head=snapshot_head,
            )
            return _response(page=_timeline_page(page))
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/evidence")
    def evidence_page(campaign_id: str, request: Request) -> JSONResponse:
        try:
            after = _cursor(request, "after", CampaignEvidenceQueryCursor)
            snapshot_head = _cursor(
                request,
                "snapshot_head",
                CampaignEvidenceQueryCursor,
            )
            assert after is None or isinstance(after, CampaignEvidenceQueryCursor)
            assert snapshot_head is None or isinstance(
                snapshot_head,
                CampaignEvidenceQueryCursor,
            )
            page = evidence_operator.evidence_page(
                campaign_id,
                after=after,
                limit=_limit(request),
                snapshot_head=snapshot_head,
            )
            return _response(page=_evidence_page(page))
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/evidence/verification")
    def evidence_verification(campaign_id: str) -> JSONResponse:
        try:
            return _response(
                verification=_verification(
                    evidence_operator.verification(campaign_id)
                )
            )
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/evidence/{evidence_id}")
    def evidence(campaign_id: str, evidence_id: str) -> JSONResponse:
        try:
            return _response(
                evidence=evidence_operator.evidence(
                    campaign_id,
                    evidence_id,
                ).to_dict()
            )
        except Exception as exc:
            _raise_public(exc)

    return router
