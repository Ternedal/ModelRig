"""Dormant Windows desktop capture boundary for Computer Use I3.

This module captures pixels only when called explicitly. It writes no screenshot to
disk, opens no network connection and injects no input. Raw image bytes live in a
small, short-lived in-memory vault keyed by the same ``screen_id`` that the trusted
``ScreenRegistry`` uses for later stale-screen checks.
"""
from __future__ import annotations

import ctypes
import os
import struct
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from .desktop_policy import ScreenRegistry

DEFAULT_MAX_WIDTH = 960
DEFAULT_MAX_HEIGHT = 540
DEFAULT_TTL_SECONDS = 20.0
DEFAULT_MAX_SNAPSHOTS = 4


class DesktopCaptureError(RuntimeError):
    """Capture or snapshot lookup was refused; callers must fail closed."""


@dataclass(frozen=True)
class CapturedDesktopFrame:
    width: int
    height: int
    bgrx: bytes
    origin_x: int = 0
    origin_y: int = 0
    captured_at: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.width, bool) or not isinstance(self.width, int) or self.width <= 0:
            raise DesktopCaptureError("frame width is invalid")
        if isinstance(self.height, bool) or not isinstance(self.height, int) or self.height <= 0:
            raise DesktopCaptureError("frame height is invalid")
        if not isinstance(self.bgrx, bytes) or len(self.bgrx) != self.width * self.height * 4:
            raise DesktopCaptureError("frame pixel buffer is invalid")
        if not isinstance(self.captured_at, (int, float)) or self.captured_at < 0:
            raise DesktopCaptureError("capture timestamp is invalid")

    def perceptual_hash(self) -> str:
        """Return a trusted 64-bit average hash as 16 lowercase hex characters."""
        values: list[int] = []
        for gy in range(8):
            y = min(self.height - 1, (gy * self.height + self.height // 2) // 8)
            for gx in range(8):
                x = min(self.width - 1, (gx * self.width + self.width // 2) // 8)
                offset = (y * self.width + x) * 4
                b, g, r = self.bgrx[offset], self.bgrx[offset + 1], self.bgrx[offset + 2]
                values.append((29 * b + 150 * g + 77 * r) >> 8)
        average = sum(values) / len(values)
        bits = 0
        for value in values:
            bits = (bits << 1) | int(value >= average)
        return f"{bits:016x}"

    def bmp_bytes(self) -> bytes:
        """Encode the top-down BGRX frame as a deterministic 32-bit BMP in memory."""
        pixel_offset = 14 + 40
        size = pixel_offset + len(self.bgrx)
        file_header = struct.pack("<2sIHHI", b"BM", size, 0, 0, pixel_offset)
        info_header = struct.pack(
            "<IiiHHIIiiII",
            40,
            self.width,
            -self.height,  # top-down rows; no extra copy or vertical flip
            1,
            32,
            0,
            len(self.bgrx),
            2835,
            2835,
            0,
            0,
        )
        return file_header + info_header + self.bgrx


@dataclass(frozen=True)
class DesktopSnapshot:
    screen_id: str
    phash: str
    width: int
    height: int
    origin_x: int
    origin_y: int
    captured_at: float
    expires_at: float
    bmp: bytes

    def metadata(self) -> dict:
        return {
            "schema": "kaliv-desktop-snapshot/v1",
            "screen_id": self.screen_id,
            "phash": self.phash,
            "width": self.width,
            "height": self.height,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "mime_type": "image/bmp",
            "image_bytes": len(self.bmp),
            "expires_in_seconds": max(0, int(self.expires_at - time.time())),
            "storage": "memory_only",
            "production_activation": False,
        }


class CaptureBackend(Protocol):
    def capture(self, *, max_width: int, max_height: int) -> CapturedDesktopFrame: ...


class DesktopSnapshotVault:
    """Bounded, TTL-enforced RAM store; raw screenshots are never returned in audit text."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
        clock=time.time,
    ) -> None:
        if not 1 <= max_snapshots <= 32:
            raise DesktopCaptureError("max_snapshots is invalid")
        if not 1.0 <= float(ttl_seconds) <= 120.0:
            raise DesktopCaptureError("snapshot TTL is invalid")
        self.ttl_seconds = float(ttl_seconds)
        self.max_snapshots = int(max_snapshots)
        self.clock = clock
        self.registry = ScreenRegistry(ttl_s=self.ttl_seconds)
        self._lock = threading.RLock()
        self._snapshots: dict[str, DesktopSnapshot] = {}

    def _prune(self, now: float) -> None:
        for screen_id in [
            key for key, value in self._snapshots.items() if value.expires_at <= now
        ]:
            self._snapshots.pop(screen_id, None)
        while len(self._snapshots) >= self.max_snapshots:
            oldest = min(self._snapshots, key=lambda key: self._snapshots[key].captured_at)
            self._snapshots.pop(oldest, None)

    def issue(self, frame: CapturedDesktopFrame) -> DesktopSnapshot:
        if not isinstance(frame, CapturedDesktopFrame):
            raise DesktopCaptureError("frame must be CapturedDesktopFrame")
        now = float(self.clock())
        phash = frame.perceptual_hash()
        ref = self.registry.issue(phash, now=now)
        snapshot = DesktopSnapshot(
            screen_id=ref.screen_id,
            phash=phash,
            width=frame.width,
            height=frame.height,
            origin_x=frame.origin_x,
            origin_y=frame.origin_y,
            captured_at=now,
            expires_at=now + self.ttl_seconds,
            bmp=frame.bmp_bytes(),
        )
        with self._lock:
            self._prune(now)
            self._snapshots[snapshot.screen_id] = snapshot
        return snapshot

    def get(self, screen_id: str) -> DesktopSnapshot:
        if not isinstance(screen_id, str) or not screen_id:
            raise DesktopCaptureError("screen_id is invalid")
        now = float(self.clock())
        with self._lock:
            self._prune(now)
            snapshot = self._snapshots.get(screen_id)
        if snapshot is None:
            raise DesktopCaptureError("screenshot is unknown or expired")
        return snapshot

    def discard(self, screen_id: str) -> None:
        with self._lock:
            self._snapshots.pop(screen_id, None)

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


class WindowsGdiCapture:
    """Capture the Windows virtual desktop through GDI into a bounded BGRX buffer."""

    def capture(self, *, max_width: int, max_height: int) -> CapturedDesktopFrame:
        if os.name != "nt":
            raise DesktopCaptureError("desktop capture is available only on Windows")
        if not 64 <= max_width <= 4096 or not 64 <= max_height <= 2160:
            raise DesktopCaptureError("capture dimensions are outside the safe range")

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        sm_xvirtualscreen, sm_yvirtualscreen = 76, 77
        sm_cxvirtualscreen, sm_cyvirtualscreen = 78, 79
        src_x = int(user32.GetSystemMetrics(sm_xvirtualscreen))
        src_y = int(user32.GetSystemMetrics(sm_yvirtualscreen))
        src_w = int(user32.GetSystemMetrics(sm_cxvirtualscreen))
        src_h = int(user32.GetSystemMetrics(sm_cyvirtualscreen))
        if src_w <= 0 or src_h <= 0:
            raise DesktopCaptureError("Windows reported an invalid virtual desktop")

        scale = min(1.0, max_width / src_w, max_height / src_h)
        width = max(1, int(src_w * scale))
        height = max(1, int(src_h * scale))
        screen_dc = memory_dc = bitmap = old_bitmap = None
        try:
            screen_dc = user32.GetDC(0)
            if not screen_dc:
                raise DesktopCaptureError("GetDC failed")
            memory_dc = gdi32.CreateCompatibleDC(screen_dc)
            bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
            if not memory_dc or not bitmap:
                raise DesktopCaptureError("GDI capture allocation failed")
            old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
            gdi32.SetStretchBltMode(memory_dc, 4)  # HALFTONE
            rop = 0x00CC0020 | 0x40000000  # SRCCOPY | CAPTUREBLT
            if not gdi32.StretchBlt(
                memory_dc, 0, 0, width, height,
                screen_dc, src_x, src_y, src_w, src_h, rop,
            ):
                raise DesktopCaptureError("StretchBlt failed")

            info = _BITMAPINFO()
            info.bmiHeader = _BITMAPINFOHEADER(
                ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0,
                width * height * 4, 0, 0, 0, 0,
            )
            buffer = (ctypes.c_ubyte * (width * height * 4))()
            if gdi32.GetDIBits(
                memory_dc, bitmap, 0, height, ctypes.byref(buffer),
                ctypes.byref(info), 0,
            ) != height:
                raise DesktopCaptureError("GetDIBits failed")
            return CapturedDesktopFrame(
                width=width,
                height=height,
                bgrx=bytes(buffer),
                origin_x=src_x,
                origin_y=src_y,
                captured_at=time.time(),
            )
        finally:
            if old_bitmap and memory_dc:
                gdi32.SelectObject(memory_dc, old_bitmap)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            if screen_dc:
                user32.ReleaseDC(0, screen_dc)


SNAPSHOTS = DesktopSnapshotVault()


def capture_desktop_snapshot(
    *,
    backend: CaptureBackend | None = None,
    vault: DesktopSnapshotVault = SNAPSHOTS,
) -> dict:
    active = backend or WindowsGdiCapture()
    frame = active.capture(max_width=DEFAULT_MAX_WIDTH, max_height=DEFAULT_MAX_HEIGHT)
    return vault.issue(frame).metadata()


def get_snapshot(screen_id: str, *, vault: DesktopSnapshotVault = SNAPSHOTS) -> DesktopSnapshot:
    """Trusted local bridge for a later vision planner; never exposed as tool text."""
    return vault.get(screen_id)


__all__ = [
    "CapturedDesktopFrame",
    "CaptureBackend",
    "DesktopCaptureError",
    "DesktopSnapshot",
    "DesktopSnapshotVault",
    "SNAPSHOTS",
    "WindowsGdiCapture",
    "capture_desktop_snapshot",
    "get_snapshot",
]
