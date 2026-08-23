#!/usr/bin/env python3
"""T-035 canonical ReadScope parity and directory identity regression."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app import file_capabilities as fc  # noqa: E402
from app import tools  # noqa: E402

PASSED = 0
FAILED = 0
ENV_NAMES = (
    fc.FILE_CAPABILITIES_FLAG,
    fc.FILE_WORKSPACE_ID_ENV,
    fc.FILE_WORKSPACE_ROOT_ENV,
    fc.TOOL_ISOLATION_ENV,
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


try:
    with tempfile.TemporaryDirectory() as root_raw, tempfile.TemporaryDirectory() as outside_raw:
        root = pathlib.Path(root_raw)
        outside = pathlib.Path(outside_raw)
        (root / "safe").mkdir()
        (root / "safe" / "inside.txt").write_text("inside", encoding="utf-8")
        (outside / "outside.txt").write_text("OUTSIDE_MUST_NOT_BE_LISTED", encoding="utf-8")

        os.environ[fc.FILE_CAPABILITIES_FLAG] = "1"
        os.environ[fc.TOOL_ISOLATION_ENV] = "process"
        os.environ[fc.FILE_WORKSPACE_ID_ENV] = "scope-demo"
        os.environ[fc.FILE_WORKSPACE_ROOT_ENV] = str(root.resolve())

        # read_scope.py already owns this Windows alias rule. T-035 must reuse
        # it instead of growing a second, weaker path grammar.
        exc = expect(
            tools.ToolDenied,
            lambda: fc._run_file_read({"path": "PROGRA~1/secret.txt"}),
            "Windows 8.3 short-name alias is rejected before filesystem lookup",
        )
        check(exc is not None and "8.3" in str(exc),
              "8.3 refusal comes from canonical ReadScope authority")

        # Simulate a directory changing from a validated real directory into a
        # symlink between the pre-list identity check and os.listdir(). The
        # outside names may be observed inside the syscall, but the operation
        # must fail before any result/receipt can be returned.
        swap = root / "safe"
        parked = root / "safe-original"
        probe = root / "symlink-probe"
        symlink_available = False
        try:
            os.symlink(outside, probe, target_is_directory=True)
            symlink_available = True
            probe.unlink()
        except (OSError, NotImplementedError):
            try:
                if probe.exists() or probe.is_symlink():
                    probe.unlink()
            except OSError:
                pass

        if symlink_available:
            original_listdir = os.listdir
            state = [False]

            def racing_listdir(path):
                if (
                    os.path.normcase(os.path.abspath(path))
                    == os.path.normcase(os.path.abspath(swap))
                    and not state[0]
                ):
                    os.rename(swap, parked)
                    os.symlink(outside, swap, target_is_directory=True)
                    state[0] = True
                return original_listdir(path)

            fc.os.listdir = racing_listdir
            try:
                exc = expect(
                    tools.ToolDenied,
                    lambda: fc._run_file_list({"path": "safe"}),
                    "directory identity swap during list fails closed",
                )
                check(exc is not None and (
                    "identitet" in str(exc) or "symlink/reparse" in str(exc)
                    or "authority" in str(exc)
                ), "directory swap refusal names an authority/identity boundary")
            finally:
                fc.os.listdir = original_listdir
                try:
                    if swap.is_symlink():
                        swap.unlink()
                finally:
                    if parked.exists():
                        os.rename(parked, swap)
        else:
            check(True, "directory-symlink swap test unavailable; no unsafe fallback used")
            check(True, "directory-symlink authority assertion skipped with platform limitation")

finally:
    for name, value in OLD_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

print(f"\n===== T-035 SCOPE AUTHORITY: {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
