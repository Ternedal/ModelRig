"""Authoritative default-off mount for the Agent 4 operator read surface."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from .domain import CampaignValidationError
from .operator_api import OPERATOR_MEDIA_TYPE, build_agent4_operator_router
from .operator_read_context import Agent4OperatorReadContext


def _rollback_routes(app: FastAPI, route_count: int) -> None:
    if len(app.router.routes) > route_count:
        del app.router.routes[route_count:]
    app.openapi_schema = None


def mount_agent4_operator(
    app: FastAPI,
    context: Agent4OperatorReadContext | None,
) -> bool:
    """Mount the read-only operator API exactly once after explicit opt-in.

    ``KALIV_AGENT4_OPERATOR_API`` is default-off and only exact ``"1"``
    enables the surface. Production mounting accepts only the narrow
    ``Agent4OperatorReadContext`` composed by A4-21. A full writer runtime must
    remain unmountable here until A4-25's server-side snapshot authority is
    implemented and qualified for concurrent lifecycle mutation + reads.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")
    if getattr(app.state, "agent4_operator_mounted", False):
        return True
    if os.getenv("KALIV_AGENT4_OPERATOR_API", "0") != "1":
        return False
    if not isinstance(context, Agent4OperatorReadContext):
        raise CampaignValidationError(
            "Agent 4 production operator API requires the narrow read-only context"
        )

    required = (
        "operator",
        "evidence_operator",
        "timeline",
        "query",
        "evidence_records",
        "evidence_query",
        "scheduler",
    )
    if any(getattr(context, name, None) is None for name in required):
        raise CampaignValidationError(
            "Agent 4 read context lacks the canonical operator services"
        )
    if context.operator.scheduler is not context.scheduler:
        raise CampaignValidationError(
            "Agent 4 campaign operator does not share the context campaign reader"
        )
    if context.operator.timeline is not context.timeline:
        raise CampaignValidationError(
            "Agent 4 campaign operator does not share the context timeline"
        )
    if context.operator.query is not context.query:
        raise CampaignValidationError(
            "Agent 4 campaign operator does not share the context query service"
        )
    if context.evidence_operator.scheduler is not context.scheduler:
        raise CampaignValidationError(
            "Agent 4 operator services do not share the context campaign reader"
        )
    if context.evidence_operator.records is not context.evidence_records:
        raise CampaignValidationError(
            "Agent 4 evidence operator does not share the context record store"
        )
    if context.evidence_operator.query is not context.evidence_query:
        raise CampaignValidationError(
            "Agent 4 evidence operator does not share the context query service"
        )

    route_count = len(app.router.routes)
    previous_context: Any = getattr(
        app.state,
        "agent4_runtime_context",
        None,
    )
    try:
        app.include_router(
            build_agent4_operator_router(
                context.operator,
                context.evidence_operator,
            )
        )
        _install_operator_error_media_type(app)
        app.state.agent4_runtime_context = context
        app.state.agent4_operator_mounted = True
        return True
    except Exception:
        _rollback_routes(app, route_count)
        app.state.agent4_runtime_context = previous_context
        app.state.agent4_operator_mounted = False
        raise


def _install_operator_error_media_type(app: FastAPI) -> None:
    """Type the operator API's ERROR responses like its successes.

    Success bodies carry application/vnd.modelrig.agent4.operator+json;
    HTTPException bodies fell back to FastAPI's application/json, so a 404
    from the operator surface was indistinguishable from a proxy's 404. The
    A4-25f evidence finalizer requires the vendor type on every physical
    trial, error stages included -- with the untyped errors it could never
    pass, which is what blocked Agent 4 finalization on the rig 30/08.
    """
    if getattr(app.state, "agent4_operator_error_handler", False):
        return

    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _typed_operator_errors(request, exc):  # type: ignore[no-untyped-def]
        response = await http_exception_handler(request, exc)
        if request.url.path.startswith("/experimental/agent4/operator"):
            response.headers["content-type"] = OPERATOR_MEDIA_TYPE
        return response

    app.state.agent4_operator_error_handler = True
