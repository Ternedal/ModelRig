#!/usr/bin/env python3
"""Real optional-runtime check: exact versions + local H.264 MP4 decode.

The script creates a tiny synthetic H.264 source through the installed PyAV
runtime, then opens and decodes that file again. No runner-image ffmpeg CLI and
no MediaPipe model download is required. Dummy task files are enough to prove
runtime/model provenance and media inspection/decode; real landmark extraction
remains a separate gate requiring explicit local MediaPipe task assets.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import av  # type: ignore  # noqa: E402
import numpy as np  # type: ignore  # noqa: E402
from bodyrig.local_tracking import LocalTrackingConfig, LocalTrackingRuntimeError  # noqa: E402
from bodyrig.local_tracking_runtime import (  # noqa: E402
    EXPECTED_MEDIAPIPE_VERSION,
    EXPECTED_PYAV_VERSION,
    LocalTrackingBackend,
)


def _generate_h264_fixture(path: Path) -> None:
    """Create three deterministic H.264 frames with the runtime under test."""
    try:
        with av.open(str(path), mode="w", format="mp4") as container:
            stream = container.add_stream("libx264", rate=30)
            stream.width = 64
            stream.height = 64
            stream.pix_fmt = "yuv420p"
            for index in range(3):
                pixels = np.zeros((64, 64, 3), dtype=np.uint8)
                pixels[:, :, 0] = index * 60
                pixels[:, :, 1] = np.arange(64, dtype=np.uint8)[None, :]
                pixels[:, :, 2] = np.arange(64, dtype=np.uint8)[:, None]
                frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                frame.pts = index
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    except Exception as exc:
        raise SystemExit(
            f"pinned PyAV runtime could not generate H.264 fixture: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if not path.is_file() or path.stat().st_size <= 0:
        raise SystemExit("PyAV H.264 fixture generation produced no file")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    args = parser.parse_args()
    video = args.video.resolve()
    video.parent.mkdir(parents=True, exist_ok=True)
    if video.exists():
        video.unlink()
    _generate_h264_fixture(video)

    with tempfile.TemporaryDirectory(prefix="bodyrig-model-placeholders-") as td:
        root = Path(td).resolve()
        models = []
        for name in ("pose.task", "hand.task", "face.task"):
            path = root / name
            path.write_bytes(("placeholder:" + name).encode("ascii"))
            models.append(path)

        backend = LocalTrackingBackend(LocalTrackingConfig(*models))
        expected_identity = (
            f"adapter=1;pyav={EXPECTED_PYAV_VERSION};"
            f"mediapipe={EXPECTED_MEDIAPIPE_VERSION}"
        )
        if backend.backend_version != expected_identity:
            raise SystemExit(
                f"backend runtime identity mismatch: {backend.backend_version!r}"
            )

        # A model replacement after construction must invalidate the backend
        # before it can produce a receipt claiming the old model revision.
        models[0].write_bytes(b"mutated-pose-model")
        try:
            backend.inspect(video)
        except LocalTrackingRuntimeError as exc:
            if "model assets changed" not in str(exc):
                raise
        else:
            raise SystemExit("mutated model asset was accepted")

        # Reconstructing the backend intentionally captures the new exact model
        # set. It may inspect/decode media without loading the placeholder task
        # files; extraction would correctly require real task assets.
        backend = LocalTrackingBackend(LocalTrackingConfig(*models))
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

    if len(timestamps) != 3:
        raise SystemExit(f"expected exactly three decoded H.264 frames, got {len(timestamps)}")
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise SystemExit(f"decoded PTS are not strictly increasing: {timestamps}")

    print(
        "PASS bodyrig real H264 decode: "
        f"runtime={backend.backend_version} codec={facts.codec} "
        f"geometry={facts.width}x{facts.height} fps={facts.nominal_fps:.3f} "
        f"frames={len(timestamps)} timestamps={timestamps}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
