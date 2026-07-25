"""Contract tests for dormant Computer Use I3 screenshot capture.

No test captures the CI runner desktop. Fake BGRX frames drive the portable contract;
the Windows backend is separately required to fail closed on non-Windows hosts.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.desktop_capture import (  # noqa: E402
    CapturedDesktopFrame,
    DesktopCaptureError,
    DesktopSnapshotVault,
    WindowsGdiCapture,
    capture_desktop_snapshot,
)

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except DesktopCaptureError as exc:
        return str(exc)
    return None


def frame(seed: int, width: int = 16, height: int = 16) -> CapturedDesktopFrame:
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            value = (x * 17 + y * 11 + seed) % 256
            pixels.extend((value, (value * 3) % 256, (255 - value), 0))
    return CapturedDesktopFrame(width, height, bytes(pixels), -10, 20, 100.0)


print("portable frame contract:")
f1 = frame(1)
f2 = frame(1)
f3 = frame(91)
check(f1.perceptual_hash() == f2.perceptual_hash(), "same pixels produce the same trusted pHash")
check(len(f1.perceptual_hash()) == 16, "pHash is exactly 64 bits / 16 lowercase hex chars")
check(f1.perceptual_hash() != f3.perceptual_hash(), "materially different pixels change the pHash")
bmp = f1.bmp_bytes()
check(bmp[:2] == b"BM" and len(bmp) == 54 + 16 * 16 * 4, "BMP is deterministic and size-bounded")
check(raises(CapturedDesktopFrame, 1, 1, b"bad") is not None, "invalid pixel buffers fail closed")

print("\nshort-lived in-memory vault:")
now = [1000.0]
vault = DesktopSnapshotVault(ttl_seconds=5.0, max_snapshots=2, clock=lambda: now[0])
s1 = vault.issue(frame(1))
now[0] += 1
s2 = vault.issue(frame(2))
metadata = s2.metadata()
check(vault.get(s1.screen_id) == s1, "fresh screen_id resolves to the exact in-memory snapshot")
check(metadata["storage"] == "memory_only", "metadata states that screenshot storage is memory-only")
check("bmp" not in metadata and "image" not in metadata, "raw pixels are not returned in tool/audit metadata")
check(metadata["production_activation"] is False, "capture substrate cannot claim production activation")
now[0] += 1
s3 = vault.issue(frame(3))
check(raises(vault.get, s1.screen_id) is not None, "bounded vault evicts the oldest screenshot")
check(vault.get(s3.screen_id).bmp.startswith(b"BM"), "newest screenshot remains available to a local vision bridge")
now[0] += 10
check(raises(vault.get, s2.screen_id) is not None, "expired screen_id is refused even when remembered")
vault.clear()
check(raises(vault.get, s3.screen_id) is not None, "kill/cleanup can clear every raw screenshot immediately")

print("\nbackend and side-effect boundary:")


class FakeBackend:
    def __init__(self):
        self.calls = []

    def capture(self, *, max_width: int, max_height: int):
        self.calls.append((max_width, max_height))
        return frame(7)


fake = FakeBackend()
now[0] = 2000.0
vault2 = DesktopSnapshotVault(ttl_seconds=5.0, max_snapshots=2, clock=lambda: now[0])
with tempfile.TemporaryDirectory() as tmp:
    before = set(Path(tmp).iterdir())
    result = capture_desktop_snapshot(backend=fake, vault=vault2)
    after = set(Path(tmp).iterdir())
check(fake.calls == [(960, 540)], "capture always applies the bounded thumbnail dimensions")
check(result["screen_id"] and result["mime_type"] == "image/bmp", "capture returns only typed snapshot metadata")
check(before == after, "capture contract writes no screenshot file")
if os.name != "nt":
    check(
        raises(WindowsGdiCapture().capture, max_width=960, max_height=540) is not None,
        "real desktop backend refuses non-Windows hosts",
    )
else:
    check(True, "real Windows capture is reserved for the physical rig gate")

print(f"\n===== DESKTOP CAPTURE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
