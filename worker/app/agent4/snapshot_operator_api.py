"""Dormant FastAPI v2 adapter for immutable Agent 4 operator snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .campaign_list_query import CampaignListQueryCursor, CampaignListQueryError
from .domain import CampaignStatus, CampaignValidationError
from .operator import Agent4CampaignOverview
from .operator_evidence import CampaignEvidenceRecordNotFoundError
from .service import CampaignNotFoundError
from .snapshot_cursor import (
    OperatorSnapshotCursor,
    OperatorSnapshotCursorError,
    SnapshotInnerCursorType,
)
from .snapshot_operator import (
    Agent4SnapshotOperatorReadService,
    OperatorSnapshotReadUnavailableError,
    SnapshotEvidencePage,
    SnapshotTimelinePage,
)
from .snapshot_store import (
    OperatorSnapshotError,
    OperatorSnapshotNotFoundError,
)
from .timeline import TimelineStoreError
from .timeline_evidence import EvidenceRecordStoreError
from .timeline_evidence_query import (
    CampaignEvidenceQueryCursor,
    CampaignEvidenceQueryError,
)
from .timeline_query import CampaignTimelineQueryCursor, CampaignTimelineQueryError

SNAPSHOT_OPERATOR_API_SCHEMA = "modelrig-agent4/operator-api/v2"
SNAPSHOT_OPERATOR_MEDIA_TYPE = "application/vnd.modelrig.agent4.operator+json"
MAX_SNAPSHOT_CURSOR_QUERY_BYTES = 16_384


class Agent4SnapshotOperatorApiRequestError(ValueError):
    """Raised when a v2 transport request cannot map to one immutable read."""


def _response(*, snapshot_id: str, **payload: Any) -> JSONResponse:
    return JSONResponse(
        content={
            "schema": SNAPSHOT_OPERATOR_API_SCHEMA,
            "snapshot_id": snapshot_id,
            **payload,
        },
        media_type=SNAPSHOT_OPERATOR_MEDIA_TYPE,
    )


def _single_query(request: Request, name: str) -> str | None:
    values = request.query_params.getlist(name)
    if len(values) > 1:
        raise Agent4SnapshotOperatorApiRequestError(
            f"agent4 snapshot query parameter {name!r} is repeated"
        )
    return values[0] if values else None


def _reject_unknown(request: Request, allowed: frozenset[str]) -> None:
    unknown = set(request.query_params.keys()) - allowed
    if unknown:
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot query contains unsupported parameters"
        )


def _limit(request: Request, *, default: int = 100) -> int:
    raw = _single_query(request, "limit")
    if raw is None:
        return default
    if not raw or raw.strip() != raw or not raw.isascii() or not raw.isdecimal():
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot limit is invalid"
        )
    try:
        return int(raw, 10)
    except (TypeError, ValueError, OverflowError) as exc:
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot limit is invalid"
        ) from exc


def _statuses(request: Request) -> tuple[CampaignStatus, ...] | None:
    values = request.query_params.getlist("status")
    if not values:
        return None
    if len(values) != len(set(values)):
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot status values must be unique"
        )
    try:
        return tuple(CampaignStatus(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot status is unsupported"
        ) from exc


def _snapshot_id(request: Request) -> str | None:
    raw = _single_query(request, "snapshot_id")
    if raw is None:
        return None
    if not raw or raw.strip() != raw:
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot_id is invalid"
        )
    return raw


def _cursor(
    request: Request,
    name: str,
    cursor_type: SnapshotInnerCursorType,
) -> OperatorSnapshotCursor | None:
    raw = _single_query(request, name)
    if raw is None:
        return None
    if not raw or len(raw.encode("utf-8")) > MAX_SNAPSHOT_CURSOR_QUERY_BYTES:
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot cursor is outside the allowed size"
        )
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot cursor is invalid"
        ) from exc
    if not isinstance(decoded, Mapping):
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot cursor must be an object"
        )
    try:
        return OperatorSnapshotCursor.from_dict(
            decoded,
            cursor_type=cursor_type,
        )
    except (CampaignValidationError, TypeError, ValueError, KeyError) as exc:
        raise Agent4SnapshotOperatorApiRequestError(
            "agent4 snapshot cursor is invalid"
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


def _timeline_page(value: SnapshotTimelinePage) -> dict[str, Any]:
    return {
        "campaign_id": value.page.campaign_id,
        "entries": [entry.to_dict() for entry in value.page.entries],
        "start_cursor": value.start_cursor.to_dict(),
        "next_cursor": value.next_cursor.to_dict(),
        "head_cursor": value.head_cursor.to_dict(),
        "has_more": value.page.has_more,
    }


def _evidence_page(value: SnapshotEvidencePage) -> dict[str, Any]:
    return {
        "campaign_id": value.page.campaign_id,
        "records": [record.to_dict() for record in value.page.records],
        "start_cursor": value.start_cursor.to_dict(),
        "next_cursor": value.next_cursor.to_dict(),
        "head_cursor": value.head_cursor.to_dict(),
        "has_more": value.page.has_more,
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


# Errors must be typed as the operator surface, exactly like successes.
# FastAPI renders HTTPException as application/json unless the response
# carries its own content-type, so every public error below passes one:
# the A4-25f evidence finalizer requires the vendor media type on ALL
# physical trials, error stages included, and the fixture host builds its
# own app -- so this has to hold at the source, not at mount time.
_ERROR_HEADERS = {"content-type": SNAPSHOT_OPERATOR_MEDIA_TYPE}


def _raise_public(exc: Exception) -> NoReturn:
    if isinstance(exc, OperatorSnapshotNotFoundError):
        raise HTTPException(
            status_code=410,
            detail="agent4 operator snapshot unavailable",
            headers=_ERROR_HEADERS,
        ) from exc
    if isinstance(
        exc,
        (CampaignNotFoundError, CampaignEvidenceRecordNotFoundError),
    ):
        raise HTTPException(
            status_code=404,
            detail="agent4 operator resource not found",
            headers=_ERROR_HEADERS,
        ) from exc
    if isinstance(
        exc,
        (
            Agent4SnapshotOperatorApiRequestError,
            CampaignValidationError,
            OperatorSnapshotCursorError,
            CampaignListQueryError,
            CampaignTimelineQueryError,
            CampaignEvidenceQueryError,
        ),
    ):
        raise HTTPException(
            status_code=422,
            detail="agent4 operator snapshot request rejected",
            headers=_ERROR_HEADERS,
        ) from exc
    if isinstance(
        exc,
        (
            OperatorSnapshotReadUnavailableError,
            OperatorSnapshotError,
            TimelineStoreError,
            EvidenceRecordStoreError,
        ),
    ):
        raise HTTPException(
            status_code=503,
            detail="agent4 operator snapshot read unavailable",
            headers=_ERROR_HEADERS,
        ) from exc
    raise exc


def build_agent4_snapshot_operator_router(
    operator: Agent4SnapshotOperatorReadService,
) -> APIRouter:
    """Build the v2 router without mounting or composing writer authority."""

    if not isinstance(operator, Agent4SnapshotOperatorReadService):
        raise CampaignValidationError(
            "operator must be an Agent4SnapshotOperatorReadService"
        )

    router = APIRouter(
        prefix="/experimental/agent4/operator",
        tags=["experimental-agent4-operator-snapshot"],
    )

    @router.get("/campaigns")
    def list_campaigns(request: Request) -> JSONResponse:
        try:
            _reject_unknown(
                request,
                frozenset({"snapshot_id", "status", "limit", "after", "snapshot_head"}),
            )
            page = operator.campaign_page(
                snapshot_id=_snapshot_id(request),
                statuses=_statuses(request),
                after=_cursor(request, "after", CampaignListQueryCursor),
                snapshot_head=_cursor(
                    request,
                    "snapshot_head",
                    CampaignListQueryCursor,
                ),
                limit=_limit(request),
            )
            return _response(
                snapshot_id=page.snapshot_id,
                campaigns=[_overview(value) for value in page.campaigns],
                start_cursor=page.start_cursor.to_dict(),
                next_cursor=page.next_cursor.to_dict(),
                head_cursor=page.head_cursor.to_dict(),
                has_more=page.has_more,
            )
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}")
    def campaign(campaign_id: str, request: Request) -> JSONResponse:
        try:
            _reject_unknown(request, frozenset({"snapshot_id"}))
            result = operator.campaign(
                campaign_id,
                snapshot_id=_snapshot_id(request),
            )
            return _response(
                snapshot_id=result.snapshot_id,
                campaign=_overview(result.campaign),
            )
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/timeline")
    def timeline(campaign_id: str, request: Request) -> JSONResponse:
        try:
            _reject_unknown(
                request,
                frozenset({"snapshot_id", "limit", "after"}),
            )
            page = operator.timeline_page(
                campaign_id,
                snapshot_id=_snapshot_id(request),
                after=_cursor(request, "after", CampaignTimelineQueryCursor),
                limit=_limit(request),
            )
            return _response(
                snapshot_id=page.snapshot_id,
                page=_timeline_page(page),
            )
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/evidence")
    def evidence_page(campaign_id: str, request: Request) -> JSONResponse:
        try:
            _reject_unknown(
                request,
                frozenset({"snapshot_id", "limit", "after"}),
            )
            page = operator.evidence_page(
                campaign_id,
                snapshot_id=_snapshot_id(request),
                after=_cursor(request, "after", CampaignEvidenceQueryCursor),
                limit=_limit(request),
            )
            return _response(
                snapshot_id=page.snapshot_id,
                page=_evidence_page(page),
            )
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/evidence/verification")
    def evidence_verification(campaign_id: str, request: Request) -> JSONResponse:
        try:
            _reject_unknown(request, frozenset({"snapshot_id"}))
            result = operator.verification(
                campaign_id,
                snapshot_id=_snapshot_id(request),
            )
            return _response(
                snapshot_id=result.snapshot_id,
                verification=_verification(result.verification),
            )
        except Exception as exc:
            _raise_public(exc)

    @router.get("/campaigns/{campaign_id}/evidence/{evidence_id}")
    def evidence(campaign_id: str, evidence_id: str, request: Request) -> JSONResponse:
        try:
            _reject_unknown(request, frozenset({"snapshot_id"}))
            result = operator.evidence(
                campaign_id,
                evidence_id,
                snapshot_id=_snapshot_id(request),
            )
            return _response(
                snapshot_id=result.snapshot_id,
                evidence=result.evidence.to_dict(),
            )
        except Exception as exc:
            _raise_public(exc)

    return router
