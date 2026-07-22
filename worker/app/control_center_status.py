"""Server-authoritative, read-only status contract for Kaliv Control Center.

This first T-044 layer deliberately has no route and no client wiring.  It turns
already-observed health/routing facts into one versioned, freshness-aware object.
A source can never become green merely by saying ``ok=true``: it must also carry
a recent observation timestamp.  Unknown and stale values therefore fail closed
instead of being rendered as healthy by a client-side guess.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from typing import Any

SCHEMA = "kaliv-control-center-status/v1"
DEFAULT_FRESHNESS_S = 30.0
MAX_FRESHNESS_S = 3600.0
MAX_CLOCK_SKEW_S = 5.0
DETAIL_LIMIT = 240

_COMPONENTS: dict[str, bool] = {
    "backend": True,
    "worker": True,
    "models": True,
    "agent3": False,
}
_ALLOWED_SURFACES = {"agent_v2", "agent3_developer"}


def _bounded_detail(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:DETAIL_LIMIT] or None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _age(observed_at: Any, *, now: float) -> tuple[float | None, str | None]:
    timestamp = _finite_number(observed_at)
    if timestamp is None:
        return None, "missing_or_invalid_observed_at"
    age = now - timestamp
    if age < -MAX_CLOCK_SKEW_S:
        return None, "observation_from_future"
    return max(0.0, age), None


def _component_status(
    name: str,
    raw: Any,
    *,
    now: float,
    freshness_s: float,
    required: bool,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "required": required,
        "state": "unknown",
        "green": False,
        "observed_at": None,
        "age_s": None,
        "detail": None,
        "reason": "missing_source",
    }
    if not isinstance(raw, Mapping):
        return base

    observed_at = _finite_number(raw.get("observed_at"))
    age, time_error = _age(raw.get("observed_at"), now=now)
    base["observed_at"] = observed_at
    base["age_s"] = round(age, 3) if age is not None else None
    base["detail"] = _bounded_detail(raw.get("detail"))
    if time_error:
        base["reason"] = time_error
        return base
    if age is not None and age > freshness_s:
        base["state"] = "stale"
        base["reason"] = "observation_too_old"
        return base

    enabled = raw.get("enabled")
    if enabled is False:
        base["state"] = "disabled"
        base["reason"] = "disabled_by_configuration"
        return base

    verdict = raw.get("ok")
    if verdict is True:
        base["state"] = "healthy"
        base["green"] = True
        base["reason"] = None
        return base
    if verdict is False:
        base["state"] = "unavailable"
        base["reason"] = "source_reported_unavailable"
        return base

    base["reason"] = "missing_boolean_verdict"
    return base


def _routing_status(
    raw: Any,
    *,
    now: float,
    freshness_s: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": "unknown",
        "green": False,
        "configured_surface": None,
        "active_surface": None,
        "fallback_reason": None,
        "observed_at": None,
        "age_s": None,
        "reason": "missing_source",
    }
    if not isinstance(raw, Mapping):
        return result

    observed_at = _finite_number(raw.get("observed_at"))
    age, time_error = _age(raw.get("observed_at"), now=now)
    result["observed_at"] = observed_at
    result["age_s"] = round(age, 3) if age is not None else None
    if time_error:
        result["reason"] = time_error
        return result
    if age is not None and age > freshness_s:
        result["state"] = "stale"
        result["reason"] = "observation_too_old"
        return result

    configured = raw.get("configured_surface")
    active = raw.get("active_surface")
    fallback_reason = _bounded_detail(raw.get("fallback_reason"))
    result["configured_surface"] = configured
    result["active_surface"] = active
    result["fallback_reason"] = fallback_reason

    if configured == "disabled" and active == "agent_v2":
        result["state"] = "disabled"
        result["reason"] = "agent3_disabled_by_configuration"
        return result
    if configured not in _ALLOWED_SURFACES or active not in _ALLOWED_SURFACES:
        result["reason"] = "unknown_surface"
        return result
    if configured == active:
        result["state"] = "healthy"
        result["green"] = True
        result["reason"] = None
        return result
    if configured == "agent3_developer" and active == "agent_v2":
        if not fallback_reason:
            result["reason"] = "fallback_reason_missing"
            return result
        result["state"] = "fallback"
        result["reason"] = "server_selected_fallback"
        return result

    result["reason"] = "unsupported_route_transition"
    return result


def build_control_center_status(
    components: Mapping[str, Any],
    routing: Any,
    *,
    now: float | None = None,
    freshness_s: float = DEFAULT_FRESHNESS_S,
) -> dict[str, Any]:
    """Normalize observed facts into the v1 Control Center status object."""
    now_v = time.time() if now is None else _finite_number(now)
    if now_v is None:
        raise ValueError("now must be a finite timestamp")
    freshness_v = _finite_number(freshness_s)
    if freshness_v is None or freshness_v <= 0 or freshness_v > MAX_FRESHNESS_S:
        raise ValueError("freshness_s must be within (0, 3600]")

    normalized = {
        name: _component_status(
            name,
            components.get(name),
            now=now_v,
            freshness_s=freshness_v,
            required=required,
        )
        for name, required in _COMPONENTS.items()
    }
    route = _routing_status(routing, now=now_v, freshness_s=freshness_v)

    required_states = {
        item["state"] for item in normalized.values() if item["required"]
    }
    all_states = {item["state"] for item in normalized.values()}
    if "unavailable" in required_states:
        overall = "unavailable"
    elif required_states & {"unknown", "stale"} or route["state"] in {"unknown", "stale"}:
        overall = "unknown"
    elif route["state"] == "fallback" or all_states & {"unavailable", "unknown", "stale"}:
        overall = "attention"
    else:
        overall = "healthy"

    state_counts: dict[str, int] = {}
    for item in normalized.values():
        state_counts[item["state"]] = state_counts.get(item["state"], 0) + 1
    state_counts[route["state"]] = state_counts.get(route["state"], 0) + 1

    return {
        "schema": SCHEMA,
        "generated_at": now_v,
        "freshness_s": freshness_v,
        "overall": overall,
        "green": overall == "healthy",
        "components": normalized,
        "routing": route,
        "summary": {
            "states": dict(sorted(state_counts.items())),
            "required_failures": sorted(
                name
                for name, item in normalized.items()
                if item["required"] and item["state"] != "healthy"
            ),
        },
    }


def collect_control_center_status(
    component_providers: Mapping[str, Callable[[], Any]],
    routing_provider: Callable[[], Any] | None,
    *,
    now: float | None = None,
    freshness_s: float = DEFAULT_FRESHNESS_S,
) -> dict[str, Any]:
    """Collect sources fail-closed, without exposing exception messages."""
    raw: dict[str, Any] = {}
    for name in _COMPONENTS:
        provider = component_providers.get(name)
        if not callable(provider):
            raw[name] = None
            continue
        try:
            raw[name] = provider()
        except Exception as exc:
            raw[name] = {"detail": f"provider_error:{type(exc).__name__}"}

    route: Any = None
    if callable(routing_provider):
        try:
            route = routing_provider()
        except Exception as exc:
            route = {"detail": f"provider_error:{type(exc).__name__}"}

    return build_control_center_status(
        raw,
        route,
        now=now,
        freshness_s=freshness_s,
    )
