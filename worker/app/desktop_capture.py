"""Dormant Tier-B screenshot capture boundary for Computer Use I3.

This module can capture the Windows virtual desktop, derive a perceptual hash and
issue the short-lived ``screen_id`` used by :mod:`desktop_policy`.  It deliberately
registers no tool and mounts no API route.  Mouse and keyboard injection are not
part of this slice.

The boundary is fail-closed:

* ``KALIV_COMPUTER_USE_SCREEN=1`` is required;
* local-model origin is the default, while cloud origin needs separate explicit
  session consent through the existing desktop policy;
* raw pixels are returned only to the caller and never written to audit metadata;
* the Windows backend imports and opens GDI resources only when ``capture()`` is
  called, then releases every handle in ``finally``.
"""
from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import Protocol

from .desktop_policy import DesktopDenied, ScreenRef, ScreenRegistry, require_local_origin

CAPTURE_SCHEMA = "kaliv-desktop-screenshot/v1"
FEATURE_ENV = "KALIV_COMPUTER_USE_SCREEN"
_MAX_DIMENSION = 16_384
_MAX_PIXELS = 100_000_000


class DesktopCaptureError(RuntimeError):
    """Capture failed without exposing platform exception text or screen data."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DesktopFrame:
    """One tightly packed, top-down BGRA frame."""

    width: int
    height: int
    bgra: bytes

    def __post_init__(self) -> None:
        if (
            isinstance(self.width, bool)
            or not isinstance(self.width, int)
            or not 1 <= self.width <= _MAX_DIMENSION
        ):
            raise DesktopCaptureError("invalid_frame_width")
        if (
            isinstance(self.height, bool)
            or not isinstance(self.height, int)
            or not 1 <= self.height <= _MAX_DIMENSION
        ):
            raise DesktopCaptureError("invalid_frame_height")
        pixels = self.width * self.height
        if pixels > _MAX_PIXELS:
            raise DesktopCaptureError("frame_too_large")
        if not isinstance(self.bgra, bytes) or len(self.bgra) != pixels * 4:
            raise DesktopCaptureError("invalid_frame_buffer")

    @property
    def stride(self) -> int:
        return self.width * 4

    def bmp_bytes(self) -> bytes:
        """Encode the frame as a self-contained top-down 32-bit BMP."""

        pixel_offset = 14 + 40
        file_size = pixel_offset + len(self.bgra)
        file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset)
        dib_header = struct.pack(
            "<IiiHHIIiiII",
            40,
            self.width,
            -self.height,  # negative = top-down rows
            1,
            32,
            0,  # BI_RGB
            len(self.bgra),
            0,
            0,
            0,
            0,
        )
        return file_header + dib_header + self.bgra

    def perceptual_hash(self) -> str:
        """Return a 128-bit screen hash robust to tiny cursor/caret changes.

        The first 64 bits compare an 8x8 luminance grid to its own mean.  The
        second 64 bits compare the same grid to an absolute mid-grey threshold,
        so uniformly black and uniformly white screens cannot collide.  Each grid
        cell is sampled at sixteen evenly distributed points; work is bounded
        regardless of desktop resolution.
        """

        values: list[int] = []
        data = self.bgra
        for gy in range(8):
            y0 = gy * self.height // 8
            y1 = max(y0 + 1, (gy + 1) * self.height // 8)
            for gx in range(8):
                x0 = gx * self.width // 8
                x1 = max(x0 + 1, (gx + 1) * self.width // 8)
                total = 0
                count = 0
                for sy in range(4):
                    y = min(y1 - 1, y0 + ((2 * sy + 1) * (y1 - y0)) // 8)
                    row = y * self.stride
                    for sx in range(4):
                        x = min(x1 - 1, x0 + ((2 * sx + 1) * (x1 - x0)) // 8)
                        offset = row + x * 4
                        b, g, r = data[offset], data[offset + 1], data[offset + 2]
                        total += (299 * r + 587 * g + 114 * b) // 1000
                        count += 1
                values.append(total // count)

        mean = sum(values) / len(values)
        relative = 0
        absolute = 0
        for value in values:
            relative = (relative << 1) | int(value >= mean)
            absolute = (absolute << 1) | int(value >= 128)
        return f"{relative:016x}{absolute:016x}"


class DesktopCaptureBackend(Protocol):
    def capture(self) -> DesktopFrame: ...


class WindowsGdiCaptureBackend:
    """Capture the complete Windows virtual desktop through GDI.

    No external package is required.  The implementation remains import-safe on
    non-Windows systems and opens no handle until ``capture`` is invoked.
    """

    def capture(self) -> DesktopFrame:
        if os.name != "nt":
            raise DesktopCaptureError("windows_capture_unavailable")

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

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

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [
                    ("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", wintypes.DWORD * 3),
                ]

            user32.GetSystemMetrics.argtypes = [ctypes.c_int]
            user32.GetSystemMetrics.restype = ctypes.c_int
            user32.GetDC.argtypes = [wintypes.HWND]
            user32.GetDC.restype = wintypes.HDC
            user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            user32.ReleaseDC.restype = ctypes.c_int
            gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
            gdi32.CreateCompatibleDC.restype = wintypes.HDC
            gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
            gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
            gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
            gdi32.SelectObject.restype = wintypes.HGDIOBJ
            gdi32.BitBlt.argtypes = [
                wintypes.HDC,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HDC,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.DWORD,
            ]
            gdi32.BitBlt.restype = wintypes.BOOL
            gdi32.GetDIBits.argtypes = [
                wintypes.HDC,
                wintypes.HBITMAP,
                wintypes.UINT,
                wintypes.UINT,
                wintypes.LPVOID,
                ctypes.POINTER(BITMAPINFO),
                wintypes.UINT,
            ]
            gdi32.GetDIBits.restype = ctypes.c_int
            gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
            gdi32.DeleteObject.restype = wintypes.BOOL
            gdi32.DeleteDC.argtypes = [wintypes.HDC]
            gdi32.DeleteDC.restype = wintypes.BOOL

            x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
            width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
            if width <= 0 or height <= 0:
                raise DesktopCaptureError("desktop_geometry_unavailable")

            screen_dc = user32.GetDC(None)
            memory_dc = bitmap = old_object = None
            if not screen_dc:
                raise DesktopCaptureError("desktop_dc_unavailable")
            try:
                memory_dc = gdi32.CreateCompatibleDC(screen_dc)
                bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
                if not memory_dc or not bitmap:
                    raise DesktopCaptureError("desktop_bitmap_unavailable")
                old_object = gdi32.SelectObject(memory_dc, bitmap)
                if not old_object:
                    raise DesktopCaptureError("desktop_bitmap_select_failed")
                if not gdi32.BitBlt(
                    memory_dc,
                    0,
                    0,
                    width,
                    height,
                    screen_dc,
                    x,
                    y,
                    0x00CC0020 | 0x40000000,  # SRCCOPY | CAPTUREBLT
                ):
                    raise DesktopCaptureError("desktop_copy_failed")

                info = BITMAPINFO()
                info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                info.bmiHeader.biWidth = width
                info.bmiHeader.biHeight = -height
                info.bmiHeader.biPlanes = 1
                info.bmiHeader.biBitCount = 32
                info.bmiHeader.biCompression = 0
                size = width * height * 4
                buffer = ctypes.create_string_buffer(size)
                rows = gdi32.GetDIBits(
                    memory_dc,
                    bitmap,
                    0,
                    height,
                    buffer,
                    ctypes.byref(info),
                    0,
                )
                if rows != height:
                    raise DesktopCaptureError("desktop_pixels_unavailable")
                return DesktopFrame(width=width, height=height, bgra=buffer.raw)
            finally:
                if memory_dc and old_object:
                    gdi32.SelectObject(memory_dc, old_object)
                if bitmap:
                    gdi32.DeleteObject(bitmap)
                if memory_dc:
                    gdi32.DeleteDC(memory_dc)
                user32.ReleaseDC(None, screen_dc)
        except DesktopCaptureError:
            raise
        except Exception as exc:
            raise DesktopCaptureError("windows_capture_failed") from exc


@dataclass(frozen=True)
class DesktopScreenshot:
    screen: ScreenRef
    width: int
    height: int
    image_bmp: bytes
    captured_at: float
    schema: str = CAPTURE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CAPTURE_SCHEMA:
            raise DesktopCaptureError("unsupported_capture_schema")
        if not isinstance(self.screen, ScreenRef):
            raise DesktopCaptureError("invalid_screen_reference")
        if not isinstance(self.image_bmp, bytes) or not self.image_bmp.startswith(b"BM"):
            raise DesktopCaptureError("invalid_screenshot_image")

    def audit_dict(self) -> dict:
        """Metadata only: never include pixels, window text or base64 image data."""

        return {
            "schema": self.schema,
            "screen_id": self.screen.screen_id,
            "phash": self.screen.phash,
            "width": self.width,
            "height": self.height,
            "image_bytes": len(self.image_bmp),
            "captured_at": self.captured_at,
            "production_activation": False,
        }


class DesktopCaptureService:
    def __init__(
        self,
        backend: DesktopCaptureBackend | None = None,
        registry: ScreenRegistry | None = None,
    ) -> None:
        self.backend = backend or WindowsGdiCaptureBackend()
        self.registry = registry or ScreenRegistry()

    @staticmethod
    def enabled() -> bool:
        return os.getenv(FEATURE_ENV, "0").strip().lower() in {"1", "true", "on"}

    def capture(
        self,
        *,
        origin: str,
        cloud_consent: bool = False,
        now: float | None = None,
    ) -> DesktopScreenshot:
        if not self.enabled():
            raise DesktopDenied(
                f"computer-use screenshot er slået fra — sæt {FEATURE_ENV}=1 eksplicit"
            )
        require_local_origin(origin, cloud_consent)
        timestamp = time.time() if now is None else float(now)
        frame = self.backend.capture()
        phash = frame.perceptual_hash()
        screen = self.registry.issue(phash, now=timestamp)
        return DesktopScreenshot(
            screen=screen,
            width=frame.width,
            height=frame.height,
            image_bmp=frame.bmp_bytes(),
            captured_at=timestamp,
        )


__all__ = [
    "CAPTURE_SCHEMA",
    "FEATURE_ENV",
    "DesktopCaptureBackend",
    "DesktopCaptureError",
    "DesktopCaptureService",
    "DesktopFrame",
    "DesktopScreenshot",
    "WindowsGdiCaptureBackend",
]
