#!/usr/bin/env python3
"""Bounded VisionRig Control Center projection contract."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app import control_center_vision as vision  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def source(index: int) -> dict:
    return {
        "source_id": f"sensor-{index:03d}",
        "metadata": {
            "display_name": f"Sensor {index}",
            "enabled": True,
        },
        "discovery": {
            "source_type": "camera",
            "capabilities": [f"cap-{n:03d}" for n in range(64)],
            "observation_count": 1,
        },
        "runtime": {
            "presence": "online",
            "capability_refresh_status": "current",
            "packet_transport": {"payload_status": "normal"},
        },
        "control": {
            "status": "converged",
            "desired_enabled": True,
            "effective_capture_active": True,
            "desired_revision": 1,
            "applied_revision": 1,
        },
        "lifecycle": {"status": "active"},
    }


PAYLOAD = {
    "schema": vision.BOOTSTRAP_SCHEMA,
    "sensor_state_revision": 9,
    "catalog": {
        "schema": vision.CATALOG_SCHEMA,
        "sources": [source(i) for i in range(140)],
    },
    "fleet": {
        "schema": vision.FLEET_SCHEMA,
        "total": 140,
        "presence": {"online": 140},
        "control": {"converged": 140},
        "transport": {"normal": 140},
        "capability_refresh": {"current": 140},
        "attention_total": 0,
        "attention_truncated": False,
        "producer_readiness": {
            "runtime_sources": 140,
            "heartbeat_v6_sources": 126,
            "heartbeat_upgrade_required": 14,
            "heartbeat_v6_ratio": 0.9,
            "packet_measurement_complete_sources": 119,
            "packet_measurement_gap_sources": 21,
            "packet_measurement_complete_ratio": 0.85,
        },
        "producer_readiness_transition": {
            "previous": None,
            "changed_utc": "2026-09-28T05:00:00+00:00",
            "heartbeat_v6_sources_delta": 4,
            "heartbeat_v6_ratio_delta": 0.03,
            "packet_measurement_complete_sources_delta": 7,
            "packet_measurement_complete_ratio_delta": 0.05,
        },
    },
    "change_consistency": {
        "schema": vision.CONSISTENCY_SCHEMA,
        "status": "synced",
    },
}


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return PAYLOAD


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, _target: str) -> FakeResponse:
        return FakeResponse()


async def run() -> None:
    original = vision.httpx.AsyncClient
    vision.httpx.AsyncClient = FakeClient
    try:
        payload = await vision.build_control_center_vision()
    finally:
        vision.httpx.AsyncClient = original

    check(payload["available"] is True, "projection remains available")
    check(payload["total"] == 140, "full fleet total remains visible")
    check(payload["sensors_returned"] == 128, "projection caps sensors at 128")
    check(payload["sensors_truncated"] is True, "projection marks truncation explicitly")
    check(len(payload["sensors"]) == 128, "only bounded sensors cross Control Center")
    check(
        all(len(item["capabilities"]) <= 32 for item in payload["sensors"]),
        "each sensor capability list is bounded",
    )
    check(
        all(len(item["source_id"]) <= 128 for item in payload["sensors"]),
        "source identifiers are bounded",
    )
    check(
        payload["visionrig_schema_versions"] == {
            "bootstrap": 31,
            "catalog": 15,
            "fleet": 28,
        },
        "actual VisionRig schema versions remain visible",
    )
    check(
        payload["producer_readiness"]["heartbeat_v6_ratio"] == 0.9,
        "heartbeat v6 readiness crosses Control Center",
    )
    check(
        payload["producer_readiness"]["packet_measurement_complete_ratio"] == 0.85,
        "packet measurement readiness crosses Control Center",
    )
    check(
        payload["producer_readiness_transition"]["heartbeat_v6_sources_delta"] == 4,
        "readiness transition delta crosses Control Center",
    )
    check(payload["production_activation"] is False, "read projection cannot activate production")

    future = {
        **PAYLOAD,
        "schema": "visionrig/sensor-bootstrap-snapshot/v32",
        "catalog": {**PAYLOAD["catalog"], "schema": "visionrig/sensor-catalog/v16"},
        "fleet": {**PAYLOAD["fleet"], "schema": "visionrig/sensor-fleet-summary/v29"},
    }

    class FutureResponse(FakeResponse):
        def json(self) -> dict:
            return future

    class FutureClient(FakeClient):
        async def get(self, _target: str) -> FutureResponse:
            return FutureResponse()

    vision.httpx.AsyncClient = FutureClient
    try:
        future_payload = await vision.build_control_center_vision()
    finally:
        vision.httpx.AsyncClient = original
    check(
        future_payload["available"] is True,
        "additive future VisionRig schema versions remain compatible",
    )
    check(
        future_payload["visionrig_schema_versions"]["bootstrap"] == 32,
        "future bootstrap version is surfaced",
    )


if __name__ == "__main__":
    asyncio.run(run())
    print(f"\n===== CONTROL CENTER VISION: {passed} passed, {failed} failed =====")
    raise SystemExit(1 if failed else 0)
