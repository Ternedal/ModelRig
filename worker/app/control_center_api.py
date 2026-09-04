"""Loopback-only read surfaces for the T-044 Control Center contracts.

The worker owns normalization because it already owns worker/model readiness,
Agent 3 validation and the durable scheduler stores. A remote client never calls
these routes directly: the Bearer-authenticated Go backend is the only remote
boundary. The schedule-history route is deliberately observation-only and uses
a separate read projection that never instantiates the writer stores.
"""
from __future__ import annotations

import inspect
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .control_center_privacy import SCHEMA as PRIVACY_SCHEMA
from .control_center_privacy import build_control_center_privacy
from .control_center_schedule_history import build_control_center_schedule_history
from .control_center_status import build_control_center_status
from .netguard import is_loopback

HealthProvider = Callable[[], Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
Agent3Provider = Callable[[], Mapping[str, Any]]
RoutingProvider = Callable[[], Mapping[str, Any]]
ScheduleHistoryProvider = Callable[[], Mapping[str, Any]]
PrivacyProvider = Callable[[], Mapping[str, Any]]


def _loopback_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_loopback(
    request: Request,
    allowed: Callable[[Request], bool],
) -> None:
    try:
        admitted = bool(allowed(request))
    except Exception:
        admitted = False
    if not admitted:
        raise HTTPException(
            status_code=403,
            detail="control center worker status is loopback-only",
        )


async def _default_health_provider() -> Mapping[str, Any]:
    """Probe only process/Ollama facts; never import ToolGate or open its DB."""
    import httpx

    from . import ollama_client as oc
    from .main import VERSION

    models: dict[str, Any]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{oc.OLLAMA_URL}/api/tags")
        models = {
            "ok": response.status_code == 200,
            "detail": f"HTTP {response.status_code}",
        }
    except Exception as exc:
        models = {
            "ok": False,
            "detail": f"provider_error:{type(exc).__name__}",
        }
    return {
        "checks": {
            "worker": {"ok": True, "version": VERSION},
            "ollama": models,
        }
    }


def _default_agent3_provider() -> Mapping[str, Any]:
    observed_at = time.time()
    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":
        return {
            "enabled": False,
            "ok": False,
            "observed_at": observed_at,
            "detail": "Agent 3 developer surface disabled",
        }

    try:
        from .agent3.validation_gate import evaluate_configured_report
        from .build_identity import code_fingerprint
        from .main import VERSION

        assessment = evaluate_configured_report(
            current_version=VERSION,
            current_code=code_fingerprint(),
        )
    except Exception as exc:
        return {
            "enabled": True,
            "observed_at": observed_at,
            "detail": f"provider_error:{type(exc).__name__}",
        }

    reasons = assessment.get("reasons")
    if isinstance(reasons, list):
        detail = "; ".join(str(reason) for reason in reasons[:4])
    else:
        detail = None
    return {
        "enabled": True,
        "ok": assessment.get("eligible_for_developer_preview") is True,
        "observed_at": observed_at,
        "detail": detail or "Agent 3 developer readiness evaluated",
    }


def _default_routing_provider() -> Mapping[str, Any]:
    # Normal chat is still Agent v2. Agent 3 is an explicit developer surface,
    # represented by its own component readiness instead of a fake fallback.
    return {
        "configured_surface": "agent_v2",
        "active_surface": "agent_v2",
        "observed_at": time.time(),
    }


async def _call_health(provider: HealthProvider) -> Mapping[str, Any]:
    result = provider()
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, Mapping):
        raise TypeError("health provider returned a non-object")
    return result


def _copy_explicit_verdict(source: Mapping[str, Any], target: dict[str, Any]) -> None:
    verdict = source.get("ok")
    if isinstance(verdict, bool):
        target["ok"] = verdict


def _backend_component(request: Request) -> Mapping[str, Any]:
    observed_at = request.headers.get("x-kaliv-backend-observed-at")
    version = request.headers.get("x-kaliv-backend-version")
    status = request.headers.get("x-kaliv-backend-status")
    component: dict[str, Any] = {
        "observed_at": observed_at,
        "detail": f"modelrig-server {version}" if version else None,
    }
    if status == "ok":
        component["ok"] = True
    elif status == "unavailable":
        component["ok"] = False
    return component


def _health_components(
    health: Mapping[str, Any],
    *,
    observed_at: float,
) -> dict[str, Mapping[str, Any]]:
    checks = health.get("checks")
    if not isinstance(checks, Mapping):
        checks = {}

    worker = checks.get("worker")
    worker = worker if isinstance(worker, Mapping) else {}
    models = checks.get("ollama")
    models = models if isinstance(models, Mapping) else {}

    worker_component: dict[str, Any] = {
        "observed_at": observed_at,
        "detail": worker.get("detail") or worker.get("version"),
    }
    model_component: dict[str, Any] = {
        "observed_at": observed_at,
        "detail": models.get("detail"),
    }
    _copy_explicit_verdict(worker, worker_component)
    _copy_explicit_verdict(models, model_component)
    return {
        "worker": worker_component,
        "models": model_component,
    }


def _privacy_failure(exc: Exception) -> dict[str, Any]:
    """Fail closed without leaking provider messages or inventing permissions."""
    return {
        "schema": PRIVACY_SCHEMA,
        "evidence_state": "unknown",
        "reason": f"provider_error:{type(exc).__name__}",
        "tool_result_egress": None,
        "common_data_sharing": {
            "state": "unknown",
            "runtime_integrated": False,
            "reason": "privacy_provider_unavailable",
        },
        "scoped_permissions": {
            "state": "unknown",
            "count": None,
            "revocation_supported": False,
            "reason": "privacy_provider_unavailable",
        },
        "production_activation": False,
    }


def build_control_center_router(
    *,
    health_provider: HealthProvider = _default_health_provider,
    agent3_provider: Agent3Provider = _default_agent3_provider,
    routing_provider: RoutingProvider = _default_routing_provider,
    schedule_history_provider: ScheduleHistoryProvider = build_control_center_schedule_history,
    privacy_provider: PrivacyProvider = build_control_center_privacy,
    loopback_allowed: Callable[[Request], bool] = _loopback_allowed,
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    """Build a side-effect-free router; collection starts only on a local GET."""
    router = APIRouter(prefix="/control-center", tags=["control-center"])

    @router.get("/status")
    async def control_center_status(request: Request) -> dict[str, Any]:
        _require_loopback(request, loopback_allowed)
        now = float(clock())

        try:
            health = await _call_health(health_provider)
        except Exception as exc:
            health = {
                "checks": {
                    "worker": {"detail": f"provider_error:{type(exc).__name__}"},
                    "ollama": {"detail": f"provider_error:{type(exc).__name__}"},
                }
            }

        try:
            agent3 = agent3_provider()
        except Exception as exc:
            agent3 = {
                "enabled": os.getenv("KALIV_AGENT3_ENABLED", "0") == "1",
                "detail": f"provider_error:{type(exc).__name__}",
            }
        try:
            routing = routing_provider()
        except Exception as exc:
            routing = {"detail": f"provider_error:{type(exc).__name__}"}
        try:
            privacy_raw = privacy_provider()
            if not isinstance(privacy_raw, Mapping):
                raise TypeError("privacy provider returned a non-object")
            privacy = dict(privacy_raw)
        except Exception as exc:
            privacy = _privacy_failure(exc)

        components: dict[str, Any] = {
            "backend": _backend_component(request),
            **_health_components(health, observed_at=now),
            "agent3": agent3,
        }
        payload = build_control_center_status(
            components,
            routing,
            now=now,
        )
        # Additive v1 field. Backend forwards the versioned object unchanged;
        # older clients ignore it, while Control Center clients can adopt it
        # without a second remote authority or a duplicated policy route.
        payload["privacy"] = privacy
        return payload

    @router.get("/schedules")
    def control_center_schedules(request: Request) -> dict[str, Any]:
        _require_loopback(request, loopback_allowed)
        try:
            payload = schedule_history_provider()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"control center schedule history unavailable:{type(exc).__name__}",
            ) from None
        if not isinstance(payload, Mapping):
            raise HTTPException(
                status_code=503,
                detail="control center schedule history unavailable:TypeError",
            )
        return dict(payload)

    return router
