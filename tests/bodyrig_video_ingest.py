"""Contract tests for the optional BodyRig local video decoder.

Run: python3 tests/bodyrig_video_ingest.py

No native decoder is installed by CI.  A tiny PyAV-shaped fake proves the
BodyRig-owned boundary, exact runtime pin, PTS timing and RGB row packing.
Physical MP4/H.264 qualification is a separate opt-in gate.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from bodyrig.video_ingest import (  # noqa: E402
    DecodedVideoFrame,
    PyAVVideoDecoder,
    VideoIngestError,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


class FakePlane:
    def __init__(self, payload: bytes, line_size: int) -> None:
        self.payload = payload
        self.line_size = line_size

    def __bytes__(self) -> bytes:
        return self.payload


class FakeFrame:
    def __init__(self, pts, *, payload: bytes) -> None:
        self.pts = pts
        self.time_base = Fraction(1, 90_000)
        self.width = 2
        self.height = 2
        self.planes = (FakePlane(payload, 8),)

    def to_rgb(self):
        return self


class FakeCodecContext:
    name = "h264"
    width = 2
    height = 2


class FakeStream:
    index = 0
    codec_context = FakeCodecContext()
    duration = 270_000
    time_base = Fraction(1, 90_000)
    average_rate = Fraction(30_000, 1_001)
    base_rate = None
    guessed_rate = None


class FakeStreams:
    def __init__(self, video) -> None:
        self.video = tuple(video)


class FakeContainer:
    def __init__(self, frames, *, with_video: bool = True) -> None:
        self.stream = FakeStream()
        self.streams = FakeStreams([self.stream] if with_video else [])
        self.duration = 3_000_000
        self._frames = tuple(frames)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def decode(self, stream):
        if stream is not self.stream:
            raise AssertionError("decoder selected a foreign stream")
        return iter(self._frames)


class FakeAV:
    __version__ = "18.0.0"
    time_base = 1_000_000

    def __init__(self, frames, *, with_video: bool = True) -> None:
        self.frames = tuple(frames)
        self.with_video = with_video
        self.open_calls = []

    def open(self, path, mode="r"):
        self.open_calls.append((path, mode))
        return FakeContainer(self.frames, with_video=self.with_video)


row_padded_a = b"abcdefXXghijklYY"
row_padded_b = b"mnopqrXXstuvwxYY"
frames = [
    FakeFrame(9_000, payload=row_padded_a),
    FakeFrame(12_003, payload=row_padded_b),
]

with tempfile.TemporaryDirectory(prefix="bodyrig-video-") as td:
    source = Path(td) / "fixture.mp4"
    source.write_bytes(b"local-fixture-placeholder")

    fake_av = FakeAV(frames)
    decoder = PyAVVideoDecoder(av_module=fake_av)
    facts = decoder.inspect(source)
    check(facts.codec == "h264", "H.264 codec metadata crosses the decoder boundary")
    check(facts.width == 2 and facts.height == 2, "video dimensions are preserved")
    check(facts.duration_us == 3_000_000, "stream time_base determines exact duration")
    check(abs(facts.nominal_fps - (30_000 / 1_001)) < 1e-9,
          "nominal FPS is descriptive metadata, not the timestamp clock")

    decoded = list(decoder.decode(source))
    check([frame.timestamp_us for frame in decoded] == [0, 33_367],
          "decoded timestamps use source PTS/time_base and normalize to first frame")
    check(decoded[0].rgb24 == b"abcdefghijkl" and decoded[1].rgb24 == b"mnopqrstuvwx",
          "RGB24 row padding is removed deterministically without NumPy")
    check(all(len(frame.rgb24) == frame.width * frame.height * 3 for frame in decoded),
          "decoded RGB payload is tightly packed")
    check(len(fake_av.open_calls) == 2,
          "inspection and decoding use independent local container lifetimes")

    class WrongVersionAV(FakeAV):
        __version__ = "17.1.0"

    try:
        PyAVVideoDecoder(av_module=WrongVersionAV(frames)).inspect(source)
    except VideoIngestError as exc:
        check("expected exactly 18.0.0" in str(exc), "runtime version drift fails closed")
    else:
        check(False, "runtime version drift fails closed")

    bad_pts = FakeAV([FakeFrame(None, payload=row_padded_a)])
    try:
        list(PyAVVideoDecoder(av_module=bad_pts).decode(source))
    except VideoIngestError as exc:
        check("no integer PTS" in str(exc), "missing presentation timestamps are not invented")
    else:
        check(False, "missing presentation timestamps are not invented")

    duplicate_pts = FakeAV([
        FakeFrame(9_000, payload=row_padded_a),
        FakeFrame(9_000, payload=row_padded_b),
    ])
    try:
        list(PyAVVideoDecoder(av_module=duplicate_pts).decode(source))
    except VideoIngestError as exc:
        check("strictly increasing" in str(exc), "duplicate presentation time fails closed")
    else:
        check(False, "duplicate presentation time fails closed")

    no_video = FakeAV([], with_video=False)
    try:
        PyAVVideoDecoder(av_module=no_video).inspect(source)
    except VideoIngestError as exc:
        check("no video stream" in str(exc), "non-video input is rejected")
    else:
        check(False, "non-video input is rejected")

    try:
        DecodedVideoFrame(timestamp_us=0, width=2, height=2, rgb24=b"short")
    except VideoIngestError:
        check(True, "malformed RGB frame payload fails closed")
    else:
        check(False, "malformed RGB frame payload fails closed")

requirements = (root / "worker" / "requirements-bodyrig-video.txt").read_text(encoding="utf-8")
check("av==18.0.0" in requirements, "optional decoder runtime is exactly pinned")
check("mediapipe" not in requirements.lower(),
      "decoder slice does not silently install a tracking model runtime")

print(f"\nBodyRig video ingest: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
