"""Hardened dormant Win32 foreground-window adapter for Tier-B computer use.

No tool, route or feature flag imports this module. ``input_enabled`` defaults to
false and has no environment-variable escape hatch. The only objects accepted
for injection are :class:`AuthorizedDesktopAction` values already produced by
the signed screenshot contract.

The adapter captures only the pixels currently visible inside the exact
foreground-window bounds and rechecks identity + geometry after capture and
immediately before input. Low-integrity/UIPI enforcement is still a separate
physical Windows gate; consequently this backend remains unregistered.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import struct
import zlib
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
_MAX_WINDOW_TITLE = 500
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Win32 scalar widths are fixed by the ABI. ctypes.wintypes maps through native
# C long on non-Windows hosts, which is 64-bit on Linux and makes offline ABI
# tests lie. Keep structures platform-independent and use opaque pointers for
# handles.
_BYTE = ctypes.c_uint8
_WORD = ctypes.c_uint16
_DWORD = ctypes.c_uint32
_UINT = ctypes.c_uint32
_LONG = ctypes.c_int32
_BOOL = ctypes.c_int32
_HRESULT = ctypes.c_int32
_HANDLE = ctypes.c_void_p
_HWND = ctypes.c_void_p
_HDC = ctypes.c_void_p
_HBITMAP = ctypes.c_void_p
_HGDIOBJ = ctypes.c_void_p
_LPWSTR = ctypes.POINTER(ctypes.c_wchar)
_LPVOID = ctypes.c_void_p


class DesktopWin32Error(RuntimeError):
    """Normalized native failure; no page text or full executable path is exposed."""


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
    """Bounded audit projection: title is hashed; raw screenshot is not logged."""

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
        if not isinstance(capture, CapturedWindow):
            raise DesktopContractError("capture must be CapturedWindow")
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


def _checked_dimensions(width: int, height: int) -> None:
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


def _checked_frame(width: int, height: int, bgra: bytes) -> None:
    _checked_dimensions(width, height)
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
    """Encode top-down BGRA pixels as a dependency-free RGB PNG."""

    _checked_frame(width, height, bgra)
    raw = bytearray()
    stride = width * 4
    view = memoryview(bgra)
    for y in range(height):
        raw.append(0)  # filter: None
        row = view[y * stride : (y + 1) * stride]
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
        # Nine columns span both edges; eight rows span top and bottom. Tiny
        # windows naturally reuse source pixels, which is deterministic and safe.
        x = 0 if width == 1 else (sample_x * (width - 1)) // 8
        y = 0 if height == 1 else (sample_y * (height - 1)) // 7
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
    try:
        raw = text.encode("utf-16-le", "strict")
    except UnicodeEncodeError as exc:
        raise DesktopContractError("text contains an unpaired Unicode surrogate") from exc
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


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", _LONG),
        ("top", _LONG),
        ("right", _LONG),
        ("bottom", _LONG),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", _DWORD),
        ("biWidth", _LONG),
        ("biHeight", _LONG),
        ("biPlanes", _WORD),
        ("biBitCount", _WORD),
        ("biCompression", _DWORD),
        ("biSizeImage", _DWORD),
        ("biXPelsPerMeter", _LONG),
        ("biYPelsPerMeter", _LONG),
        ("biClrUsed", _DWORD),
        ("biClrImportant", _DWORD),
    ]


class _RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", _BYTE),
        ("rgbGreen", _BYTE),
        ("rgbRed", _BYTE),
        ("rgbReserved", _BYTE),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", _RGBQUAD * 1),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", _LONG),
        ("dy", _LONG),
        ("mouseData", _DWORD),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", _WORD),
        ("wScan", _WORD),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", _DWORD),
        ("wParamL", _WORD),
        ("wParamH", _WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", _DWORD),
        ("union", _INPUTUNION),
    ]


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
        input_size = ctypes.sizeof(_INPUT)
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        expected_input = 40 if pointer_size == 8 else 28
        return {
            "platform": os.name,
            "pointer_bytes": pointer_size,
            "input_bytes": input_size,
            "input_layout_ok": input_size == expected_input,
            "bitmap_header_bytes": ctypes.sizeof(_BITMAPINFOHEADER),
            "bitmap_header_layout_ok": ctypes.sizeof(_BITMAPINFOHEADER) == 40,
            "production_activation": False,
        }

    def _bind(self) -> None:
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = _HWND
        self.user32.IsWindowVisible.argtypes = [_HWND]
        self.user32.IsWindowVisible.restype = _BOOL
        self.user32.IsIconic.argtypes = [_HWND]
        self.user32.IsIconic.restype = _BOOL
        self.user32.GetWindowRect.argtypes = [_HWND, ctypes.POINTER(_RECT)]
        self.user32.GetWindowRect.restype = _BOOL
        self.user32.GetWindowTextLengthW.argtypes = [_HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [_HWND, _LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [
            _HWND,
            ctypes.POINTER(_DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = _DWORD
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int
        self.user32.GetDC.argtypes = [_HWND]
        self.user32.GetDC.restype = _HDC
        self.user32.ReleaseDC.argtypes = [_HWND, _HDC]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = _BOOL
        self.user32.SendInput.argtypes = [
            _UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        self.user32.SendInput.restype = _UINT

        self.gdi32.CreateCompatibleDC.argtypes = [_HDC]
        self.gdi32.CreateCompatibleDC.restype = _HDC
        self.gdi32.DeleteDC.argtypes = [_HDC]
        self.gdi32.DeleteDC.restype = _BOOL
        self.gdi32.CreateCompatibleBitmap.argtypes = [_HDC, ctypes.c_int, ctypes.c_int]
        self.gdi32.CreateCompatibleBitmap.restype = _HBITMAP
        self.gdi32.SelectObject.argtypes = [_HDC, _HGDIOBJ]
        self.gdi32.SelectObject.restype = _HGDIOBJ
        self.gdi32.DeleteObject.argtypes = [_HGDIOBJ]
        self.gdi32.DeleteObject.restype = _BOOL
        self.gdi32.BitBlt.argtypes = [
            _HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            _HDC,
            ctypes.c_int,
            ctypes.c_int,
            _DWORD,
        ]
        self.gdi32.BitBlt.restype = _BOOL
        self.gdi32.GetDIBits.argtypes = [
            _HDC,
            _HBITMAP,
            _UINT,
            _UINT,
            _LPVOID,
            ctypes.POINTER(_BITMAPINFO),
            _UINT,
        ]
        self.gdi32.GetDIBits.restype = ctypes.c_int

        self.kernel32.OpenProcess.argtypes = [_DWORD, _BOOL, _DWORD]
        self.kernel32.OpenProcess.restype = _HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            _HANDLE,
            _DWORD,
            _LPWSTR,
            ctypes.POINTER(_DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = _BOOL
        self.kernel32.CloseHandle.argtypes = [_HANDLE]
        self.kernel32.CloseHandle.restype = _BOOL
        if self.dwmapi is not None:
            self.dwmapi.DwmGetWindowAttribute.argtypes = [
                _HWND,
                _DWORD,
                _LPVOID,
                _DWORD,
            ]
            self.dwmapi.DwmGetWindowAttribute.restype = _HRESULT

    @staticmethod
    def _fail(code: str) -> DesktopWin32Error:
        return DesktopWin32Error(f"{code} (winerror={ctypes.get_last_error()})")

    def _window_rect(self, hwnd: int) -> _RECT:
        rect = _RECT()
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
        pid = _DWORD()
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
            size = _DWORD(32768)
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
        ctypes.set_last_error(0)
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length < 0:
            raise self._fail("window_title_length_failed")
        if length > _MAX_WINDOW_TITLE:
            raise DesktopDenied("forgrundsvinduets titel er for lang til sikker binding")
        buffer = ctypes.create_unicode_buffer(length + 1)
        if length:
            ctypes.set_last_error(0)
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
        hwnd_value = int(hwnd or 0)
        if not hwnd_value:
            raise DesktopDenied("intet interaktivt forgrundsvindue er tilgængeligt")
        if not self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
            raise DesktopDenied("forgrundsvinduet er skjult eller minimeret")
        rect = self._window_rect(hwnd_value)
        target = WindowTarget(
            hwnd=hwnd_value,
            process=self._process_name(hwnd_value),
            title=self._window_title(hwnd_value),
            left=int(rect.left),
            top=int(rect.top),
            width=int(rect.right - rect.left),
            height=int(rect.bottom - rect.top),
        )
        _checked_dimensions(target.width, target.height)
        self._require_virtual_bounds(target)
        return target

    def capture_bgra(self, target: WindowTarget) -> bytes:
        if not isinstance(target, WindowTarget):
            raise DesktopContractError("target must be WindowTarget")
        _checked_dimensions(target.width, target.height)
        screen_dc = self.user32.GetDC(None)
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
            if not old or int(old) == ctypes.c_void_p(-1).value:
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
            size = target.width * target.height * 4
            info = _BITMAPINFO()
            info.bmiHeader = _BITMAPINFOHEADER(
                biSize=ctypes.sizeof(_BITMAPINFOHEADER),
                biWidth=target.width,
                biHeight=-target.height,
                biPlanes=1,
                biBitCount=32,
                biCompression=self.BI_RGB,
                biSizeImage=size,
                biXPelsPerMeter=0,
                biYPelsPerMeter=0,
                biClrUsed=0,
                biClrImportant=0,
            )
            buffer = (ctypes.c_ubyte * size)()
            lines = self.gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                target.height,
                ctypes.cast(buffer, _LPVOID),
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
            self.user32.ReleaseDC(None, screen_dc)

    def set_cursor_pos(self, x: int, y: int) -> None:
        if not self.user32.SetCursorPos(int(x), int(y)):
            raise self._fail("cursor_move_failed")

    def _send(self, inputs: list[_INPUT]) -> None:
        if not inputs:
            return
        array = (_INPUT * len(inputs))(*inputs)
        sent = self.user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            raise self._fail("input_injection_failed")

    def send_left_click(self) -> None:
        self._send(
            [
                _INPUT(
                    type=self.INPUT_MOUSE,
                    union=_INPUTUNION(
                        mi=_MOUSEINPUT(dwFlags=self.MOUSEEVENTF_LEFTDOWN)
                    ),
                ),
                _INPUT(
                    type=self.INPUT_MOUSE,
                    union=_INPUTUNION(
                        mi=_MOUSEINPUT(dwFlags=self.MOUSEEVENTF_LEFTUP)
                    ),
                ),
            ]
        )

    def send_unicode_units(self, units: tuple[int, ...]) -> None:
        if not isinstance(units, tuple) or not units:
            raise DesktopContractError("units must be a non-empty tuple")
        inputs: list[_INPUT] = []
        for unit in units:
            if (
                isinstance(unit, bool)
                or not isinstance(unit, int)
                or not 0 <= unit <= 0xFFFF
            ):
                raise DesktopContractError("UTF-16 unit is invalid")
            inputs.append(
                _INPUT(
                    type=self.INPUT_KEYBOARD,
                    union=_INPUTUNION(
                        ki=_KEYBDINPUT(
                            wVk=0,
                            wScan=unit,
                            dwFlags=self.KEYEVENTF_UNICODE,
                        )
                    ),
                )
            )
            inputs.append(
                _INPUT(
                    type=self.INPUT_KEYBOARD,
                    union=_INPUTUNION(
                        ki=_KEYBDINPUT(
                            wVk=0,
                            wScan=unit,
                            dwFlags=self.KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP,
                        )
                    ),
                )
            )
        self._send(inputs)


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
