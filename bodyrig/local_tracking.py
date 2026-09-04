"""Optional local M1.1 video decoder + MediaPipe Tasks extraction backend.

The stable BodyRig contract lives in :mod:`bodyrig.tracking`. This module is an
adapter only: PyAV decodes local video and preserves PTS timestamps; MediaPipe
Tasks extracts body, hand and face observations and maps them immediately to
``BackendFrame``/``Landmark`` values.

Nothing downloads models. Callers must provide three local ``.task`` model
assets explicitly. Imports of PyAV/MediaPipe are lazy so the normal ModelRig
runtime and CI do not acquire this optional ML/video dependency accidentally.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from .tracking import BackendFrame, Landmark, MediaFacts, TrackingContractError

BACKEND_ID = "mediapipe-tasks-pyav"
BACKEND_VERSION = "1"

# MediaPipe Pose Landmarker canonical 33-landmark ordering -> BodyRig M1.1.
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

_HAND_NAMES = (
    "wrist", "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "pinky_mcp", "pinky_pip", "pinky_dip", "pinky_tip",
)

# Stable sparse face subset from MediaPipe's 478-point face topology.
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

_BLENDSHAPES = {
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


class LocalTrackingRuntimeError(TrackingContractError):
    """Optional decoder/extractor runtime is absent or misconfigured."""


@dataclass(frozen=True)
class LocalTrackingConfig:
    pose_model: os.PathLike[str] | str
    hand_model: os.PathLike[str] | str
    face_model: os.PathLike[str] | str
    frame_stride: int = 1
    min_detection_confidence: float = 0.5
    min_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    delegate: str = "cpu"

    def validated(self) -> "LocalTrackingConfig":
        if type(self.frame_stride) is not int or self.frame_stride < 1 or self.frame_stride > 120:
            raise LocalTrackingRuntimeError("frame_stride must be an integer within [1,120]")
        for label, value in (
            ("min_detection_confidence", self.min_detection_confidence),
            ("min_presence_confidence", self.min_presence_confidence),
            ("min_tracking_confidence", self.min_tracking_confidence),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                raise LocalTrackingRuntimeError(f"{label} must be within [0,1]")
        delegate = self.delegate.strip().lower() if isinstance(self.delegate, str) else ""
        if delegate not in {"cpu", "gpu"}:
            raise LocalTrackingRuntimeError("delegate must be cpu or gpu")
        for label, raw in (
            ("pose_model", self.pose_model),
            ("hand_model", self.hand_model),
            ("face_model", self.face_model),
        ):
            path = Path(raw)
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise LocalTrackingRuntimeError(f"{label} must be an existing absolute non-symlink file")
        return self

    def model_revision(self) -> str:
        digest = hashlib.sha256()
        for raw in (self.pose_model, self.hand_model, self.face_model):
            path = Path(raw)
            digest.update(path.name.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            digest.update(b"\0")
        return "sha256:" + digest.hexdigest()


def _require_runtime() -> tuple[Any, Any]:
    try:
        import av  # type: ignore
    except ImportError as exc:
        raise LocalTrackingRuntimeError(
            "PyAV is not installed; install the pinned BodyRig tracking runtime"
        ) from exc
    try:
        import mediapipe as mp  # type: ignore
    except ImportError as exc:
        raise LocalTrackingRuntimeError(
            "MediaPipe is not installed; install the pinned BodyRig tracking runtime"
        ) from exc
    return av, mp


def _fraction(value: object) -> float:
    if value is None:
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    return result if result > 0.0 else 0.0


def _duration_us(container: Any, stream: Any) -> int:
    if getattr(stream, "duration", None) is not None and getattr(stream, "time_base", None) is not None:
        value = int(round(float(stream.duration * stream.time_base) * 1_000_000))
        if value > 0:
            return value
    # PyAV exposes container.duration in FFmpeg AV_TIME_BASE units (microseconds).
    container_duration = getattr(container, "duration", None)
    if isinstance(container_duration, int) and container_duration > 0:
        return container_duration
    frames = getattr(stream, "frames", 0) or 0
    fps = _fraction(getattr(stream, "average_rate", None))
    if frames and fps:
        return int(round(frames / fps * 1_000_000))
    raise LocalTrackingRuntimeError("video duration is unavailable")


def _codec_name(stream: Any) -> str:
    context = getattr(stream, "codec_context", None)
    name = getattr(context, "name", None) or getattr(getattr(stream, "codec", None), "name", None)
    if not isinstance(name, str) or not name.strip():
        raise LocalTrackingRuntimeError("video codec identity is unavailable")
    return name.strip().lower()


def _confidence(point: Any, fallback: float) -> float:
    for name in ("visibility", "presence"):
        value = getattr(point, name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= float(value) <= 1.0:
            return float(value)
    return float(fallback)


def _landmark(point: Any, fallback_confidence: float) -> Landmark:
    return Landmark(
        x=float(point.x),
        y=float(point.y),
        z=float(point.z),
        confidence=_confidence(point, fallback_confidence),
    )


def _pose(result: Any, fallback: float) -> Mapping[str, Landmark] | None:
    groups = getattr(result, "pose_landmarks", None) or []
    if not groups:
        return None
    points = groups[0]
    if len(points) < 33:
        raise LocalTrackingRuntimeError("MediaPipe pose result has fewer than 33 landmarks")
    return {name: _landmark(points[index], fallback) for name, index in _POSE_INDEX.items()}


def _hands(result: Any, fallback: float) -> tuple[Mapping[str, Landmark] | None, Mapping[str, Landmark] | None]:
    groups = getattr(result, "hand_landmarks", None) or []
    handedness = getattr(result, "handedness", None) or []
    left = right = None
    for index, points in enumerate(groups):
        if len(points) < len(_HAND_NAMES):
            raise LocalTrackingRuntimeError("MediaPipe hand result has fewer than 21 landmarks")
        categories = handedness[index] if index < len(handedness) else []
        category = categories[0] if categories else None
        label = str(getattr(category, "category_name", "")).strip().lower()
        score = getattr(category, "score", None)
        hand_confidence = float(score) if isinstance(score, (int, float)) and 0.0 <= float(score) <= 1.0 else fallback
        mapped = {name: _landmark(points[pos], hand_confidence) for pos, name in enumerate(_HAND_NAMES)}
        if label == "left" and left is None:
            left = mapped
        elif label == "right" and right is None:
            right = mapped
        # Unknown/duplicate handedness is deliberately omitted rather than
        # inventing which canonical side it belongs to.
    return left, right


def _face(result: Any, fallback: float) -> tuple[Mapping[str, Landmark] | None, Mapping[str, float] | None]:
    groups = getattr(result, "face_landmarks", None) or []
    face = None
    if groups:
        points = groups[0]
        maximum = max(_FACE_INDEX.values())
        if len(points) <= maximum:
            raise LocalTrackingRuntimeError("MediaPipe face result lacks canonical sparse landmark indices")
        face = {name: _landmark(points[index], fallback) for name, index in _FACE_INDEX.items()}

    expressions = None
    blend_groups = getattr(result, "face_blendshapes", None) or []
    if blend_groups:
        selected: dict[str, float] = {}
        for category in blend_groups[0]:
            native = str(getattr(category, "category_name", ""))
            canonical = _BLENDSHAPES.get(native)
            score = getattr(category, "score", None)
            if canonical is not None and isinstance(score, (int, float)) and not isinstance(score, bool):
                selected[canonical] = max(0.0, min(1.0, float(score)))
        expressions = selected or None
    return face, expressions


class MediaPipePyAVTrackingBackend:
    """One-job local extractor; detector state is never shared across jobs."""

    backend_id = BACKEND_ID
    backend_version = BACKEND_VERSION

    def __init__(self, config: LocalTrackingConfig) -> None:
        self.config = config.validated()
        self.model_revision = self.config.model_revision()

    def inspect(self, source_path: os.PathLike[str] | str) -> MediaFacts:
        av, _mp = _require_runtime()
        try:
            with av.open(str(source_path), mode="r") as container:
                streams = [stream for stream in container.streams if getattr(stream, "type", None) == "video"]
                if len(streams) != 1:
                    raise LocalTrackingRuntimeError("source must contain exactly one video stream")
                stream = streams[0]
                width = int(getattr(stream.codec_context, "width", 0) or 0)
                height = int(getattr(stream.codec_context, "height", 0) or 0)
                fps = _fraction(getattr(stream, "average_rate", None)) or _fraction(getattr(stream, "base_rate", None))
                if width <= 0 or height <= 0 or fps <= 0:
                    raise LocalTrackingRuntimeError("video geometry/frame-rate metadata is unavailable")
                return MediaFacts(
                    codec=_codec_name(stream),
                    width=width,
                    height=height,
                    duration_us=_duration_us(container, stream),
                    nominal_fps=fps,
                )
        except LocalTrackingRuntimeError:
            raise
        except Exception as exc:
            raise LocalTrackingRuntimeError(f"video inspection failed: {type(exc).__name__}: {exc}") from exc

    def _detectors(self, mp: Any, stack: ExitStack) -> tuple[Any, Any, Any]:
        vision = mp.tasks.vision
        delegate_name = self.config.delegate.strip().lower()
        delegate = mp.tasks.BaseOptions.Delegate.CPU if delegate_name == "cpu" else mp.tasks.BaseOptions.Delegate.GPU

        def base(path: os.PathLike[str] | str) -> Any:
            return mp.tasks.BaseOptions(model_asset_path=str(path), delegate=delegate)

        common = {
            "running_mode": vision.RunningMode.VIDEO,
            "min_tracking_confidence": float(self.config.min_tracking_confidence),
        }
        pose = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=base(self.config.pose_model),
                num_poses=1,
                min_pose_detection_confidence=float(self.config.min_detection_confidence),
                min_pose_presence_confidence=float(self.config.min_presence_confidence),
                **common,
            )
        )
        hand = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=base(self.config.hand_model),
                num_hands=2,
                min_hand_detection_confidence=float(self.config.min_detection_confidence),
                min_hand_presence_confidence=float(self.config.min_presence_confidence),
                **common,
            )
        )
        face = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=base(self.config.face_model),
                num_faces=1,
                min_face_detection_confidence=float(self.config.min_detection_confidence),
                min_face_presence_confidence=float(self.config.min_presence_confidence),
                output_face_blendshapes=True,
                **common,
            )
        )
        return stack.enter_context(pose), stack.enter_context(hand), stack.enter_context(face)

    def extract(self, source_path: os.PathLike[str] | str) -> Iterable[BackendFrame]:
        av, mp = _require_runtime()
        fallback = float(self.config.min_presence_confidence)
        try:
            with av.open(str(source_path), mode="r") as container, ExitStack() as stack:
                streams = [stream for stream in container.streams if getattr(stream, "type", None) == "video"]
                if len(streams) != 1:
                    raise LocalTrackingRuntimeError("source must contain exactly one video stream")
                stream = streams[0]
                pose_detector, hand_detector, face_detector = self._detectors(mp, stack)
                last_us = -1
                last_ms = -1
                decoded_index = 0
                for frame in container.decode(stream):
                    current_index = decoded_index
                    decoded_index += 1
                    if current_index % self.config.frame_stride:
                        continue
                    pts = getattr(frame, "pts", None)
                    time_base = getattr(frame, "time_base", None) or getattr(stream, "time_base", None)
                    if pts is None or time_base is None:
                        raise LocalTrackingRuntimeError("decoded frame lacks PTS/time-base")
                    timestamp_us = int(round(float(Fraction(pts) * Fraction(time_base)) * 1_000_000))
                    if timestamp_us < 0 or timestamp_us <= last_us:
                        raise LocalTrackingRuntimeError("decoded frame timestamps are not strictly increasing")
                    last_us = timestamp_us
                    timestamp_ms = max(timestamp_us // 1000, last_ms + 1)
                    last_ms = timestamp_ms

                    rgb = frame.to_ndarray(format="rgb24")
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    pose_result = pose_detector.detect_for_video(image, timestamp_ms)
                    hand_result = hand_detector.detect_for_video(image, timestamp_ms)
                    face_result = face_detector.detect_for_video(image, timestamp_ms)
                    left, right = _hands(hand_result, fallback)
                    face, expressions = _face(face_result, fallback)
                    yield BackendFrame(
                        timestamp_us=timestamp_us,
                        body=_pose(pose_result, fallback),
                        left_hand=left,
                        right_hand=right,
                        face=face,
                        expressions=expressions,
                    )
        except LocalTrackingRuntimeError:
            raise
        except Exception as exc:
            raise LocalTrackingRuntimeError(f"local tracking extraction failed: {type(exc).__name__}: {exc}") from exc
