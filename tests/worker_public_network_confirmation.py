#!/usr/bin/env python3
"""Public-network reads require the same confirmation in every contract layer.

A public read changes no local state, but it transmits an exact request to a
third party. ToolGate already treats that as confirmable. This gate prevents the
versioned capability descriptor, backend and either client from advertising the
same action as confirmation-free.

Run: python3 tests/worker_public_network_confirmation.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_tmp = tempfile.mkdtemp(prefix="kaliv-public-network-confirmation-")
os.environ.setdefault("KALIV_AUDIT_DB", str(Path(_tmp) / "audit.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", str(Path(_tmp) / "tools.json"))
os.environ.setdefault("KALIV_JOBS_DB", str(Path(_tmp) / "jobs.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _tmp)
sys.path.insert(0, str(ROOT / "worker"))

from app import tools  # noqa: E402
from app.capability_schema import (  # noqa: E402
    CapabilitySchemaError,
    descriptor_from_tool,
    expected_confirmation_mode,
    parse_descriptor,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


public_read = tools.Tool(
    name="public_read_probe",
    risk="read",
    description="Fetch a public resource for the contract probe.",
    network="public",
    network_destinations=("example.test",),
)
configured_read = tools.Tool(
    name="configured_read_probe",
    risk="read",
    description="Read from an operator-configured service.",
    network="configured_service",
    network_destinations=("service",),
)

check(
    tools.requires_confirmation(public_read, "local"),
    "ToolGate requires confirmation for a public-network read",
)
check(
    not tools.requires_confirmation(configured_read, "local"),
    "configured-service read keeps the existing confirmation-free contract",
)
check(
    expected_confirmation_mode("read", "public") == "required",
    "descriptor derivation requires confirmation for public reads",
)
check(
    expected_confirmation_mode("read", "configured_service") == "none",
    "descriptor derivation does not broaden every networked read",
)

public_descriptor = descriptor_from_tool(public_read)
check(
    public_descriptor.access == "read"
    and public_descriptor.network.mode == "public"
    and public_descriptor.confirmation.mode == "required",
    "producer preserves read/public while advertising the required card",
)
check(
    parse_descriptor(public_descriptor.to_dict()) == public_descriptor,
    "a correctly confirmed public-read descriptor round-trips",
)

contradiction = public_descriptor.to_dict()
contradiction["confirmation"] = {"mode": "none"}
try:
    parse_descriptor(contradiction)
except CapabilitySchemaError:
    check(True, "Python parser rejects public read plus confirmation=none")
else:
    check(False, "Python parser accepted public read plus confirmation=none")

sources = {
    "go": ROOT / "backend/internal/capabilityschema/schema.go",
    "android": ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/CapabilityDescriptorV2.kt",
    "desktop": ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/CapabilityDescriptorV2.kt",
}
needles = {
    "go": 'd.Access != "read" || d.Network.Mode == "public"',
    "android": 'access != "read" || network.mode == "public"',
    "desktop": 'access != "read" || network.mode == "public"',
}
for name, path in sources.items():
    text = path.read_text(encoding="utf-8")
    check(
        needles[name] in text,
        f"{name} validator derives confirmation from access and public network",
    )
    check(
        "confirmation mode contradicts access/network" in text,
        f"{name} reports the two-axis contradiction explicitly",
    )

print(f"\n===== PUBLIC NETWORK CONFIRMATION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
