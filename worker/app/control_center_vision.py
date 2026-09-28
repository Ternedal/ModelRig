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
BOOTSTRAP_SCHEMA = "visionrig/sensor-bootstrap-snapshot/v31"
CATALOG_SCHEMA = "visionrig/sensor-catalog/v15"
FLEET_SCHEMA = "visionrig/sensor-fleet-summary/v28"
BOOTSTRAP_SCHEMA_MIN_VERSION = 6
CATALOG_SCHEMA_MIN_VERSION = 8
FLEET_SCHEMA_MIN_VERSION = 6
CONSISTENCY_SCHEMA = "visionrig/sensor-change-consistency/v1"
MAX_SENSORS = 128
MAX_CAPABILITIES_PER_SENSOR = 32


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


def _require_compatible_schema(
    value: Any,
    *,
    family: str,
    min_version: int,
) -> int:
    text = str(value or "").strip()
    prefix = family + "/v"
    if not text.startswith(prefix):
        raise ValueError(f"unsupported {family} schema")
    suffix = text[len(prefix):]
    if not suffix.isdigit():
        raise ValueError(f"unsupported {family} schema")
    version = int(suffix)
    if version < min_version:
        raise ValueError(f"unsupported {family} schema")
    return version


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

    source_id = str(raw.get("source_id") or "").strip()[:128]
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
        })[:MAX_CAPABILITIES_PER_SENSOR],
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
        "first_seen_utc": _bounded_str(discovery.get("first_seen_utc")),
        "observation_count": (
            int(discovery.get("observation_count"))
            if isinstance(discovery.get("observation_count"), int)
            else 0
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
        bootstrap_version = _require_compatible_schema(
            payload.get("schema"),
            family="visionrig/sensor-bootstrap-snapshot",
            min_version=BOOTSTRAP_SCHEMA_MIN_VERSION,
        )

        catalog = _mapping(payload.get("catalog"))
        fleet = _mapping(payload.get("fleet"))
        consistency = _mapping(payload.get("change_consistency"))
        catalog_version = _require_compatible_schema(
            catalog.get("schema"),
            family="visionrig/sensor-catalog",
            min_version=CATALOG_SCHEMA_MIN_VERSION,
        )
        fleet_version = _require_compatible_schema(
            fleet.get("schema"),
            family="visionrig/sensor-fleet-summary",
            min_version=FLEET_SCHEMA_MIN_VERSION,
        )
        if consistency.get("schema") != CONSISTENCY_SCHEMA:
            raise ValueError("unsupported VisionRig consistency schema")

        raw_sources = catalog.get("sources")
        if not isinstance(raw_sources, list):
            raise TypeError("catalog sources is not an array")
        bounded_sources = [
            source
            for source in raw_sources
            if isinstance(source, Mapping)
            and str(source.get("source_id") or "").strip()
        ]
        bounded_sources.sort(
            key=lambda source: str(source.get("source_id") or "").strip()
        )
        catalog_total = len(bounded_sources)
        sensors = [
            _sensor_projection(source)
            for source in bounded_sources[:MAX_SENSORS]
        ]
        sensors = [sensor for sensor in sensors if sensor["source_id"]]

        consistency_status = consistency.get("status")
        if consistency_status not in {"synced", "registry_ahead", "journal_ahead"}:
            consistency_status = "unknown"

        readiness_raw = _mapping(fleet.get("producer_readiness"))
        transition_raw = _mapping(fleet.get("producer_readiness_transition"))

        def ratio(name: str) -> float | None:
            value = readiness_raw.get(name)
            if not isinstance(value, (int, float)):
                return None
            number = float(value)
            if not 0.0 <= number <= 1.0:
                return None
            return number

        producer_readiness = {
            "runtime_sources": int(readiness_raw.get("runtime_sources") or 0),
            "heartbeat_v6_sources": int(
                readiness_raw.get("heartbeat_v6_sources") or 0
            ),
            "heartbeat_upgrade_required": int(
                readiness_raw.get("heartbeat_upgrade_required") or 0
            ),
            "heartbeat_v6_ratio": ratio("heartbeat_v6_ratio"),
            "packet_measurement_complete_sources": int(
                readiness_raw.get("packet_measurement_complete_sources") or 0
            ),
            "packet_measurement_gap_sources": int(
                readiness_raw.get("packet_measurement_gap_sources") or 0
            ),
            "packet_measurement_complete_ratio": ratio(
                "packet_measurement_complete_ratio"
            ),
        }
        producer_readiness_transition = {
            "changed_utc": _bounded_str(transition_raw.get("changed_utc")),
            "heartbeat_v6_sources_delta": (
                int(transition_raw["heartbeat_v6_sources_delta"])
                if isinstance(
                    transition_raw.get("heartbeat_v6_sources_delta"),
                    int,
                )
                else None
            ),
            "heartbeat_v6_ratio_delta": (
                float(transition_raw["heartbeat_v6_ratio_delta"])
                if isinstance(
                    transition_raw.get("heartbeat_v6_ratio_delta"),
                    (int, float),
                )
                else None
            ),
            "packet_measurement_complete_sources_delta": (
                int(transition_raw["packet_measurement_complete_sources_delta"])
                if isinstance(
                    transition_raw.get("packet_measurement_complete_sources_delta"),
                    int,
                )
                else None
            ),
            "packet_measurement_complete_ratio_delta": (
                float(transition_raw["packet_measurement_complete_ratio_delta"])
                if isinstance(
                    transition_raw.get("packet_measurement_complete_ratio_delta"),
                    (int, float),
                )
                else None
            ),
        }

        return {
            "schema": SCHEMA,
            "available": True,
            "visionrig_schema_versions": {
                "bootstrap": bootstrap_version,
                "catalog": catalog_version,
                "fleet": fleet_version,
            },
            "sensor_state_revision": int(payload.get("sensor_state_revision") or 0),
            "consistency": consistency_status,
            "total": int(fleet.get("total") or catalog_total),
            "sensors_returned": len(sensors),
            "sensors_truncated": catalog_total > len(sensors),
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
            "producer_readiness": producer_readiness,
            "producer_readiness_transition": producer_readiness_transition,
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
            "sensors_returned": 0,
            "sensors_truncated": False,
            "presence": {},
            "control": {},
            "transport": {},
            "capability_refresh": {},
            "attention_total": 0,
            "attention_truncated": False,
            "visionrig_schema_versions": None,
            "producer_readiness": {
                "runtime_sources": 0,
                "heartbeat_v6_sources": 0,
                "heartbeat_upgrade_required": 0,
                "heartbeat_v6_ratio": None,
                "packet_measurement_complete_sources": 0,
                "packet_measurement_gap_sources": 0,
                "packet_measurement_complete_ratio": None,
            },
            "producer_readiness_transition": {
                "changed_utc": None,
                "heartbeat_v6_sources_delta": None,
                "heartbeat_v6_ratio_delta": None,
                "packet_measurement_complete_sources_delta": None,
                "packet_measurement_complete_ratio_delta": None,
            },
            "sensors": [],
            "production_activation": False,
        }
