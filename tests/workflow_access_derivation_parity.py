#!/usr/bin/env python3
"""All capability validators must derive confirmation from the same two axes.

A public-network read changes no local state, but it transmits an exact request
to a third party. ToolGate already cards that action. The versioned descriptor,
backend and both clients must therefore agree that confirmation is required
when either access is not read OR network.mode is public.

Run: python3 tests/workflow_access_derivation_parity.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SOURCES = {
    "go": ROOT / "backend/internal/capabilityschema/schema.go",
    "python": ROOT / "worker/app/capability_schema.py",
    "kotlin-android": ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/CapabilityDescriptorV2.kt",
    "kotlin-desktop": ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/CapabilityDescriptorV2.kt",
}

#: Forbidden form: enumerating only today's dangerous access values. A future
#: class would fall through confirmation-free.
ENUMERATED = re.compile(
    r'(?:access|Access)\b.{0,30}"write".{0,30}"desktop"', re.I)

PUBLIC_NETWORK_NEEDLES = {
    "go": 'd.Access != "read" || d.Network.Mode == "public"',
    "python": 'access != "read" or network_mode == "public"',
    "kotlin-android": 'access != "read" || network.mode == "public"',
    "kotlin-desktop": 'access != "read" || network.mode == "public"',
}

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


for name, path in SOURCES.items():
    check(path.is_file(), f"{name}: source exists")

# Keep the original fail-closed access-enum mutation detector.
offenders = []
for name, path in SOURCES.items():
    if not path.is_file():
        continue
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(("//", "#", "*")):
            continue
        if not ENUMERATED.search(line):
            continue
        if '"read"' in line:  # enum declaration, not a derivation
            continue
        offenders.append((name, line.strip()[:60]))

check(
    not offenders,
    "no validator derives confirmation from an enumeration of dangerous access values "
    f"({offenders or 'none'})",
)
check(
    bool(ENUMERATED.search('if d.Access == "write" || d.Access == "desktop" {')),
    "self-test: detector catches the known fail-open access form",
)
check(
    not ENUMERATED.search('if d.Access != "read" {'),
    "self-test: fail-closed access form is not an offence",
)

# Pin the orthogonal public-network rule in every implementation.
for name, path in SOURCES.items():
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    check(
        PUBLIC_NETWORK_NEEDLES[name] in text,
        f"{name}: confirmation derivation includes public network",
    )
    check(
        "confirmation mode contradicts access/network" in text,
        f"{name}: contradiction names both contract axes",
    )

# Functional proof at the producer/execution boundary, not source text alone.
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

print(f"\naccess/network confirmation parity: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
