#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import desktop_win32 as W  # noqa: E402
from app.desktop_contract import (  # noqa: E402
    AuthorizedDesktopAction,
    DesktopContractError,
    WindowTarget,
)
from app.desktop_policy import DesktopDenied, TargetAllowlist  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def refused(fn, expected, name: str, contains: str = "") -> str | None:
    try:
        fn()
    except expected as exc:
        message = str(exc)
        check(not contains or contains in message, name)
        return message
    else:
        check(False, name)
        return None


def png_rgb(png: bytes) -> tuple[int, int, bytes]:
    check(png.startswith(b"\x89PNG\r\n\x1a\n"), "PNG has canonical signature")
    offset = 8
    width = height = 0
    compressed = bytearray()
    while offset < len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        kind = png[offset + 4 : offset + 8]
        payload = png[offset + 8 : offset + 8 + length]
        crc = struct.unpack(">I", png[offset + 8 + length : offset + 12 + length])[0]
        check(
            crc == (zlib.crc32(kind + payload) & 0xFFFFFFFF),
            f"PNG {kind.decode('ascii')} CRC is valid",
        )
        offset += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            check(
                (depth, colour, compression, filtering, interlace) == (8, 2, 0, 0, 0),
                "PNG is bounded 8-bit non-interlaced RGB",
            )
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    return width, height, zlib.decompress(bytes(compressed))


# BGRA: blue pixel, red pixel.
frame = bytes((255, 0, 0, 255, 0, 0, 255, 255))
png = W.encode_png_bgra(2, 1, frame)
width, height, raw = png_rgb(png)
check((width, height) == (2, 1), "PNG retains exact dimensions")
check(raw == b"\x00\x00\x00\xff\xff\x00\x00", "BGRA converts to exact RGB scanline")
check(len(png) < 8 * 1024 * 1024, "PNG remains inside result cap")

solid = bytes((0, 0, 0, 255)) * (9 * 8)
check(W.difference_hash_bgra(9, 8, solid) == "0000000000000000", "solid frame has deterministic zero dHash")
# Each source row decreases in red from left to right; left > right sets every bit.
gradient = bytearray()
for _y in range(8):
    for x in range(9):
        red = 255 - x * 20
        gradient.extend((0, 0, red, 255))
check(W.difference_hash_bgra(9, 8, bytes(gradient)) == "ffffffffffffffff", "dHash samples both horizontal edges")

check(W.utf16_units("A") == (0x0041,), "BMP text maps to one UTF-16 unit")
check(W.utf16_units("😀") == (0xD83D, 0xDE00), "supplementary Unicode maps to surrogate pair")
refused(
    lambda: W.utf16_units("\ud800"),
    DesktopContractError,
    "unpaired surrogate fails closed",
    "unpaired",
)
refused(
    lambda: W.encode_png_bgra(1, 1, b"short"),
    DesktopContractError,
    "mismatched BGRA length is rejected",
    "size",
)
refused(
    lambda: W.encode_png_bgra(5000, 5000, b""),
    DesktopDenied,
    "oversized geometry is rejected before encoding",
    "for stort",
)

abi = W.CtypesWin32Api.abi_status()
check(abi["bitmap_header_bytes"] == 40, "BITMAPINFOHEADER uses the real 40-byte Win32 layout")
check(abi["bitmap_header_layout_ok"] is True, "bitmap ABI self-check is green")
check(abi["input_layout_ok"] is True, "INPUT layout matches current pointer width")
check(abi["production_activation"] is False, "native ABI cannot activate production")
if os.name != "nt":
    refused(
        W.CtypesWin32Api,
        W.DesktopWin32Error,
        "native adapter refuses non-Windows construction",
        "requires Windows",
    )

TARGET = WindowTarget(
    hwnd=11,
    process="notepad.exe",
    title="ModelRig scratchpad",
    left=100,
    top=200,
    width=2,
    height=1,
)
OTHER = WindowTarget(
    hwnd=12,
    process="notepad.exe",
    title="ModelRig scratchpad",
    left=100,
    top=200,
    width=2,
    height=1,
)
NOT_ALLOWED = WindowTarget(
    hwnd=13,
    process="cmd.exe",
    title="ModelRig scratchpad",
    left=100,
    top=200,
    width=2,
    height=1,
)
ALLOW = TargetAllowlist(rules={"notepad.exe": ["ModelRig*"]})


class FakeNative:
    def __init__(self, targets: list[WindowTarget], pixels: bytes = frame) -> None:
        self.targets = list(targets)
        self.last = self.targets[-1] if self.targets else TARGET
        self.pixels = pixels
        self.captured: list[WindowTarget] = []
        self.cursor: list[tuple[int, int]] = []
        self.clicks = 0
        self.text_chunks: list[tuple[int, ...]] = []

    def foreground_target(self) -> WindowTarget:
        if self.targets:
            self.last = self.targets.pop(0)
        return self.last

    def capture_bgra(self, target: WindowTarget) -> bytes:
        self.captured.append(target)
        return self.pixels

    def set_cursor_pos(self, x: int, y: int) -> None:
        self.cursor.append((x, y))

    def send_left_click(self) -> None:
        self.clicks += 1

    def send_unicode_units(self, units: tuple[int, ...]) -> None:
        self.text_chunks.append(units)


native = FakeNative([TARGET, TARGET])
backend = W.Win32DesktopBackend(ALLOW, native=native)
capture = backend.capture_foreground()
check(capture.target == TARGET, "capture binds the exact foreground target")
check(native.captured == [TARGET], "native capture receives only the inspected target")
check(capture.image == png, "capture returns deterministic PNG")
check(capture.phash == W.difference_hash_bgra(2, 1, frame), "capture returns trusted dHash")
audit = W.DesktopCaptureAudit.from_capture(capture).to_dict()
check(audit["process"] == "notepad.exe", "audit retains bounded process identity")
check(audit["title_sha256"] == hashlib.sha256(TARGET.title.encode()).hexdigest(), "audit hashes window title")
check(TARGET.title not in str(audit), "raw window title is absent from audit projection")
check(audit["production_activation"] is False, "capture audit cannot activate production")

changed = W.Win32DesktopBackend(ALLOW, native=FakeNative([TARGET, OTHER]))
refused(
    changed.capture_foreground,
    DesktopDenied,
    "foreground switch during capture is refused",
    "ændrede",
)
blocked_target = W.Win32DesktopBackend(ALLOW, native=FakeNative([NOT_ALLOWED]))
refused(
    blocked_target.capture_foreground,
    DesktopDenied,
    "capture checks allowlist before pixels are read",
    "allowlisten",
)
check(blocked_target.native.captured == [], "disallowed window produces no screenshot")

click = AuthorizedDesktopAction(
    kind="click",
    target=TARGET,
    absolute_x=101,
    absolute_y=200,
    button="left",
)
refused(
    lambda: backend.perform(click),
    DesktopDenied,
    "input is dormant by default",
    "dormant",
)
check(native.cursor == [] and native.clicks == 0, "dormant refusal injects nothing")

click_native = FakeNative([TARGET, TARGET])
click_backend = W.Win32DesktopBackend(ALLOW, native=click_native, input_enabled=True)
click_backend.perform(click)
check(click_native.cursor == [(101, 200)], "authorized click moves to exact absolute point")
check(click_native.clicks == 1, "authorized click injects exactly one click pair")

hover_switch = FakeNative([TARGET, OTHER])
hover_backend = W.Win32DesktopBackend(ALLOW, native=hover_switch, input_enabled=True)
refused(
    lambda: hover_backend.perform(click),
    DesktopDenied,
    "window switch after cursor move blocks mouse-down",
    "ændrede",
)
check(hover_switch.cursor == [(101, 200)] and hover_switch.clicks == 0, "TOCTOU refusal never clicks")

wrong_initial = FakeNative([OTHER])
wrong_backend = W.Win32DesktopBackend(ALLOW, native=wrong_initial, input_enabled=True)
refused(
    lambda: wrong_backend.perform(click),
    DesktopDenied,
    "action refuses a different foreground handle",
    "ændrede",
)
check(wrong_initial.cursor == [] and wrong_initial.clicks == 0, "identity refusal injects nothing")

text = "A" * 128 + "😀" + "B"
# 131 UTF-16 units -> 128 + 3, and a target check before every chunk.
type_native = FakeNative([TARGET, TARGET])
type_backend = W.Win32DesktopBackend(ALLOW, native=type_native, input_enabled=True)
type_backend.perform(
    AuthorizedDesktopAction(kind="type_text", target=TARGET, text=text)
)
check([len(chunk) for chunk in type_native.text_chunks] == [128, 3], "text is injected in bounded UTF-16 chunks")
check(type_native.text_chunks[1][:2] == (0xD83D, 0xDE00), "surrogate pair is preserved across input contract")

chunk_switch = FakeNative([TARGET, OTHER])
chunk_backend = W.Win32DesktopBackend(ALLOW, native=chunk_switch, input_enabled=True)
refused(
    lambda: chunk_backend.perform(
        AuthorizedDesktopAction(kind="type_text", target=TARGET, text="A" * 129)
    ),
    DesktopDenied,
    "foreground is rechecked before each text chunk",
    "ændrede",
)
check([len(chunk) for chunk in chunk_switch.text_chunks] == [128], "only the pre-switch chunk was injected")

refused(
    lambda: W.Win32DesktopBackend(TargetAllowlist(), native=FakeNative([TARGET])).capture_foreground(),
    DesktopDenied,
    "empty allowlist keeps capture off",
    "allowlisten",
)
refused(
    lambda: W.Win32DesktopBackend(ALLOW, native=FakeNative([TARGET]), input_enabled=1),
    DesktopContractError,
    "input_enabled rejects truthy non-booleans",
    "boolean",
)
refused(
    lambda: click_backend.perform({"kind": "click"}),
    DesktopContractError,
    "backend rejects model-authored dictionaries",
    "AuthorizedDesktopAction",
)

print(f"\nDormant Win32 desktop adapter: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
