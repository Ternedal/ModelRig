"""Loopback-only VisionRig projection for ModelRig Control Center.

This module normalizes VisionRig's sensor catalog into a stable Kaliv/ModelRig
contract. It is observation-only: sensor mutations remain outside the worker's
Control Center read surface.
"""
from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

SCHEMA = "kaliv-control-center-vision/v1"
VISIONRIG_CATALOG_SCHEMA = "visionrig/sensor-catalog/v4"


def _visionrig_base_url() -> str:
    raw = os.getenv("KALIV_VISIONRIG_URL", "http://127.0.0.1:8110").strip()
    parsed = urlparse(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid VisionRig URL")
    host = parsed.hostname.lower()
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if not loopback:
        raise ValueError("VisionRig URL must be loopback")
    return raw.rstrip("/")


def _as_dict(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sensor_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _as_dict(raw.get("metadata"))
    discovery = _as_dict(raw.get("discovery"))
    runtime = _as_dict(raw.get("runtime"))
    control = _as_dict(raw.get("control"))

    source_id = str(raw.get("source_id") or "").strip()
    source_type = str(
        discovery.get("source_type")
        or runtime.get("source_type")
        or "unknown"
    ).strip()
    device = discovery.get("device") or runtime.get("device")
    capabilities = discovery.get("capabilities") or runtime.get("capabilities") or []
    if not isinstance(capabilities, (list, tuple)):
        capabilities = []

    presence = runtime.get("presence")
    if presence not in {"online", "stale", "offline"}:
        presence = "offline" if discovery else "unknown"

    desired_enabled = control.get("desired_enabled")
    if not isinstance(desired_enabled, bool):
        desired_enabled = bool(metadata.get("enabled", True))

    effective = control.get("effective_capture_active")
    if not isinstance(effective, bool):
        effective = None

    convergence = control.get("status")
    if convergence not in {"converged", "pending", "unknown"}:
        convergence = "unknown"

    return {
        "source_id": source_id,
        "display_name": (
            str(metadata.get("display_name")).strip()
            if metadata.get("display_name")
            else None
        ),
        "location": (
            str(metadata.get("location")).strip()
            if metadata.get("location")
            else None
        ),
        "role": str(metadata.get("role")).strip() if metadata.get("role") else None,
        "source_type": source_type,
        "device": str(device).strip() if device else None,
        "capabilities": sorted(
            {
                str(item).strip().lower()
                for item in capabilities
                if str(item).strip()
            }
        ),
        "presence": presence,
        "desired_enabled": desired_enabled,
        "effective_capture_active": effective,
        "convergence": convergence,
        "first_seen_utc": discovery.get("first_seen_utc"),
        "last_seen_utc": discovery.get("last_seen_utc"),
        "runtime_last_seen_utc": runtime.get("last_seen_utc"),
        "observation_count": int(discovery.get("observation_count") or 0),
    }


async def build_control_center_vision() -> dict[str, Any]:
    """Read and normalize VisionRig without exposing raw perception data."""
    target = _visionrig_base_url() + "/api/v1/sensors/catalog"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(target)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise TypeError("catalog response is not an object")
        if payload.get("schema") != VISIONRIG_CATALOG_SCHEMA:
            raise ValueError("unsupported VisionRig catalog schema")
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            raise TypeError("catalog sources is not an array")
        sensors = [
            _sensor_projection(source)
            for source in raw_sources
            if isinstance(source, Mapping)
        ]
        sensors = [sensor for sensor in sensors if sensor["source_id"]]
        sensors.sort(key=lambda item: item["source_id"])
        return {
            "schema": SCHEMA,
            "available": True,
            "sensors": sensors,
            "production_activation": False,
        }
    except Exception as exc:
        return {
            "schema": SCHEMA,
            "available": False,
            "reason": f"visionrig_unavailable:{type(exc).__name__}",
            "sensors": [],
            "production_activation": False,
        }
