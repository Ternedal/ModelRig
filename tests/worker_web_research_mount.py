#!/usr/bin/env python3
"""The web-research flag exposes exactly one surface: ToolGate.

D7 selected ``web_research`` in REGISTRY as the canonical production caller.
The old ``/research/fetch`` placeholder route must therefore stay absent even
when the feature flag is enabled.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-wrm-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import tools  # noqa: E402
from app.web_research_mount import (  # noqa: E402
    WEB_RESEARCH_FLAG,
    mount_web_research,
    web_research_enabled,
)
from app.web_research_tool import TOOL_NAME  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def paths(app: FastAPI) -> set[str]:
    return set(app.openapi().get("paths", {}))


saved_flag = os.environ.get(WEB_RESEARCH_FLAG)
saved_tool = tools.REGISTRY.get(TOOL_NAME)
try:
    tools.REGISTRY.pop(TOOL_NAME, None)

    os.environ.pop(WEB_RESEARCH_FLAG, None)
    app = FastAPI()
    check(web_research_enabled() is False, "without flag the surface is off")
    check(mount_web_research(app) is False, "mount refuses without opt-in")
    check(TOOL_NAME not in tools.REGISTRY, "ToolGate caller stays absent")
    check("/research/fetch" not in paths(app), "legacy HTTP route stays absent")

    for value in ("", "0", "true", "yes", "on", " 1 x", "TRUE"):
        os.environ[WEB_RESEARCH_FLAG] = value
        check(web_research_enabled() is False, f"flag={value!r} is not opt-in")

    os.environ[WEB_RESEARCH_FLAG] = "1"
    app = FastAPI()
    check(web_research_enabled() is True, "flag=1 is explicit opt-in")
    check(mount_web_research(app) is True, "mount succeeds with opt-in")
    check(TOOL_NAME in tools.REGISTRY, "canonical ToolGate caller is registered")
    check("/research/fetch" not in paths(app), "no parallel research endpoint is mounted")
    with TestClient(app) as client:
        check(client.post("/research/fetch").status_code == 404, "legacy route remains 404")

    before_routes = len(app.routes)
    before_tool = tools.REGISTRY[TOOL_NAME]
    check(mount_web_research(app) is True, "repeated mount remains successful")
    check(len(app.routes) == before_routes, "repeated mount adds no routes")
    check(tools.REGISTRY[TOOL_NAME] is before_tool, "repeated mount keeps one tool registration")
finally:
    tools.REGISTRY.pop(TOOL_NAME, None)
    if saved_tool is not None:
        tools.REGISTRY[TOOL_NAME] = saved_tool
    if saved_flag is None:
        os.environ.pop(WEB_RESEARCH_FLAG, None)
    else:
        os.environ[WEB_RESEARCH_FLAG] = saved_flag

print(f"\nweb research mount guard: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
