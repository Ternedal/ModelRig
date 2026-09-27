"""Loopback-only VisionRig projection for ModelRig Control Center.

Reads VisionRig's race-safe bootstrap snapshot and exposes only curated sensor
operational facts. No raw perception data or mutation authority crosses this
surface.
"""
from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

SCHEMA = "kaliv-control-center-vision/v1"
BOOTSTRAP_SCHEMA = "visionrig/sensor-bootstrap-snapshot/v6"
CATALOG_SCHEMA = "visionrig/sensor-catalog/v8"
FLEET_SCHEMA = "visionrig/sensor-fleet-summary/v6"
CONSISTENCY_SCHEMA = "visionrig/sensor-change-consistency/v1"


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
    parsed = parsed._replace(path=parsed.path.rstrip("/"))
    return parsed.geturl().rstrip("/")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bounded_str(value: Any, *, max_length: int = 256) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _sensor_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(raw.get("metadata"))
    discovery = _mapping(raw.get("discovery"))
    runtime = _mapping(raw.get("runtime"))
    control = _mapping(raw.get("control"))
    lifecycle = _mapping(raw.get("lifecycle"))
    packet = _mapping(runtime.get("packet_transport"))

    source_id = str(raw.get("source_id") or "").strip()
    capabilities = discovery.get("capabilities") or runtime.get("capabilities") or []
    if not isinstance(capabilities, (list, tuple)):
        capabilities = []

    presence = runtime.get("presence")
    if presence not in {"online", "stale", "offline"}:
        presence = "unknown"

    convergence = control.get("status")
    if convergence not in {"converged", "pending", "unknown"}:
        convergence = "unknown"

    desired_enabled = control.get("desired_enabled")
    if not isinstance(desired_enabled, bool):
        desired_enabled = bool(metadata.get("enabled", True))

    effective_capture = control.get("effective_capture_active")
    if not isinstance(effective_capture, bool):
        effective_capture = None

    lifecycle_status = lifecycle.get("status")
    if lifecycle_status not in {"active", "retired"}:
        lifecycle_status = "active"

    transport_status = packet.get("payload_status")
    if transport_status not in {"normal", "warning", "critical"}:
        transport_status = "unknown"

    capability_refresh_status = runtime.get("capability_refresh_status")
    if capability_refresh_status not in {"current", "stale"}:
        capability_refresh_status = "unknown"

    return {
        "source_id": source_id,
        "display_name": _bounded_str(metadata.get("display_name")),
        "location": _bounded_str(metadata.get("location")),
        "role": _bounded_str(metadata.get("role")),
        "source_type": _bounded_str(
            discovery.get("source_type") or runtime.get("source_type"),
            max_length=32,
        ) or "unknown",
        "device": _bounded_str(discovery.get("device") or runtime.get("device")),
        "capabilities": sorted({
            str(item).strip().lower()[:64]
            for item in capabilities
            if str(item).strip()
        }),
        "lifecycle": lifecycle_status,
        "presence": presence,
        "desired_enabled": desired_enabled,
        "effective_capture_active": effective_capture,
        "convergence": convergence,
        "desired_revision": int(control.get("desired_revision") or 0),
        "applied_revision": (
            int(control["applied_revision"])
            if isinstance(control.get("applied_revision"), int)
            else None
        ),
        "pending_seconds": (
            float(control["pending_seconds"])
            if isinstance(control.get("pending_seconds"), (int, float))
            else None
        ),
        "transport_status": transport_status,
        "payload_utilization": (
            float(packet["payload_utilization"])
            if isinstance(packet.get("payload_utilization"), (int, float))
            else None
        ),
        "capability_refresh_status": capability_refresh_status,
        "negotiated_max_payload_bytes": (
            int(runtime["negotiated_max_payload_bytes"])
            if isinstance(runtime.get("negotiated_max_payload_bytes"), int)
            else None
        ),
        "negotiated_packet_compression": _bounded_str(
            runtime.get("negotiated_packet_compression"),
            max_length=16,
        ),
        "negotiated_packet_target_utilization": (
            float(runtime["negotiated_packet_target_utilization"])
            if isinstance(
                runtime.get("negotiated_packet_target_utilization"),
                (int, float),
            )
            else None
        ),
        "last_seen_utc": _bounded_str(
            runtime.get("last_seen_utc") or discovery.get("last_seen_utc")
        ),
    }


def _count_map(value: Any, keys: tuple[str, ...]) -> dict[str, int]:
    raw = _mapping(value)
    return {
        key: int(raw.get(key) or 0)
        for key in keys
        if isinstance(raw.get(key, 0), int)
    }


async def build_control_center_vision() -> dict[str, Any]:
    """Return curated VisionRig state or a typed unavailable projection."""
    target = _visionrig_base_url() + "/api/v1/sensors/bootstrap"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(target)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise TypeError("bootstrap response is not an object")
        if payload.get("schema") != BOOTSTRAP_SCHEMA:
            raise ValueError("unsupported VisionRig bootstrap schema")

        catalog = _mapping(payload.get("catalog"))
        fleet = _mapping(payload.get("fleet"))
        consistency = _mapping(payload.get("change_consistency"))
        if catalog.get("schema") != CATALOG_SCHEMA:
            raise ValueError("unsupported VisionRig catalog schema")
        if fleet.get("schema") != FLEET_SCHEMA:
            raise ValueError("unsupported VisionRig fleet schema")
        if consistency.get("schema") != CONSISTENCY_SCHEMA:
            raise ValueError("unsupported VisionRig consistency schema")

        raw_sources = catalog.get("sources")
        if not isinstance(raw_sources, list):
            raise TypeError("catalog sources is not an array")
        sensors = [
            _sensor_projection(source)
            for source in raw_sources
            if isinstance(source, Mapping)
        ]
        sensors = [sensor for sensor in sensors if sensor["source_id"]]
        sensors.sort(key=lambda item: item["source_id"])

        consistency_status = consistency.get("status")
        if consistency_status not in {"synced", "registry_ahead", "journal_ahead"}:
            consistency_status = "unknown"

        return {
            "schema": SCHEMA,
            "available": True,
            "sensor_state_revision": int(payload.get("sensor_state_revision") or 0),
            "consistency": consistency_status,
            "total": int(fleet.get("total") or len(sensors)),
            "presence": _count_map(
                fleet.get("presence"),
                ("online", "stale", "offline", "unknown"),
            ),
            "control": _count_map(
                fleet.get("control"),
                ("converged", "pending", "unknown"),
            ),
            "transport": _count_map(
                fleet.get("transport"),
                ("normal", "warning", "critical", "unknown"),
            ),
            "capability_refresh": _count_map(
                fleet.get("capability_refresh"),
                ("current", "stale", "unknown"),
            ),
            "attention_total": int(fleet.get("attention_total") or 0),
            "attention_truncated": fleet.get("attention_truncated") is True,
            "sensors": sensors,
            "production_activation": False,
        }
    except Exception as exc:
        return {
            "schema": SCHEMA,
            "available": False,
            "reason": f"visionrig_unavailable:{type(exc).__name__}",
            "sensor_state_revision": None,
            "consistency": "unknown",
            "total": 0,
            "presence": {},
            "control": {},
            "transport": {},
            "capability_refresh": {},
            "attention_total": 0,
            "attention_truncated": False,
            "sensors": [],
            "production_activation": False,
        }
