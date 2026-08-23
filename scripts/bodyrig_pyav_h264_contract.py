#!/usr/bin/env python3
"""Real optional-runtime check: inspect/decode a local H.264 MP4 with PyAV.

The workflow creates the tiny synthetic source itself. No MediaPipe model asset
is downloaded; dummy task files are sufficient because this gate deliberately
stops at media inspection/decode. Extraction has its own dependency-free adapter
contract until explicit model assets are supplied by a real ingest environment.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import av  # type: ignore  # noqa: E402
from bodyrig.local_tracking import LocalTrackingConfig, MediaPipePyAVTrackingBackend  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    args = parser.parse_args()
    video = args.video.resolve()
    if not video.is_file():
        raise SystemExit(f"fixture missing: {video}")

    with tempfile.TemporaryDirectory(prefix="bodyrig-model-placeholders-") as td:
        root = Path(td).resolve()
        models = []
        for name in ("pose.task", "hand.task", "face.task"):
            path = root / name
            path.write_bytes(("placeholder:" + name).encode("ascii"))
            models.append(path)
        backend = MediaPipePyAVTrackingBackend(LocalTrackingConfig(*models))
        facts = backend.inspect(video)

    if facts.codec not in {"h264", "avc1"}:
        raise SystemExit(f"expected H.264 codec, got {facts.codec!r}")
    if facts.width != 64 or facts.height != 64:
        raise SystemExit(f"unexpected fixture geometry: {facts.width}x{facts.height}")
    if facts.duration_us <= 0 or facts.nominal_fps <= 0:
        raise SystemExit("media duration/fps must be positive")

    timestamps: list[int] = []
    with av.open(str(video), mode="r") as container:
        streams = [stream for stream in container.streams if stream.type == "video"]
        if len(streams) != 1:
            raise SystemExit(f"expected one video stream, got {len(streams)}")
        for frame in container.decode(streams[0]):
            if frame.pts is None or frame.time_base is None:
                raise SystemExit("decoded H.264 frame lacks PTS/time-base")
            timestamps.append(round(float(frame.pts * frame.time_base) * 1_000_000))
            rgb = frame.to_ndarray(format="rgb24")
            if tuple(rgb.shape) != (64, 64, 3):
                raise SystemExit(f"unexpected decoded RGB shape: {rgb.shape}")

    if len(timestamps) < 2:
        raise SystemExit(f"expected multiple decoded H.264 frames, got {len(timestamps)}")
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise SystemExit(f"decoded PTS are not strictly increasing: {timestamps}")

    print(
        "PASS bodyrig real H264 decode: "
        f"codec={facts.codec} geometry={facts.width}x{facts.height} "
        f"fps={facts.nominal_fps:.3f} frames={len(timestamps)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
