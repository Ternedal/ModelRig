#!/usr/bin/env python3
"""Dedicated optional-runtime proof for BodyRig M1.1 ingest.

This script is run only by the BodyRig ingest workflow after installing the
pinned optional wheels. It generates a tiny local H.264/MP4 with ffmpeg,
decodes it through the production OpenCV decoder, and verifies the current
MediaPipe Holistic API surface without downloading model weights.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.mediapipe_backend import (  # noqa: E402
    MEDIAPIPE_VERSION,
    OPENCV_HEADLESS_VERSION,
    MediaPipeHolisticBackend,
    OpenCvVideoDecoder,
    _installed_version,
    _load_mediapipe,
)

passed = failed = 0


def check(condition: bool, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def run_ffmpeg(output: Path) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=160x120:rate=12",
        "-t",
        "1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-y",
        str(output),
    ]
    subprocess.run(command, check=True, timeout=30)


check(_installed_version("mediapipe") == MEDIAPIPE_VERSION, "pinned MediaPipe wheel is active")
check(
    _installed_version("opencv-python-headless") == OPENCV_HEADLESS_VERSION,
    "pinned OpenCV headless wheel is active",
)

mp = _load_mediapipe()
check(hasattr(mp.tasks.vision, "HolisticLandmarker"), "MediaPipe exposes HolisticLandmarker")
check(hasattr(mp.tasks.vision, "HolisticLandmarkerOptions"), "MediaPipe exposes HolisticLandmarkerOptions")
check(hasattr(mp.tasks.vision.HolisticLandmarker, "create_from_options"), "Holistic create_from_options API exists")
check(hasattr(mp.tasks.vision.HolisticLandmarker, "detect_for_video"), "Holistic VIDEO detection API exists")
check(hasattr(mp.tasks.BaseOptions.Delegate, "CPU"), "MediaPipe CPU delegate exists")
check(hasattr(mp.tasks.vision.RunningMode, "VIDEO"), "MediaPipe VIDEO running mode exists")

with tempfile.TemporaryDirectory(prefix="bodyrig-ingest-runtime-") as td:
    root = Path(td)
    source = root / "fixture-h264.mp4"
    run_ffmpeg(source)
    check(source.is_file() and source.stat().st_size > 0, "synthetic H.264/MP4 fixture was created locally")

    decoder = OpenCvVideoDecoder()
    facts = decoder.inspect(source)
    check(facts.codec == "h264", "OpenCV identifies synthetic MP4 video as H.264")
    check(facts.width == 160 and facts.height == 120, "decoded dimensions match source")
    check(abs(facts.nominal_fps - 12.0) < 0.01, "decoded nominal FPS matches source")
    check(900_000 <= facts.duration_us <= 1_100_000, "decoded duration is bounded around one second")

    frames = list(decoder.iter_rgb_frames(source, sample_fps=6.0))
    timestamps = [timestamp_us for timestamp_us, _rgb in frames]
    check(5 <= len(frames) <= 7, "deterministic 6 FPS sampling produces expected frame count")
    check(timestamps == sorted(set(timestamps)), "sampled timestamps are strictly monotonic and unique")
    check(all(frame.shape == (120, 160, 3) for _timestamp, frame in frames), "decoder emits RGB frame geometry")

    fake_model = root / "holistic.task"
    fake_model.write_bytes(b"bodyrig-model-hash-contract")
    backend = MediaPipeHolisticBackend(model_asset_path=fake_model, sample_fps=6.0)
    expected_revision = "sha256:" + hashlib.sha256(fake_model.read_bytes()).hexdigest()
    check(backend.backend_version == MEDIAPIPE_VERSION, "backend identity pins MediaPipe version")
    check(backend.model_revision == expected_revision, "backend identity pins local model content hash")
    check(backend.delegate == "cpu", "CPU is the default ingest delegate")

print(f"BodyRig ingest runtime: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
