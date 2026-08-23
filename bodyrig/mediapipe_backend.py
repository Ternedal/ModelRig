"""Optional MediaPipe/OpenCV backend for BodyRig M1.1 video ingest.

The base ModelRig worker does not import or install these dependencies. Install
``bodyrig/requirements-ingest.txt`` explicitly, provide a local Holistic
Landmarker model asset, then pass :class:`MediaPipeHolisticBackend` to
``build_tracking_timeline``.

No model weights or source video are downloaded by this module.
"""
from __future__ import annotations

import hashlib
import math
import os
import stat
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Iterator

from .tracking import BackendFrame, Landmark, MediaFacts, TrackingContractError

MEDIAPIPE_VERSION = "1.0.1"
OPENCV_HEADLESS_VERSION = "4.14.0.94"

_POSE_INDEX = {
    "nose": 0,
    "left_eye": 2,
    "right_eye": 5,
    "left_ear": 7,
    "right_ear": 8,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
    "left_heel": 29,
    "right_heel": 30,
    "left_foot_index": 31,
    "right_foot_index": 32,
}

_HAND_INDEX = {
    "wrist": 0,
    "thumb_cmc": 1,
    "thumb_mcp": 2,
    "thumb_ip": 3,
    "thumb_tip": 4,
    "index_mcp": 5,
    "index_pip": 6,
    "index_dip": 7,
    "index_tip": 8,
    "middle_mcp": 9,
    "middle_pip": 10,
    "middle_dip": 11,
    "middle_tip": 12,
    "ring_mcp": 13,
    "ring_pip": 14,
    "ring_dip": 15,
    "ring_tip": 16,
    "pinky_mcp": 17,
    "pinky_pip": 18,
    "pinky_dip": 19,
    "pinky_tip": 20,
}

# Stable semantic subset of the MediaPipe face mesh. These are intentionally
# kept out of the public tracking contract: a future extractor may map its own
# native mesh differently while emitting the same semantic ids.
_FACE_INDEX = {
    "nose_tip": 1,
    "chin": 152,
    "mouth_left": 61,
    "mouth_right": 291,
    "upper_lip": 13,
    "lower_lip": 14,
    "left_eye_inner": 133,
    "left_eye_outer": 33,
    "right_eye_inner": 362,
    "right_eye_outer": 263,
    "left_brow_inner": 107,
    "left_brow_outer": 70,
    "right_brow_inner": 336,
    "right_brow_outer": 300,
}

_BLENDSHAPE_MAP = {
    "eyeBlinkLeft": "blink_left",
    "eyeBlinkRight": "blink_right",
    "jawOpen": "jaw_open",
    "mouthSmileLeft": "mouth_smile_left",
    "mouthSmileRight": "mouth_smile_right",
    "mouthFrownLeft": "mouth_frown_left",
    "mouthFrownRight": "mouth_frown_right",
    "browInnerUp": "brow_inner_up",
    "browDownLeft": "brow_down_left",
    "browDownRight": "brow_down_right",
}


class IngestDependencyError(RuntimeError):
    """Optional ingest runtime is absent or does not match the pinned contract."""


def _installed_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError as exc:
        raise IngestDependencyError(
            f"missing optional dependency {distribution}; install bodyrig/requirements-ingest.txt"
        ) from exc


def _load_cv2():
    installed = _installed_version("opencv-python-headless")
    if installed != OPENCV_HEADLESS_VERSION:
        raise IngestDependencyError(
            f"opencv-python-headless must be exactly {OPENCV_HEADLESS_VERSION}; got {installed}"
        )
    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - import details are platform-specific
        raise IngestDependencyError(f"cannot import cv2: {type(exc).__name__}") from exc
    return cv2


def _load_mediapipe():
    installed = _installed_version("mediapipe")
    if installed != MEDIAPIPE_VERSION:
        raise IngestDependencyError(
            f"mediapipe must be exactly {MEDIAPIPE_VERSION}; got {installed}"
        )
    try:
        import mediapipe as mp  # type: ignore
    except Exception as exc:  # pragma: no cover - import details are platform-specific
        raise IngestDependencyError(f"cannot import mediapipe: {type(exc).__name__}") from exc
    return mp


def _safe_model_hash(path: Path) -> str:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise TrackingContractError("MediaPipe model asset cannot be inspected") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise TrackingContractError("MediaPipe model asset must be a non-symlink regular file")
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise TrackingContractError("MediaPipe model asset identity changed before hashing")
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
            after = os.fstat(handle.fileno())
    except TrackingContractError:
        raise
    except OSError as exc:
        raise TrackingContractError("MediaPipe model asset cannot be hashed") from exc
    if (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise TrackingContractError("MediaPipe model asset changed while hashing")
    return digest.hexdigest()


def _fourcc_name(value: float | int) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError, OverflowError):
        return "unknown"
    chars = "".join(chr((code >> (8 * index)) & 0xFF) for index in range(4)).strip("\x00 ")
    raw = chars.lower()
    if raw in {"avc1", "avc3", "h264", "x264"}:
        return "h264"
    return raw or "unknown"


class OpenCvVideoDecoder:
    """CPU decoder for ordinary local videos using the pinned OpenCV wheel.

    Timestamps are derived from frame index and nominal FPS. This is deterministic
    for constant-frame-rate MP4/H.264, which is the M1.1 acceptance baseline. A
    source whose decoder cannot provide positive FPS/frame-count metadata fails
    closed instead of receiving invented timing.
    """

    def inspect(self, source_path: os.PathLike[str] | str) -> MediaFacts:
        cv2 = _load_cv2()
        capture = cv2.VideoCapture(str(source_path))
        try:
            if not capture.isOpened():
                raise TrackingContractError("OpenCV cannot open source video")
            width = int(round(float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))))
            height = int(round(float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            frame_count = int(round(float(capture.get(cv2.CAP_PROP_FRAME_COUNT))))
            codec = _fourcc_name(capture.get(cv2.CAP_PROP_FOURCC))
        finally:
            capture.release()
        if width <= 0 or height <= 0:
            raise TrackingContractError("video dimensions are unavailable")
        if not math.isfinite(fps) or fps <= 0.0:
            raise TrackingContractError("video nominal FPS is unavailable")
        if frame_count <= 0:
            raise TrackingContractError("video frame count is unavailable")
        duration_us = max(1, int(round(frame_count * 1_000_000.0 / fps)))
        return MediaFacts(
            codec=codec,
            width=width,
            height=height,
            duration_us=duration_us,
            nominal_fps=fps,
        )

    def iter_rgb_frames(
        self,
        source_path: os.PathLike[str] | str,
        *,
        sample_fps: float | None,
    ) -> Iterator[tuple[int, Any]]:
        cv2 = _load_cv2()
        facts = self.inspect(source_path)
        fps = facts.nominal_fps
        if sample_fps is not None:
            if not math.isfinite(sample_fps) or sample_fps <= 0.0:
                raise TrackingContractError("sample_fps must be positive and finite")
            effective_sample_fps = min(float(sample_fps), fps)
            step_us = 1_000_000.0 / effective_sample_fps
        else:
            step_us = 0.0

        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            capture.release()
            raise TrackingContractError("OpenCV cannot reopen source video")
        try:
            next_emit_us = 0.0
            index = 0
            emitted = 0
            while True:
                ok, bgr = capture.read()
                if not ok:
                    break
                timestamp_us = int(round(index * 1_000_000.0 / fps))
                index += 1
                if step_us and timestamp_us + 0.5 < next_emit_us:
                    continue
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                yield timestamp_us, rgb
                emitted += 1
                if step_us:
                    next_emit_us = emitted * step_us
        finally:
            capture.release()


def _confidence_from_landmark(native: Any) -> float | None:
    values: list[float] = []
    for name in ("visibility", "presence"):
        value = getattr(native, name, None)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(min(1.0, max(0.0, value)))
    if not values:
        return None
    return min(values)


def _landmark(native: Any) -> Landmark:
    x = getattr(native, "x", None)
    y = getattr(native, "y", None)
    z = getattr(native, "z", 0.0)
    if x is None or y is None:
        raise TrackingContractError("MediaPipe landmark is missing x/y coordinates")
    return Landmark(
        x=float(x),
        y=float(y),
        z=0.0 if z is None else float(z),
        confidence=_confidence_from_landmark(native),
    )


def _map_landmarks(values: Iterable[Any] | None, mapping: dict[str, int]) -> dict[str, Landmark] | None:
    if values is None:
        return None
    points = list(values)
    if not points:
        return None
    required = max(mapping.values())
    if len(points) <= required:
        raise TrackingContractError(
            f"MediaPipe result has {len(points)} landmarks; expected index {required}"
        )
    return {name: _landmark(points[index]) for name, index in mapping.items()}


def _map_blendshapes(values: Iterable[Any] | None) -> dict[str, float] | None:
    if values is None:
        return None
    result: dict[str, float] = {}
    for category in values:
        source_name = getattr(category, "category_name", None)
        target_name = _BLENDSHAPE_MAP.get(source_name)
        if target_name is None:
            continue
        score = getattr(category, "score", None)
        if score is None:
            continue
        value = float(score)
        if not math.isfinite(value):
            raise TrackingContractError(f"MediaPipe blendshape {source_name} is non-finite")
        result[target_name] = min(1.0, max(0.0, value))
    return result or None


def mediapipe_result_to_backend_frame(result: Any, *, timestamp_us: int) -> BackendFrame:
    """Map one native HolisticLandmarker result into the stable BodyRig adapter type."""
    return BackendFrame(
        timestamp_us=timestamp_us,
        body=_map_landmarks(getattr(result, "pose_landmarks", None), _POSE_INDEX),
        left_hand=_map_landmarks(getattr(result, "left_hand_landmarks", None), _HAND_INDEX),
        right_hand=_map_landmarks(getattr(result, "right_hand_landmarks", None), _HAND_INDEX),
        face=_map_landmarks(getattr(result, "face_landmarks", None), _FACE_INDEX),
        expressions=_map_blendshapes(getattr(result, "face_blendshapes", None)),
    )


class MediaPipeHolisticBackend:
    """Single-subject local pose/hand/face extractor using MediaPipe Tasks.

    CPU is the default and supported development path. GPU can be requested
    explicitly, but MediaPipe currently limits the Python GPU delegate to Ubuntu.
    """

    backend_id = "mediapipe-holistic"
    backend_version = MEDIAPIPE_VERSION

    def __init__(
        self,
        *,
        model_asset_path: os.PathLike[str] | str,
        sample_fps: float | None = 15.0,
        delegate: str = "cpu",
        decoder: OpenCvVideoDecoder | None = None,
    ) -> None:
        path = Path(model_asset_path)
        self._model_asset_path = path
        self.model_revision = f"sha256:{_safe_model_hash(path)}"
        self.sample_fps = sample_fps
        normalized_delegate = str(delegate).strip().lower()
        if normalized_delegate not in {"cpu", "gpu"}:
            raise TrackingContractError("MediaPipe delegate must be cpu or gpu")
        self.delegate = normalized_delegate
        self.decoder = decoder or OpenCvVideoDecoder()

    def inspect(self, source_path: os.PathLike[str] | str) -> MediaFacts:
        return self.decoder.inspect(source_path)

    def extract(self, source_path: os.PathLike[str] | str) -> Iterator[BackendFrame]:
        mp = _load_mediapipe()
        delegate_enum = (
            mp.tasks.BaseOptions.Delegate.CPU
            if self.delegate == "cpu"
            else mp.tasks.BaseOptions.Delegate.GPU
        )
        options = mp.tasks.vision.HolisticLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(self._model_asset_path),
                delegate=delegate_enum,
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            output_face_blendshapes=True,
            output_segmentation_mask=False,
        )
        last_timestamp_ms = -1
        with mp.tasks.vision.HolisticLandmarker.create_from_options(options) as landmarker:
            for timestamp_us, rgb in self.decoder.iter_rgb_frames(
                source_path,
                sample_fps=self.sample_fps,
            ):
                timestamp_ms = timestamp_us // 1000
                if timestamp_ms <= last_timestamp_ms:
                    raise TrackingContractError(
                        "sampled video timestamps are not monotonic at MediaPipe millisecond precision"
                    )
                last_timestamp_ms = timestamp_ms
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(image, timestamp_ms)
                yield mediapipe_result_to_backend_frame(result, timestamp_us=timestamp_us)
