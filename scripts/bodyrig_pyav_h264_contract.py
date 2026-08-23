#!/usr/bin/env python3
"""Real optional-runtime check: exact Tasks API + local H.264 MP4 decode.

The script creates a tiny synthetic H.264 source through the installed PyAV
runtime, then opens and decodes that file again. It also constructs the exact
MediaPipe Tasks option objects used by the adapter. No runner-image ffmpeg CLI
and no MediaPipe model download is required. Real landmark extraction remains a
separate gate requiring explicit local MediaPipe task assets.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import av  # type: ignore  # noqa: E402
import mediapipe as mp  # type: ignore  # noqa: E402
import numpy as np  # type: ignore  # noqa: E402
from bodyrig.local_tracking import LocalTrackingConfig  # noqa: E402
from bodyrig.local_tracking_runtime import (  # noqa: E402
    EXPECTED_MEDIAPIPE_VERSION,
    EXPECTED_PYAV_VERSION,
    LocalTrackingBackend,
)


def _verify_mediapipe_tasks_api() -> None:
    """Prove the pinned package exposes the exact API our adapter calls."""
    vision = mp.tasks.vision
    for class_name in ("PoseLandmarker", "HandLandmarker", "FaceLandmarker"):
        cls = getattr(vision, class_name, None)
        if cls is None or not hasattr(cls, "create_from_options"):
            raise SystemExit(f"MediaPipe Tasks API missing {class_name}.create_from_options")
        if not hasattr(cls, "detect_for_video"):
            raise SystemExit(f"MediaPipe Tasks API missing {class_name}.detect_for_video")

    base = mp.tasks.BaseOptions(
        model_asset_path="placeholder.task",
        delegate=mp.tasks.BaseOptions.Delegate.CPU,
    )
    common = {"running_mode": vision.RunningMode.VIDEO, "min_tracking_confidence": 0.5}
    vision.PoseLandmarkerOptions(
        base_options=base, num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        **common,
    )
    vision.HandLandmarkerOptions(
        base_options=base, num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        **common,
    )
    face_options = vision.FaceLandmarkerOptions(
        base_options=base, num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        output_face_blendshapes=True,
        **common,
    )
    if face_options.output_face_blendshapes is not True:
        raise SystemExit("MediaPipe FaceLandmarkerOptions did not retain blendshape output")


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
    _verify_mediapipe_tasks_api()

    video = args.video.resolve()
    video.parent.mkdir(parents=True, exist_ok=True)
    if video.exists():
        video.unlink()
    _generate_h264_fixture(video)

    expected_identity = (
        f"adapter=1;pyav={EXPECTED_PYAV_VERSION};"
        f"mediapipe={EXPECTED_MEDIAPIPE_VERSION}"
    )
    with tempfile.TemporaryDirectory(prefix="bodyrig-model-placeholders-") as td:
        root = Path(td).resolve()
        models = []
        for name in ("pose.task", "hand.task", "face.task"):
            path = root / name
            path.write_bytes(("placeholder:" + name).encode("ascii"))
            models.append(path)

        # The supported backend snapshots these exact bytes. Mutating the
        # operator path afterwards cannot change what the active job will load.
        with LocalTrackingBackend(LocalTrackingConfig(*models)) as first_backend:
            if first_backend.backend_version != expected_identity:
                raise SystemExit(
                    f"backend runtime identity mismatch: {first_backend.backend_version!r}"
                )
            first_revision = first_backend.model_revision
            models[0].write_bytes(b"mutated-pose-model")
            facts = first_backend.inspect(video)
            if first_backend.model_revision != first_revision:
                raise SystemExit("private model snapshot revision changed after source mutation")

        # A fresh backend intentionally snapshots the new bytes and therefore
        # receives a different exact model revision.
        with LocalTrackingBackend(LocalTrackingConfig(*models)) as second_backend:
            second_revision = second_backend.model_revision
            runtime_identity = second_backend.backend_version
            second_facts = second_backend.inspect(video)
        if second_revision == first_revision:
            raise SystemExit("new backend did not observe changed model bytes")
        if second_facts != facts:
            raise SystemExit("model revision change unexpectedly altered media inspection facts")

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
        "PASS bodyrig real runtime: "
        f"runtime={runtime_identity} tasks_api=pose+hand+face "
        f"codec={facts.codec} geometry={facts.width}x{facts.height} "
        f"fps={facts.nominal_fps:.3f} frames={len(timestamps)} "
        f"timestamps={timestamps} model_revision_changed={first_revision != second_revision}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
