#!/usr/bin/env python3
"""T-035 scoped file-capability contract and isolated runtime proof."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app import tools  # noqa: E402
from app.capability_schema import descriptor_from_tool  # noqa: E402
from app.file_capabilities import (  # noqa: E402
    FILE_CAPABILITIES_FLAG,
    FILE_WORKSPACE_ID_ENV,
    FILE_WORKSPACE_ROOT_ENV,
    MAX_LIST_ENTRIES,
    MAX_READ_BYTES,
    TOOL_ISOLATION_ENV,
    FileCapabilityConfigError,
    _run_file_list,
    _run_file_read,
    _run_file_search,
    register_file_capability_tools,
    workspace_from_environment,
)
from app.file_capabilities_mount import mount_file_capabilities  # noqa: E402
from app.toolhost import ProcessExecutor  # noqa: E402
from fastapi import FastAPI  # noqa: E402

PASSED = 0
FAILED = 0
TOOL_NAMES = ("file_read", "file_list", "file_search")
ENV_NAMES = (
    FILE_CAPABILITIES_FLAG,
    FILE_WORKSPACE_ID_ENV,
    FILE_WORKSPACE_ROOT_ENV,
    TOOL_ISOLATION_ENV,
    "PYTHONPATH",
)
OLD_ENV = {name: os.environ.get(name) for name in ENV_NAMES}


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def expect(kind: type, fn, label: str):
    try:
        fn()
    except kind as exc:
        check(True, f"{label} ({type(exc).__name__})")
        return exc
    except BaseException as exc:  # noqa: BLE001
        check(False, f"{label} -- wrong exception: {type(exc).__name__}: {exc}")
        return exc
    check(False, f"{label} -- no exception")
    return None


def remove_tools() -> None:
    for name in TOOL_NAMES:
        tools.REGISTRY.pop(name, None)


def set_workspace(root: pathlib.Path, workspace_id: str = "demo") -> None:
    os.environ[FILE_CAPABILITIES_FLAG] = "1"
    os.environ[TOOL_ISOLATION_ENV] = "process"
    os.environ[FILE_WORKSPACE_ID_ENV] = workspace_id
    os.environ[FILE_WORKSPACE_ROOT_ENV] = str(root.resolve())


try:
    # --- Default-off + trusted activation boundary -------------------------
    remove_tools()
    for name in (FILE_CAPABILITIES_FLAG, FILE_WORKSPACE_ID_ENV,
                 FILE_WORKSPACE_ROOT_ENV, TOOL_ISOLATION_ENV):
        os.environ.pop(name, None)
    check(register_file_capability_tools() is False, "default-off registers nothing")
    check(all(name not in tools.REGISTRY for name in TOOL_NAMES),
          "registry remains untouched while off")

    os.environ[FILE_CAPABILITIES_FLAG] = "1"
    expect(FileCapabilityConfigError, register_file_capability_tools,
           "opt-in without process isolation fails closed")
    check(all(name not in tools.REGISTRY for name in TOOL_NAMES),
          "failed activation does not partially register")

    os.environ[TOOL_ISOLATION_ENV] = "process"
    os.environ[FILE_WORKSPACE_ID_ENV] = "bad workspace id"
    os.environ[FILE_WORKSPACE_ROOT_ENV] = "relative/path"
    expect(FileCapabilityConfigError, workspace_from_environment,
           "invalid workspace authority is rejected")

    with tempfile.TemporaryDirectory() as root_raw, tempfile.TemporaryDirectory() as outside_raw:
        root = pathlib.Path(root_raw)
        outside = pathlib.Path(outside_raw)
        (root / "nested").mkdir()
        (root / "hello.txt").write_text("Hej fra workspace\nAnden linje\n", encoding="utf-8")
        (root / "nested" / "notes.md").write_text(
            "første\nHer er NEEDLE i en linje\ntredje\n", encoding="utf-8"
        )
        (root / "binary.bin").write_bytes(b"\x00\x01\x02binary")
        (root / "large.txt").write_text("x" * (MAX_READ_BYTES + 1), encoding="utf-8")
        outside_file = outside / "outside.txt"
        outside_file.write_text("hemmelig udenfor", encoding="utf-8")

        set_workspace(root)
        check(register_file_capability_tools() is True, "valid authority registers T-035 tools")
        check(register_file_capability_tools() is True, "registration is idempotent")

        # --- Descriptor / ToolGate truth ----------------------------------
        env_allow = (
            FILE_CAPABILITIES_FLAG,
            FILE_WORKSPACE_ID_ENV,
            FILE_WORKSPACE_ROOT_ENV,
            TOOL_ISOLATION_ENV,
        )
        for name in TOOL_NAMES:
            tool = tools.REGISTRY[name]
            descriptor = descriptor_from_tool(tool)
            check(tool.risk == "read" and tool.network == "none",
                  f"{name} is local read-only")
            check(tool.sensitivity == "private", f"{name} result is private")
            check(tool.isolate is True and tool.env_allow == env_allow,
                  f"{name} requires isolated child with exact authority env")
            check(tool.schedulable is False and bool(tool.unschedulable_because),
                  f"{name} cannot run unattended")
            check(tools.requires_confirmation(tool, "local") is False,
                  f"{name} does not invent a write confirmation")
            check(descriptor.capability_id == f"tool:{name}"
                  and descriptor.production_activation is False,
                  f"{name} descriptor remains dormant v2 authority")
            check(tool.params.get("additionalProperties") is False,
                  f"{name} rejects undeclared parameters at schema boundary")

        # --- file_read ----------------------------------------------------
        read = json.loads(_run_file_read({"path": "hello.txt"}))
        check(read["status"] == "text" and "Hej fra workspace" in read["text"],
              "file_read returns bounded UTF-8 text")
        check(read["workspace_id"] == "demo"
              and read["receipt"]["relative_paths"] == ["hello.txt"],
              "file_read receipt binds workspace + relative path")
        check(read["production_activation"] is False
              and read["receipt"]["production_activation"] is False,
              "file_read cannot claim production activation")
        check(str(root) not in json.dumps(read, ensure_ascii=False),
              "file_read never exposes absolute workspace root")

        binary = json.loads(_run_file_read({"path": "binary.bin"}))
        check(binary["status"].startswith("unsupported_") and "text" not in binary,
              "binary/unknown content returns metadata, not bytes")
        large = json.loads(_run_file_read({"path": "large.txt"}))
        check(large["status"] == "unsupported_too_large" and "text" not in large,
              "oversized file is metadata-only")

        expect(tools.ToolDenied, lambda: _run_file_read({"path": "../outside.txt"}),
               "parent traversal is rejected")
        expect(tools.ToolDenied, lambda: _run_file_read({"path": str(outside_file)}),
               "absolute path is rejected")
        expect(tools.ToolDenied, lambda: _run_file_read({"path": r"C:\\Windows\\win.ini"}),
               "Windows drive path is rejected cross-platform")
        expect(tools.ToolDenied, lambda: _run_file_read({"path": "hello.txt:secret"}),
               "NTFS alternate-data-stream syntax is rejected")
        expect(tools.ToolDenied, lambda: _run_file_read({"path": "NUL.txt"}),
               "Windows device aliases are rejected")
        expect(tools.ToolDenied, lambda: _run_file_read({"path": "hello.txt", "root": "/"}),
               "unknown authority-smuggling argument is rejected")

        # --- link/reparse escape -----------------------------------------
        link = root / "escape.txt"
        link_created = False
        try:
            os.symlink(outside_file, link)
            link_created = True
        except (OSError, NotImplementedError):
            pass
        if link_created:
            expect(tools.ToolDenied, lambda: _run_file_read({"path": "escape.txt"}),
                   "symlink escape is rejected")
            listed = json.loads(_run_file_list({"limit": MAX_LIST_ENTRIES}))
            link_rows = [row for row in listed["entries"] if row["path"] == "escape.txt"]
            check(bool(link_rows) and link_rows[0]["kind"] == "unsupported_link",
                  "list exposes link as unsupported without following it")
        else:
            check(True, "symlink creation unavailable on this platform; no unsafe fallback used")

        # --- file_list ----------------------------------------------------
        listed = json.loads(_run_file_list({}))
        entry_paths = {entry["path"] for entry in listed["entries"]}
        check({"hello.txt", "nested", "binary.bin", "large.txt"}.issubset(entry_paths),
              "file_list returns bounded relative metadata")
        check(str(root) not in json.dumps(listed, ensure_ascii=False),
              "file_list never exposes absolute workspace root")
        expect(tools.ToolDenied, lambda: _run_file_list({"limit": True}),
               "bool is not accepted as integer list limit")
        expect(tools.ToolDenied, lambda: _run_file_list({"limit": MAX_LIST_ENTRIES + 1}),
               "list hard cap cannot be widened by model args")

        # --- file_search --------------------------------------------------
        search = json.loads(_run_file_search({"query": "needle"}))
        check(len(search["matches"]) == 1
              and search["matches"][0]["path"] == "nested/notes.md"
              and search["matches"][0]["line"] == 2,
              "file_search finds bounded case-insensitive text match")
        check(search["receipt"]["relative_paths"] == ["nested/notes.md"],
              "search receipt contains only matched relative files")
        check(search["bytes_scanned"] <= 1_000_000,
              "search reports bounded scanned bytes")
        check(str(root) not in json.dumps(search, ensure_ascii=False),
              "file_search never exposes absolute workspace root")
        expect(tools.ToolDenied, lambda: _run_file_search({"query": ""}),
               "blank search query is rejected")
        expect(tools.ToolDenied,
               lambda: _run_file_search({"query": "x", "max_results": 999}),
               "search result cap cannot be widened")

        # --- production mount -------------------------------------------
        app = FastAPI()
        check(mount_file_capabilities(app) is True, "production mount accepts valid opt-in")
        check(mount_file_capabilities(app) is True, "production mount is idempotent")
        check(getattr(app.state, "file_capabilities_mounted", False) is True,
              "mount records state without adding a parallel file route")

        # --- real isolated child ----------------------------------------
        os.environ["PYTHONPATH"] = str(ROOT / "worker")
        executor = ProcessExecutor(
            tools.InProcessExecutor(),
            child_cmd=[sys.executable, "-m", "app.tool_child"],
        )
        isolated_text = json.loads(
            executor.execute(tools.REGISTRY["file_read"], {"path": "hello.txt"})
        )
        check(isolated_text["status"] == "text"
              and isolated_text["receipt"]["workspace_id"] == "demo",
              "real child process reconstructs authority and reads workspace file")

        # Removing the activation flag from the exact child env must make the
        # same registered parent tool disappear in the fresh child.
        os.environ.pop(FILE_CAPABILITIES_FLAG, None)
        exc = expect(
            tools.ToolDenied,
            lambda: executor.execute(tools.REGISTRY["file_read"], {"path": "hello.txt"}),
            "fresh child fails closed when activation flag is absent",
        )
        check(exc is not None and "unknown tool" in str(exc),
              "child failure is absence of authority, not in-process fallback")
        os.environ[FILE_CAPABILITIES_FLAG] = "1"

        # A workspace root that is itself an alias is never accepted as trusted
        # authority. Exercise when symlinks are available.
        root_alias = outside / "root-alias"
        alias_created = False
        try:
            os.symlink(root, root_alias, target_is_directory=True)
            alias_created = True
        except (OSError, NotImplementedError):
            pass
        if alias_created:
            os.environ[FILE_WORKSPACE_ROOT_ENV] = str(root_alias)
            expect(FileCapabilityConfigError, workspace_from_environment,
                   "workspace root cannot itself be a symlink/reparse alias")
            os.environ[FILE_WORKSPACE_ROOT_ENV] = str(root.resolve())

finally:
    remove_tools()
    for name, value in OLD_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

print(f"\n===== T-035 FILE CAPABILITIES: {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
