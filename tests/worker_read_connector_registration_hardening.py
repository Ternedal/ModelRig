from __future__ import annotations

import os
from dataclasses import replace

from fastapi import FastAPI

from app import read_connector_tool as runtime_mod
from app import tools as tools_mod
from app.read_connector_package_contract import connectors

passed = failed = 0
TOOL_NAMES = {
    "google_calendar": "google_calendar_read",
    "google_drive": "google_drive_read",
    "gmail": "gmail_read",
    "notion": "notion_read",
}


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, expected, name: str, contains: str = "") -> None:
    try:
        fn()
    except expected as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


def route_count(app) -> int:
    return sum(
        1
        for route in getattr(app, "routes", ())
        if str(getattr(route, "path", "")).startswith("/read-connectors")
    )


saved_env = os.environ.get("KALIV_READ_CONNECTOR_PILOT")
saved_tools = {name: tools_mod.REGISTRY.get(name) for name in TOOL_NAMES.values()}
for name in TOOL_NAMES.values():
    tools_mod.REGISTRY.pop(name, None)
os.environ["KALIV_READ_CONNECTOR_PILOT"] = "1"

try:
    # A descriptor that only matches name/risk/impact/network/destination is not
    # this package. Old recognition accepted exactly that subset, so four wider
    # look-alikes could suppress the real registration as an idempotent reload.
    for connector in connectors():
        expected = runtime_mod._lazy_tool(connector)
        tools_mod.REGISTRY[TOOL_NAMES[connector]] = replace(
            expected,
            schedulable=True,
            unschedulable_because="",
            sensitivity="operational",
        )
    lookalike_snapshot = dict(tools_mod.REGISTRY)
    rejects(
        lambda: runtime_mod.register_read_connector_pilot(FastAPI()),
        RuntimeError,
        "look-alike connector tools are not accepted as this package",
        "another capability",
    )
    check(
        all(tools_mod.REGISTRY.get(name) is tool for name, tool in lookalike_snapshot.items()),
        "look-alike refusal mutates no registry entry",
    )

    for name in TOOL_NAMES.values():
        tools_mod.REGISTRY.pop(name, None)

    # Routes without tools are already a partial composition and must fail
    # closed rather than duplicating the operator surface and filling registry.
    route_only = FastAPI()
    route_only.include_router(runtime_mod.build_read_connector_router())
    before_routes = route_count(route_only)
    rejects(
        lambda: runtime_mod.register_read_connector_pilot(route_only),
        RuntimeError,
        "route-only partial composition fails closed",
        "operator routes",
    )
    check(
        all(name not in tools_mod.REGISTRY for name in TOOL_NAMES.values()),
        "route-only refusal leaves registry empty",
    )
    check(route_count(route_only) == before_routes, "route-only refusal adds no duplicate routes")

    # If mounting the router itself fails, no tool may become visible. Registry
    # mutation therefore happens only after include_router succeeds.
    class FailingApp:
        routes: list = []

        def include_router(self, router) -> None:
            del router
            raise RuntimeError("synthetic route mount failure")

    rejects(
        lambda: runtime_mod.register_read_connector_pilot(FailingApp()),
        RuntimeError,
        "route-mount failure propagates",
        "synthetic route mount failure",
    )
    check(
        all(name not in tools_mod.REGISTRY for name in TOOL_NAMES.values()),
        "route-mount failure leaves zero connector tools",
    )

    # Global Tool registry may survive while a fresh FastAPI app is composed in
    # the same process. Recognized tools alone are not proof that THIS app has
    # the loopback operator routes; the second app must receive them once.
    app_one = FastAPI()
    check(runtime_mod.register_read_connector_pilot(app_one) is True, "first app composes full package")
    check(route_count(app_one) > 0, "first app has connector operator routes")
    tool_objects = {name: tools_mod.REGISTRY[name] for name in TOOL_NAMES.values()}

    app_two = FastAPI()
    check(
        runtime_mod.register_read_connector_pilot(app_two) is True,
        "fresh app mounts routes for recognized global tools",
    )
    check(route_count(app_two) > 0, "fresh app receives connector operator routes")
    check(
        all(tools_mod.REGISTRY.get(name) is tool for name, tool in tool_objects.items()),
        "fresh app route composition does not replace recognized tools",
    )
    second_routes = route_count(app_two)
    check(
        runtime_mod.register_read_connector_pilot(app_two) is False,
        "repeat composition on same app is idempotent",
    )
    check(route_count(app_two) == second_routes, "repeat composition adds no routes")
finally:
    for name in TOOL_NAMES.values():
        tools_mod.REGISTRY.pop(name, None)
    for name, value in saved_tools.items():
        if value is not None:
            tools_mod.REGISTRY[name] = value
    if saved_env is None:
        os.environ.pop("KALIV_READ_CONNECTOR_PILOT", None)
    else:
        os.environ["KALIV_READ_CONNECTOR_PILOT"] = saved_env

print(f"===== T-037 REGISTRATION HARDENING: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
