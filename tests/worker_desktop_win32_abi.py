#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import desktop_win32 as W  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


status = W.CtypesWin32Api.abi_status()
check(status["bitmap_header_bytes"] == 40, "BITMAPINFOHEADER is 40 bytes")
check(status["bitmap_header_layout_ok"] is True, "bitmap layout self-check passes")
check(status["input_layout_ok"] is True, "INPUT layout matches pointer width")
check(status["production_activation"] is False, "ABI probe cannot activate production")

if os.name != "nt":
    print("  SKIP: native DLL binding requires Windows; pure ABI layout was checked")
    print(f"\nWin32 ABI probe: {passed} passed, {failed} failed, native skipped")
    raise SystemExit(1 if failed else 0)

api = W.CtypesWin32Api()
check(api.user32 is not None, "user32 loaded")
check(api.gdi32 is not None, "gdi32 loaded")
check(api.kernel32 is not None, "kernel32 loaded")
check(api.dwmapi is not None, "dwmapi loaded on supported Windows runner")

# Signature inspection only. Calling any of these would touch the runner's
# interactive session, which this ABI probe is explicitly forbidden to do.
required = (
    (api.user32, "GetForegroundWindow", 0),
    (api.user32, "GetWindowRect", 2),
    (api.user32, "GetWindowThreadProcessId", 2),
    (api.user32, "GetWindowTextW", 3),
    (api.user32, "GetDC", 1),
    (api.user32, "ReleaseDC", 2),
    (api.user32, "SetCursorPos", 2),
    (api.user32, "SendInput", 3),
    (api.gdi32, "CreateCompatibleDC", 1),
    (api.gdi32, "CreateCompatibleBitmap", 3),
    (api.gdi32, "SelectObject", 2),
    (api.gdi32, "BitBlt", 9),
    (api.gdi32, "GetDIBits", 7),
    (api.kernel32, "OpenProcess", 3),
    (api.kernel32, "QueryFullProcessImageNameW", 4),
    (api.kernel32, "CloseHandle", 1),
)
for library, name, arity in required:
    function = getattr(library, name, None)
    check(function is not None, f"{name} export exists")
    check(
        function is not None
        and isinstance(getattr(function, "argtypes", None), list)
        and len(function.argtypes) == arity,
        f"{name} has the pinned {arity}-argument ctypes contract",
    )
    check(
        function is not None and getattr(function, "restype", None) is not None,
        f"{name} has an explicit return type",
    )

if api.dwmapi is not None:
    function = api.dwmapi.DwmGetWindowAttribute
    check(len(function.argtypes) == 4, "DwmGetWindowAttribute has pinned arity")
    check(function.restype is not None, "DwmGetWindowAttribute has explicit HRESULT")

# The constructor/binding above is the furthest this job may go. These instance
# methods are deliberately not invoked: foreground_target, capture_bgra,
# set_cursor_pos, send_left_click and send_unicode_units.
print("  PASS: probe performed no desktop capture or input")
passed += 1

print(f"\nWin32 ABI probe: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
