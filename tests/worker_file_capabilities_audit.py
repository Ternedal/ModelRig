#!/usr/bin/env python3
"""T-035 audit regression: private file content must not enter ToolGate audit."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "worker"))

from app import tools  # noqa: E402
from app.file_capabilities import (  # noqa: E402
    FILE_CAPABILITIES_FLAG,
    FILE_WORKSPACE_ID_ENV,
    FILE_WORKSPACE_ROOT_ENV,
    TOOL_ISOLATION_ENV,
    _run_file_read,
    _run_file_search,
)
from app.file_capabilities_mount import mount_file_capabilities  # noqa: E402
from fastapi import FastAPI  # noqa: E402

PASSED = 0
FAILED = 0
TOOL_NAMES = ("file_read", "file_list", "file_search")
ENV_NAMES = (
    FILE_CAPABILITIES_FLAG,
    FILE_WORKSPACE_ID_ENV,
    FILE_WORKSPACE_ROOT_ENV,
    TOOL_ISOLATION_ENV,
)
OLD_ENV = {name: os.environ.get(name) for name in ENV_NAMES}
OLD_AUDIT = tools.GATE.audit


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def remove_tools() -> None:
    for name in TOOL_NAMES:
        tools.REGISTRY.pop(name, None)


try:
    with tempfile.TemporaryDirectory() as root_raw, tempfile.TemporaryDirectory() as state_raw:
        root = pathlib.Path(root_raw)
        secret_marker = "PRIVATE_FILE_TEXT_MUST_NEVER_REACH_AUDIT"
        search_marker = "PRIVATE_SEARCH_QUERY_MUST_NEVER_REACH_AUDIT"
        (root / "private.txt").write_text(
            f"prefix {secret_marker} suffix\ncontains needle too\n", encoding="utf-8"
        )

        os.environ[FILE_CAPABILITIES_FLAG] = "1"
        os.environ[TOOL_ISOLATION_ENV] = "process"
        os.environ[FILE_WORKSPACE_ID_ENV] = "audit-demo"
        os.environ[FILE_WORKSPACE_ROOT_ENV] = str(root.resolve())

        audit_path = str(pathlib.Path(state_raw) / "audit.db")
        tools.GATE.audit = tools.AuditLog(audit_path)
        remove_tools()
        app = FastAPI()
        check(mount_file_capabilities(app) is True, "mount installs file audit boundary")

        read_result = _run_file_read({"path": "private.txt"})
        tools.GATE.audit.record(
            tool="file_read",
            args={"path": "private.txt"},
            risk="read",
            outcome="executed",
            result_summary=read_result,
            origin="local",
        )

        search_result = _run_file_search({"query": search_marker, "path": ""})
        tools.GATE.audit.record(
            tool="file_search",
            args={"query": search_marker, "path": "", "max_results": 5},
            risk="read",
            outcome="executed",
            result_summary=search_result,
            origin="local",
        )

        rows = tools.GATE.audit.recent(10)
        encoded = json.dumps(rows, ensure_ascii=False)
        check(secret_marker not in encoded, "file_read content is absent from audit")
        check(search_marker not in encoded, "file_search plaintext query is absent from audit")
        check("query_sha256" in encoded and "query_length" in encoded,
              "search audit retains bounded query identity without plaintext")
        check("workspace=audit-demo operation=read" in encoded,
              "read audit keeps non-content workspace/operation summary")
        check("workspace=audit-demo operation=search" in encoded,
              "search audit keeps non-content workspace/operation summary")
        check("private.txt" in encoded,
              "relative path authority remains auditable without absolute root")
        check(str(root) not in encoded, "absolute workspace root is absent from audit")

        # Malformed results must fail safe: never copy arbitrary text because a
        # parser or future tool version drifted.
        malformed_marker = "MALFORMED_PRIVATE_PAYLOAD_MUST_NOT_BE_LOGGED"
        tools.GATE.audit.record(
            tool="file_read",
            args={"path": "private.txt"},
            risk="read",
            outcome="executed",
            result_summary=malformed_marker,
            origin="local",
        )
        latest = json.dumps(tools.GATE.audit.recent(1), ensure_ascii=False)
        check(malformed_marker not in latest and "unparseable" in latest,
              "unparseable file result is redacted fail-safe")

finally:
    remove_tools()
    tools.GATE.audit = OLD_AUDIT
    for name, value in OLD_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

print(f"\n===== T-035 FILE AUDIT: {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
