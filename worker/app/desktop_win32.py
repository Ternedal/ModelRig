"""Dormant Win32 foreground-window adapter for Tier-B computer use.

No tool or route imports this module. Constructing the high-level backend with
its defaults can capture nothing automatically and can inject no input:
``input_enabled`` is false unless an explicit in-process owner enables it.
There is intentionally no environment variable that flips this switch.

The adapter is narrow by design:

* only the current foreground top-level window can be inspected or captured;
* the full window must be visible inside the virtual desktop;
* capture reads the pixels currently visible to the user, not hidden window
  backing storage or another desktop;
* the foreground identity and geometry are checked before and after capture;
* clicks/type events re-check the exact foreground target immediately before
  every injection step;
* only the pure-Python signed contract returns an action that may reach this
  adapter. This module never accepts model-authored dictionaries.

Windows low-integrity/UIPI enforcement remains a separate physical gate. Until
that layer is proven on the rig, real input injection is dormant and must not be
registered as a ModelRig capability.
"""
from __future__ import annotations

import ctypes
import os
import struct
import zlib
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Protocol

from .desktop_contract import (
    AuthorizedDesktopAction,
    CapturedWindow,
    DesktopContractError,
    WindowTarget,
)
from .desktop_policy import DesktopDenied, TargetAllowlist

_MAX_PIXELS = 16_000_000
_MAX_PNG_BYTES = 8 * 1024 * 1024
_MAX_TEXT_UNITS_PER_SEND = 128
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DesktopWin32Error(RuntimeError):
    """Normalized native failure; raw paths/window contents are not included."""


class NativeDesktopApi(Protocol):
    def foreground_target(self) -> WindowTarget:
        ...

    def capture_bgra(self, target: WindowTarget) -> bytes:
        ...

    def set_cursor_pos(self, x: int, y: int) -> None:
        ...

    def send_left_click(self) -> None:
        ...

    def send_unicode_units(self, units: tuple[int, ...]) -> None:
        ...


@dataclass(frozen=True)
class DesktopCaptureAudit:
    process: str
    title_sha256: str
    hwnd: int
    left: int
    top: int
    width: int
    height: int
    image_sha256: str
    phash: str
    production_activation: bool = False

    @classmethod
    def from_capture(cls, capture: CapturedWindow) -> "DesktopCaptureAudit":
        import hashlib

        return cls(
            process=capture.target.process,
            title_sha256=hashlib.sha256(
                capture.target.title.encode("utf-8")
            ).hexdigest(),
            hwnd=capture.target.hwnd,
            left=capture.target.left,
            top=capture.target.top,
            width=capture.target.width,
            height=capture.target.height,
            image_sha256=capture.image_sha256,
            phash=capture.phash,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "process": self.process,
            "title_sha256": self.title_sha256,
            "hwnd": self.hwnd,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "image_sha256": self.image_sha256,
            "phash": self.phash,
            "production_activation": self.production_activation,
        }


def _checked_frame(width: int, height: int, bgra: bytes) -> None:
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise DesktopContractError("frame dimensions must be positive integers")
    if width * height > _MAX_PIXELS:
        raise DesktopDenied("forgrundsvinduet er for stort til sikker capture")
    expected = width * height * 4
    if not isinstance(bgra, bytes) or len(bgra) != expected:
        raise DesktopContractError("BGRA frame size does not match window geometry")


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    if len(kind) != 4:
        raise DesktopContractError("PNG chunk type is invalid")
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def encode_png_bgra(width: int, height: int, bgra: bytes) -> bytes:
    """Encode top-down BGRA pixels as dependency-free RGB PNG."""

    _checked_frame(width, height, bgra)
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # PNG filter: None
        row = memoryview(bgra)[y * stride : (y + 1) * stride]
        for x in range(0, stride, 4):
            raw.extend((row[x + 2], row[x + 1], row[x]))
    png = b"".join(
        (
            _PNG_SIGNATURE,
            _png_chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
            ),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6)),
            _png_chunk(b"IEND", b""),
        )
    )
    if len(png) > _MAX_PNG_BYTES:
        raise DesktopDenied("screenshot-resultatet overskrider 8 MB-grænsen")
    return png


def difference_hash_bgra(width: int, height: int, bgra: bytes) -> str:
    """Return a 64-bit visual difference hash as 16 lowercase hex chars."""

    _checked_frame(width, height, bgra)
    stride = width * 4

    def luminance(sample_x: int, sample_y: int) -> int:
        x = min(width - 1, (sample_x * width) // 9)
        y = min(height - 1, (sample_y * height) // 8)
        offset = y * stride + x * 4
        blue, green, red = bgra[offset], bgra[offset + 1], bgra[offset + 2]
        return (29 * blue + 150 * green + 77 * red) >> 8

    value = 0
    for sample_y in range(8):
        row = [luminance(sample_x, sample_y) for sample_x in range(9)]
        for sample_x in range(8):
            value = (value << 1) | int(row[sample_x] > row[sample_x + 1])
    return f"{value:016x}"


def utf16_units(text: str) -> tuple[int, ...]:
    if not isinstance(text, str) or not text:
        raise DesktopContractError("text must be a non-empty string")
    raw = text.encode("utf-16-le", "strict")
    return tuple(
        int.from_bytes(raw[offset : offset + 2], "little")
        for offset in range(0, len(raw), 2)
    )


class Win32DesktopBackend:
    """Capture and dormant input adapter around an injectable native API."""

    def __init__(
        self,
        allowlist: TargetAllowlist,
        *,
        native: NativeDesktopApi | None = None,
        input_enabled: bool = False,
    ) -> None:
        if not isinstance(allowlist, TargetAllowlist):
            raise DesktopContractError("allowlist must be TargetAllowlist")
        if not isinstance(input_enabled, bool):
            raise DesktopContractError("input_enabled must be boolean")
        self.allowlist = allowlist
        self.native = native or CtypesWin32Api()
        self.input_enabled = input_enabled

    @staticmethod
    def _same_target(expected: WindowTarget, actual: WindowTarget) -> None:
        if expected != actual:
            raise DesktopDenied(
                "forgrundsvinduet ændrede identitet eller geometri under handlingen"
            )

    def capture_foreground(self) -> CapturedWindow:
        before = self.native.foreground_target()
        self.allowlist.require(before.process, before.title)
        bgra = self.native.capture_bgra(before)
        after = self.native.foreground_target()
        self._same_target(before, after)
        png = encode_png_bgra(before.width, before.height, bgra)
        return CapturedWindow(
            target=before,
            image=png,
            media_type="image/png",
            phash=difference_hash_bgra(before.width, before.height, bgra),
        )

    def perform(self, action: AuthorizedDesktopAction) -> None:
        if not isinstance(action, AuthorizedDesktopAction):
            raise DesktopContractError("action must be AuthorizedDesktopAction")
        if not self.input_enabled:
            raise DesktopDenied(
                "Win32-input er fortsat dormant; low-integrity/UIPI-gaten er ikke godkendt"
            )
        current = self.native.foreground_target()
        self.allowlist.require(current.process, current.title)
        self._same_target(action.target, current)
        if action.kind == "click":
            if action.absolute_x is None or action.absolute_y is None:
                raise DesktopContractError("authorized click is missing coordinates")
            self.native.set_cursor_pos(action.absolute_x, action.absolute_y)
            # Moving the cursor can trigger hover UI. Identity/geometry must still
            # be exact immediately before the irreversible mouse-down event.
            self._same_target(action.target, self.native.foreground_target())
            self.native.send_left_click()
            return
        if action.kind != "type_text" or not isinstance(action.text, str):
            raise DesktopContractError("authorized type action is malformed")
        units = utf16_units(action.text)
        for offset in range(0, len(units), _MAX_TEXT_UNITS_PER_SEND):
            self._same_target(action.target, self.native.foreground_target())
            self.native.send_unicode_units(
                units[offset : offset + _MAX_TEXT_UNITS_PER_SEND]
            )


class CtypesWin32Api:
    """Lazy ctypes binding. Import is safe on non-Windows; construction is not."""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    BI_RGB = 0
    DIB_RGB_COLORS = 0
    SRCCOPY = 0x00CC0020
    CAPTUREBLT = 0x40000000
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    DWMWA_EXTENDED_FRAME_BOUNDS = 9

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class RGBQUAD(ctypes.Structure):
        _fields_ = [
            ("rgbBlue", wintypes.BYTE),
            ("rgbGreen", wintypes.BYTE),
            ("rgbRed", wintypes.BYTE),
            ("rgbReserved", wintypes.BYTE),
        ]

    class BITMAPINFO(ctypes.Structure):
        pass

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class INPUTUNION(ctypes.Union):
        pass

    class INPUT(ctypes.Structure):
        pass

    def __init__(self) -> None:
        if os.name != "nt" or not hasattr(ctypes, "WinDLL"):
            raise DesktopWin32Error("Win32 desktop adapter requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        except OSError:
            self.dwmapi = None
        self._bind()

    @staticmethod
    def abi_status() -> dict[str, object]:
        return {
            "platform": os.name,
            "pointer_bytes": ctypes.sizeof(ctypes.c_void_p),
            "input_bytes": ctypes.sizeof(CtypesWin32Api.INPUT),
            "bitmap_header_bytes": ctypes.sizeof(CtypesWin32Api.BITMAPINFOHEADER),
            "production_activation": False,
        }

    def _bind(self) -> None:
        hwnd = wintypes.HWND
        hdc = wintypes.HDC
        hbitmap = wintypes.HBITMAP
        handle = wintypes.HANDLE
        bool_t = wintypes.BOOL

        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = hwnd
        self.user32.IsWindowVisible.argtypes = [hwnd]
        self.user32.IsWindowVisible.restype = bool_t
        self.user32.IsIconic.argtypes = [hwnd]
        self.user32.IsIconic.restype = bool_t
        self.user32.GetWindowRect.argtypes = [hwnd, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowRect.restype = bool_t
        self.user32.GetWindowTextLengthW.argtypes = [hwnd]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [hwnd, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [
            hwnd,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int
        self.user32.GetDC.argtypes = [hwnd]
        self.user32.GetDC.restype = hdc
        self.user32.ReleaseDC.argtypes = [hwnd, hdc]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = bool_t
        self.user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(self.INPUT),
            ctypes.c_int,
        ]
        self.user32.SendInput.restype = wintypes.UINT

        self.gdi32.CreateCompatibleDC.argtypes = [hdc]
        self.gdi32.CreateCompatibleDC.restype = hdc
        self.gdi32.DeleteDC.argtypes = [hdc]
        self.gdi32.DeleteDC.restype = bool_t
        self.gdi32.CreateCompatibleBitmap.argtypes = [hdc, ctypes.c_int, ctypes.c_int]
        self.gdi32.CreateCompatibleBitmap.restype = hbitmap
        self.gdi32.SelectObject.argtypes = [hdc, wintypes.HGDIOBJ]
        self.gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.gdi32.DeleteObject.restype = bool_t
        self.gdi32.BitBlt.argtypes = [
            hdc,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            hdc,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]
        self.gdi32.BitBlt.restype = bool_t
        self.gdi32.GetDIBits.argtypes = [
            hdc,
            hbitmap,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.LPVOID,
            ctypes.POINTER(self.BITMAPINFO),
            wintypes.UINT,
        ]
        self.gdi32.GetDIBits.restype = ctypes.c_int

        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, bool_t, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = handle
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            handle,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = bool_t
        self.kernel32.CloseHandle.argtypes = [handle]
        self.kernel32.CloseHandle.restype = bool_t
        if self.dwmapi is not None:
            self.dwmapi.DwmGetWindowAttribute.argtypes = [
                hwnd,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
            ]
            self.dwmapi.DwmGetWindowAttribute.restype = wintypes.HRESULT

    @staticmethod
    def _fail(code: str) -> DesktopWin32Error:
        return DesktopWin32Error(f"{code} (winerror={ctypes.get_last_error()})")

    def _window_rect(self, hwnd: int) -> wintypes.RECT:
        rect = wintypes.RECT()
        used_dwm = False
        if self.dwmapi is not None:
            result = self.dwmapi.DwmGetWindowAttribute(
                hwnd,
                self.DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            used_dwm = result == 0
        if not used_dwm and not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise self._fail("window_rect_failed")
        return rect

    def _process_name(self, hwnd: int) -> str:
        pid = wintypes.DWORD()
        if not self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
            raise self._fail("window_process_failed")
        handle = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value,
        )
        if not handle:
            raise self._fail("process_open_failed")
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(size),
            ):
                raise self._fail("process_name_failed")
            name = PureWindowsPath(buffer.value[: size.value]).name.lower()
            if not name:
                raise DesktopWin32Error("process_name_empty")
            return name
        finally:
            self.kernel32.CloseHandle(handle)

    def _window_title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length < 0:
            raise self._fail("window_title_length_failed")
        buffer = ctypes.create_unicode_buffer(min(length, 499) + 1)
        if length:
            copied = self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
            if copied <= 0 and ctypes.get_last_error():
                raise self._fail("window_title_failed")
        return buffer.value

    def _require_virtual_bounds(self, target: WindowTarget) -> None:
        left = self.user32.GetSystemMetrics(self.SM_XVIRTUALSCREEN)
        top = self.user32.GetSystemMetrics(self.SM_YVIRTUALSCREEN)
        width = self.user32.GetSystemMetrics(self.SM_CXVIRTUALSCREEN)
        height = self.user32.GetSystemMetrics(self.SM_CYVIRTUALSCREEN)
        if width <= 0 or height <= 0:
            raise DesktopWin32Error("virtual_desktop_unavailable")
        if (
            target.left < left
            or target.top < top
            or target.left + target.width > left + width
            or target.top + target.height > top + height
        ):
            raise DesktopDenied(
                "forgrundsvinduet er delvist uden for det synlige virtuelle skrivebord"
            )

    def foreground_target(self) -> WindowTarget:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            raise DesktopDenied("intet interaktivt forgrundsvindue er tilgængeligt")
        if not self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
            raise DesktopDenied("forgrundsvinduet er skjult eller minimeret")
        rect = self._window_rect(hwnd)
        target = WindowTarget(
            hwnd=int(hwnd),
            process=self._process_name(hwnd),
            title=self._window_title(hwnd),
            left=int(rect.left),
            top=int(rect.top),
            width=int(rect.right - rect.left),
            height=int(rect.bottom - rect.top),
        )
        _checked_frame(target.width, target.height, b"\0" * (target.width * target.height * 4))
        self._require_virtual_bounds(target)
        return target

    def capture_bgra(self, target: WindowTarget) -> bytes:
        if not isinstance(target, WindowTarget):
            raise DesktopContractError("target must be WindowTarget")
        _checked_frame(target.width, target.height, b"\0" * (target.width * target.height * 4))
        screen_dc = self.user32.GetDC(0)
        if not screen_dc:
            raise self._fail("screen_dc_failed")
        memory_dc = bitmap = old = None
        try:
            memory_dc = self.gdi32.CreateCompatibleDC(screen_dc)
            if not memory_dc:
                raise self._fail("memory_dc_failed")
            bitmap = self.gdi32.CreateCompatibleBitmap(
                screen_dc,
                target.width,
                target.height,
            )
            if not bitmap:
                raise self._fail("bitmap_create_failed")
            old = self.gdi32.SelectObject(memory_dc, bitmap)
            if not old:
                raise self._fail("bitmap_select_failed")
            if not self.gdi32.BitBlt(
                memory_dc,
                0,
                0,
                target.width,
                target.height,
                screen_dc,
                target.left,
                target.top,
                self.SRCCOPY | self.CAPTUREBLT,
            ):
                raise self._fail("window_capture_failed")
            header = self.BITMAPINFOHEADER(
                biSize=ctypes.sizeof(self.BITMAPINFOHEADER),
                biWidth=target.width,
                biHeight=-target.height,  # top-down
                biPlanes=1,
                biBitCount=32,
                biCompression=self.BI_RGB,
                biSizeImage=target.width * target.height * 4,
                biXPelsPerMeter=0,
                biYPelsPerMeter=0,
                biClrUsed=0,
                biClrImportant=0,
            )
            info = self.BITMAPINFO()
            info.bmiHeader = header
            buffer = (ctypes.c_ubyte * header.biSizeImage)()
            lines = self.gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                target.height,
                buffer,
                ctypes.byref(info),
                self.DIB_RGB_COLORS,
            )
            if lines != target.height:
                raise self._fail("window_pixels_failed")
            return bytes(buffer)
        finally:
            if old and memory_dc:
                self.gdi32.SelectObject(memory_dc, old)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory_dc:
                self.gdi32.DeleteDC(memory_dc)
            self.user32.ReleaseDC(0, screen_dc)

    def set_cursor_pos(self, x: int, y: int) -> None:
        if not self.user32.SetCursorPos(int(x), int(y)):
            raise self._fail("cursor_move_failed")

    def _send(self, inputs: list["CtypesWin32Api.INPUT"]) -> None:
        if not inputs:
            return
        array = (self.INPUT * len(inputs))(*inputs)
        sent = self.user32.SendInput(len(inputs), array, ctypes.sizeof(self.INPUT))
        if sent != len(inputs):
            raise self._fail("input_injection_failed")

    def send_left_click(self) -> None:
        self._send(
            [
                self.INPUT(
                    type=self.INPUT_MOUSE,
                    union=self.INPUTUNION(
                        mi=self.MOUSEINPUT(dwFlags=self.MOUSEEVENTF_LEFTDOWN)
                    ),
                ),
                self.INPUT(
                    type=self.INPUT_MOUSE,
                    union=self.INPUTUNION(
                        mi=self.MOUSEINPUT(dwFlags=self.MOUSEEVENTF_LEFTUP)
                    ),
                ),
            ]
        )

    def send_unicode_units(self, units: tuple[int, ...]) -> None:
        if not isinstance(units, tuple) or not units:
            raise DesktopContractError("units must be a non-empty tuple")
        inputs: list[CtypesWin32Api.INPUT] = []
        for unit in units:
            if isinstance(unit, bool) or not isinstance(unit, int) or not 0 <= unit <= 0xFFFF:
                raise DesktopContractError("UTF-16 unit is invalid")
            inputs.append(
                self.INPUT(
                    type=self.INPUT_KEYBOARD,
                    union=self.INPUTUNION(
                        ki=self.KEYBDINPUT(
                            wVk=0,
                            wScan=unit,
                            dwFlags=self.KEYEVENTF_UNICODE,
                        )
                    ),
                )
            )
            inputs.append(
                self.INPUT(
                    type=self.INPUT_KEYBOARD,
                    union=self.INPUTUNION(
                        ki=self.KEYBDINPUT(
                            wVk=0,
                            wScan=unit,
                            dwFlags=self.KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP,
                        )
                    ),
                )
            )
        self._send(inputs)


CtypesWin32Api.BITMAPINFO._fields_ = [
    ("bmiHeader", CtypesWin32Api.BITMAPINFOHEADER),
    ("bmiColors", CtypesWin32Api.RGBQUAD * 1),
]
CtypesWin32Api.INPUTUNION._fields_ = [
    ("mi", CtypesWin32Api.MOUSEINPUT),
    ("ki", CtypesWin32Api.KEYBDINPUT),
    ("hi", CtypesWin32Api.HARDWAREINPUT),
]
CtypesWin32Api.INPUT._anonymous_ = ("union",)
CtypesWin32Api.INPUT._fields_ = [
    ("type", wintypes.DWORD),
    ("union", CtypesWin32Api.INPUTUNION),
]


__all__ = [
    "CtypesWin32Api",
    "DesktopCaptureAudit",
    "DesktopWin32Error",
    "NativeDesktopApi",
    "Win32DesktopBackend",
    "difference_hash_bgra",
    "encode_png_bgra",
    "utf16_units",
]
