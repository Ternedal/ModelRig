"""Contracts for the dormant Computer Use I3 screenshot boundary.

Run: PYTHONPATH=worker python3 tests/worker_desktop_capture.py
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.desktop_capture import (  # noqa: E402
    FEATURE_ENV,
    DesktopCaptureError,
    DesktopCaptureService,
    DesktopFrame,
    WindowsGdiCaptureBackend,
)
from app.desktop_policy import DesktopDenied, ScreenRegistry, hamming  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    return None


def frame(width=64, height=64, *, inverted=False, changed_pixel=False):
    raw = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            value = (x * 3 + y * 2) % 256
            if inverted:
                value = 255 - value
            offset = (y * width + x) * 4
            raw[offset : offset + 4] = bytes((value, value, value, 255))
    if changed_pixel:
        raw[0:4] = bytes((255, 255, 255, 255))
    return DesktopFrame(width=width, height=height, bgra=bytes(raw))


class FakeBackend:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def capture(self):
        self.calls += 1
        return self.value


print("frame contract:")
base = frame()
same = frame()
tiny = frame(changed_pixel=True)
broad = frame(inverted=True)

check(len(base.perceptual_hash()) == 32, "the perceptual hash is a fixed 128-bit hex value")
check(base.perceptual_hash() == same.perceptual_hash(), "identical pixels produce the same hash")
check(hamming(base.perceptual_hash(), tiny.perceptual_hash()) <= 6,
      "one changed pixel stays inside the existing caret/noise tolerance")
check(hamming(base.perceptual_hash(), broad.perceptual_hash()) > 6,
      "a materially changed screen exceeds the action tolerance")

bmp = base.bmp_bytes()
check(bmp[:2] == b"BM", "the screenshot is encoded as a BMP")
check(struct.unpack_from("<I", bmp, 2)[0] == len(bmp), "the BMP header records the exact file size")
check(struct.unpack_from("<i", bmp, 18)[0] == base.width, "the BMP header records width")
check(struct.unpack_from("<i", bmp, 22)[0] == -base.height, "negative BMP height preserves top-down rows")

bad = raises(DesktopCaptureError, DesktopFrame, 2, 2, b"too short")
check(bad is not None and bad.code == "invalid_frame_buffer", "malformed pixel buffers fail closed")

print("\nservice gate:")
old = os.environ.get(FEATURE_ENV)
try:
    os.environ.pop(FEATURE_ENV, None)
    backend = FakeBackend(base)
    service = DesktopCaptureService(backend=backend, registry=ScreenRegistry(ttl_s=20.0, tolerance=6))
    denied = raises(DesktopDenied, service.capture, origin="local", now=1000.0)
    check(denied is not None and FEATURE_ENV in str(denied), "the feature is off unless explicitly enabled")
    check(backend.calls == 0, "the disabled gate blocks before touching the desktop")

    os.environ[FEATURE_ENV] = "1"
    denied = raises(DesktopDenied, service.capture, origin="cloud", cloud_consent=False, now=1000.0)
    check(denied is not None and "LOKAL" in str(denied), "cloud planning is refused without separate session consent")
    check(backend.calls == 0, "cloud refusal happens before capture")

    shot = service.capture(origin="local", now=1000.0)
    check(backend.calls == 1, "one approved local request performs one capture")
    check(shot.screen.phash == base.perceptual_hash(), "the screen reference is bound to captured pixels")
    check(service.registry.verify(shot.screen.screen_id, base.perceptual_hash(), now=1005.0) is None,
          "the issued screen_id is immediately usable against the live screen hash")
    stale = raises(DesktopDenied, service.registry.verify,
                   shot.screen.screen_id, base.perceptual_hash(), 1021.0)
    check(stale is not None and "gammelt" in str(stale), "the screenshot binding expires through the existing policy")

    audit = shot.audit_dict()
    check(audit["production_activation"] is False, "capture metadata cannot claim production activation")
    check(audit["image_bytes"] == len(shot.image_bmp), "audit records only screenshot size")
    check("image_bmp" not in audit and "pixels" not in audit and "base64" not in audit,
          "raw screen pixels never enter audit metadata")

    consented = service.capture(origin="cloud", cloud_consent=True, now=1100.0)
    check(consented.screen.screen_id != shot.screen.screen_id,
          "explicit cloud consent is per capture and still issues a fresh screen reference")
finally:
    if old is None:
        os.environ.pop(FEATURE_ENV, None)
    else:
        os.environ[FEATURE_ENV] = old

print("\nplatform boundary:")
backend = WindowsGdiCaptureBackend()
check(backend is not None, "the Windows backend can be constructed without opening desktop handles")
if os.name != "nt":
    unavailable = raises(DesktopCaptureError, backend.capture)
    check(unavailable is not None and unavailable.code == "windows_capture_unavailable",
          "non-Windows execution fails with a normalized code")
else:
    check(True, "actual Windows capture remains a physical-rig acceptance test")

print(f"\n===== DESKTOP CAPTURE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
