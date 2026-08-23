"""Optional offline RTMW/RTMLib backend for BodyRig M1.1 video ingest.

This adapter deliberately accepts *local model files only*. It never passes a
URL or missing path to RTMLib, because RTMLib's convenience API may otherwise
download checkpoints. ONNX Runtime telemetry is disabled for the process before
RTMLib/onnxruntime are imported.

The backend emits only BodyRig's engine-neutral ``BackendFrame`` values. RTMW
native 133-keypoint arrays never cross the adapter boundary.
"""
from __future__ import annotations

import hashlib
import math
import os
import stat
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Iterator, Sequence

# The full process-lifetime opt-out must exist before ONNX Runtime initializes.
_ORT_WAS_PRELOADED = "onnxruntime" in sys.modules
_ORT_GUARD_WAS_PRESET = os.environ.get("ORT_DISABLE_TELEMETRY") == "1"
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

from .tracking import BackendFrame, Landmark, MediaFacts, TrackingContractError

RTMLIB_VERSION = "0.0.16"
ONNXRUNTIME_VERSION = "1.28.0"
OPENCV_HEADLESS_VERSION = "4.14.0.94"
NUMPY_VERSION = "2.5.2"
TQDM_VERSION = "4.70.0"

# COCO-WholeBody / RTMW native layout: 17 body + 6 feet + 68 face + 21 left
# hand + 21 right hand = 133 keypoints. Keep these indices private so another
# extractor can implement the same BodyRig schema without inheriting RTMW ids.
_BODY_INDEX = {
    "nose": 0,
    "left_eye": 1,
    "right_eye": 2,
    "left_ear": 3,
    "right_ear": 4,
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_elbow": 7,
    "right_elbow": 8,
    "left_wrist": 9,
    "right_wrist": 10,
    "left_hip": 11,
    "right_hip": 12,
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
    "left_heel": 19,
    "right_heel": 22,
    "left_foot_index": 17,
    "right_foot_index": 20,
}

# 68-point face segment starts at native index 23. The offsets follow the
# standard 68-point facial landmark ordering used by COCO-WholeBody.
_FACE_BASE = 23
_FACE_INDEX = {
    "chin": _FACE_BASE + 8,
    "left_brow_outer": _FACE_BASE + 17,
    "left_brow_inner": _FACE_BASE + 21,
    "right_brow_inner": _FACE_BASE + 22,
    "right_brow_outer": _FACE_BASE + 26,
    "nose_tip": _FACE_BASE + 30,
    "left_eye_outer": _FACE_BASE + 36,
    "left_eye_inner": _FACE_BASE + 39,
    "right_eye_inner": _FACE_BASE + 42,
    "right_eye_outer": _FACE_BASE + 45,
    "mouth_left": _FACE_BASE + 48,
    "mouth_right": _FACE_BASE + 54,
    "upper_lip": _FACE_BASE + 51,
    "lower_lip": _FACE_BASE + 57,
}

_HAND_NAMES = (
    "wrist",
    "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "pinky_mcp", "pinky_pip", "pinky_dip", "pinky_tip",
)
_LEFT_HAND_INDEX = {name: 91 + index for index, name in enumerate(_HAND_NAMES)}
_RIGHT_HAND_INDEX = {name: 112 + index for index, name in enumerate(_HAND_NAMES)}


class IngestDependencyError(RuntimeError):
    """Optional ingest runtime is absent, mismatched, or unsafe to initialize."""


def _installed_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError as exc:
        raise IngestDependencyError(
            f"missing optional dependency {distribution}; run the BodyRig ingest installer"
        ) from exc


def _require_exact_runtime() -> None:
    expected = {
        "rtmlib": RTMLIB_VERSION,
        "onnxruntime": ONNXRUNTIME_VERSION,
        "opencv-python-headless": OPENCV_HEADLESS_VERSION,
        "numpy": NUMPY_VERSION,
        "tqdm": TQDM_VERSION,
    }
    mismatches = []
    for distribution, version in expected.items():
        actual = _installed_version(distribution)
        if actual != version:
            mismatches.append(f"{distribution}={actual} (expected {version})")
    if mismatches:
        raise IngestDependencyError("optional ingest runtime version mismatch: " + "; ".join(mismatches))


def _load_cv2():
    _require_exact_runtime()
    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - platform import details
        raise IngestDependencyError(f"cannot import cv2: {type(exc).__name__}") from exc
    return cv2


def _load_rtmlib():
    if _ORT_WAS_PRELOADED and not _ORT_GUARD_WAS_PRESET:
        raise IngestDependencyError(
            "onnxruntime was imported before ORT_DISABLE_TELEMETRY=1; restart the process before BodyRig ingest"
        )
    if os.environ.get("ORT_DISABLE_TELEMETRY") != "1":
        raise IngestDependencyError("ORT_DISABLE_TELEMETRY must remain 1 for BodyRig ingest")
    _require_exact_runtime()
    try:
        import onnxruntime as ort  # type: ignore
        # Defense in depth. The environment variable above is the process-lifetime
        # guard; this API additionally suppresses telemetry after import.
        ort.disable_telemetry_events()
        from rtmlib import Wholebody  # type: ignore
    except Exception as exc:  # pragma: no cover - platform import details
        raise IngestDependencyError(f"cannot initialize RTMW runtime: {type(exc).__name__}") from exc
    return Wholebody


@dataclass(frozen=True)
class _ModelSnapshot:
    sha256: str
    size: int
    device: int
    inode: int
    mtime_ns: int


def _capture_model(path: Path, label: str) -> _ModelSnapshot:
    """Hash one local non-symlink model and bind the digest to file identity."""
    try:
        path_before = os.lstat(path)
    except OSError as exc:
        raise TrackingContractError(f"{label} model cannot be inspected") from exc
    if stat.S_ISLNK(path_before.st_mode) or not stat.S_ISREG(path_before.st_mode):
        raise TrackingContractError(f"{label} model must be a local non-symlink regular file")
    digest = hashlib.sha256()
    total = 0
    try:
        with open(path, "rb") as handle:
            opened_before = os.fstat(handle.fileno())
            if (opened_before.st_dev, opened_before.st_ino) != (path_before.st_dev, path_before.st_ino):
                raise TrackingContractError(f"{label} model identity changed before hashing")
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                digest.update(block)
            opened_after = os.fstat(handle.fileno())
    except TrackingContractError:
        raise
    except OSError as exc:
        raise TrackingContractError(f"{label} model cannot be hashed") from exc
    try:
        path_after = os.lstat(path)
    except OSError as exc:
        raise TrackingContractError(f"{label} model disappeared while hashing") from exc
    before_identity = (
        opened_before.st_dev, opened_before.st_ino, opened_before.st_size, opened_before.st_mtime_ns
    )
    after_identity = (
        opened_after.st_dev, opened_after.st_ino, opened_after.st_size, opened_after.st_mtime_ns
    )
    path_identity = (
        path_after.st_dev, path_after.st_ino, path_after.st_size, path_after.st_mtime_ns
    )
    if before_identity != after_identity or after_identity != path_identity or total != opened_after.st_size:
        raise TrackingContractError(f"{label} model changed while hashing")
    return _ModelSnapshot(
        sha256=digest.hexdigest(),
        size=total,
        device=int(opened_after.st_dev),
        inode=int(opened_after.st_ino),
        mtime_ns=int(opened_after.st_mtime_ns),
    )


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
    """Deterministic CPU decode/sampling for the M1.1 CFR MP4/H.264 baseline."""

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
        return MediaFacts(
            codec=codec,
            width=width,
            height=height,
            duration_us=max(1, int(round(frame_count * 1_000_000.0 / fps))),
            nominal_fps=fps,
        )

    def iter_bgr_frames(
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
                yield timestamp_us, bgr
                emitted += 1
                if step_us:
                    next_emit_us = emitted * step_us
        finally:
            capture.release()


def _sequence_length(value: Any) -> int:
    try:
        return len(value)
    except TypeError as exc:
        raise TrackingContractError("RTMW result must be a sized array") from exc


def _row(value: Any, index: int) -> Sequence[Any]:
    try:
        return value[index]
    except (IndexError, KeyError, TypeError) as exc:
        raise TrackingContractError("RTMW result shape is invalid") from exc


def _score_mean(scores: Any, person: int) -> float:
    row = _row(scores, person)
    values: list[float] = []
    for index in range(min(23, _sequence_length(row))):
        try:
            score = float(row[index])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(score):
            values.append(max(0.0, min(1.0, score)))
    return sum(values) / len(values) if values else -1.0


def _select_primary(keypoints: Any, scores: Any) -> int | None:
    count = min(_sequence_length(keypoints), _sequence_length(scores))
    if count <= 0:
        return None
    # Deterministic tie-break: earliest detector result wins equal mean body score.
    return max(range(count), key=lambda index: (_score_mean(scores, index), -index))


def _map_part(
    keypoints: Any,
    scores: Any,
    *,
    person: int,
    mapping: dict[str, int],
    width: int,
    height: int,
    min_score: float,
) -> dict[str, Landmark] | None:
    point_row = _row(keypoints, person)
    score_row = _row(scores, person)
    result: dict[str, Landmark] = {}
    for name, index in mapping.items():
        if index >= _sequence_length(point_row) or index >= _sequence_length(score_row):
            raise TrackingContractError(f"RTMW result is missing keypoint index {index}")
        point = _row(point_row, index)
        if _sequence_length(point) < 2:
            raise TrackingContractError(f"RTMW keypoint {index} lacks x/y")
        try:
            x = float(point[0])
            y = float(point[1])
            confidence = float(score_row[index])
        except (TypeError, ValueError, IndexError) as exc:
            raise TrackingContractError(f"RTMW keypoint {index} is not numeric") from exc
        if not all(math.isfinite(value) for value in (x, y, confidence)):
            raise TrackingContractError(f"RTMW keypoint {index} is non-finite")
        confidence = max(0.0, min(1.0, confidence))
        if confidence < min_score:
            continue
        if x < 0.0 or y < 0.0 or x > width or y > height:
            # An off-frame estimate is not a visible landmark observation.
            continue
        result[name] = Landmark(
            x=min(1.0, max(0.0, x / width)),
            y=min(1.0, max(0.0, y / height)),
            z=0.0,
            confidence=confidence,
        )
    return result or None


def rtmw_result_to_backend_frame(
    keypoints: Any,
    scores: Any,
    *,
    timestamp_us: int,
    width: int,
    height: int,
    min_score: float = 0.3,
) -> BackendFrame:
    """Map one RTMW result into BodyRig semantic landmarks."""
    if width <= 0 or height <= 0:
        raise TrackingContractError("RTMW mapping requires positive frame dimensions")
    if not math.isfinite(min_score) or not 0.0 <= min_score <= 1.0:
        raise TrackingContractError("min_score must be within [0,1]")
    person = _select_primary(keypoints, scores)
    if person is None:
        return BackendFrame(timestamp_us=timestamp_us)
    return BackendFrame(
        timestamp_us=timestamp_us,
        body=_map_part(
            keypoints, scores, person=person, mapping=_BODY_INDEX,
            width=width, height=height, min_score=min_score,
        ),
        left_hand=_map_part(
            keypoints, scores, person=person, mapping=_LEFT_HAND_INDEX,
            width=width, height=height, min_score=min_score,
        ),
        right_hand=_map_part(
            keypoints, scores, person=person, mapping=_RIGHT_HAND_INDEX,
            width=width, height=height, min_score=min_score,
        ),
        face=_map_part(
            keypoints, scores, person=person, mapping=_FACE_INDEX,
            width=width, height=height, min_score=min_score,
        ),
        expressions=None,
    )


class RtmwWholeBodyBackend:
    """Local CPU RTMW whole-body extraction with explicit model provenance."""

    backend_id = "rtmw-rtmlib-onnxruntime"
    backend_version = f"rtmlib-{RTMLIB_VERSION}/onnxruntime-{ONNXRUNTIME_VERSION}"

    def __init__(
        self,
        *,
        detector_model_path: os.PathLike[str] | str,
        pose_model_path: os.PathLike[str] | str,
        detector_input_size: tuple[int, int] = (640, 640),
        pose_input_size: tuple[int, int] = (192, 256),
        sample_fps: float | None = 15.0,
        min_score: float = 0.3,
        decoder: OpenCvVideoDecoder | None = None,
    ) -> None:
        self._detector_path = Path(detector_model_path).resolve()
        self._pose_path = Path(pose_model_path).resolve()
        self._detector_snapshot = _capture_model(self._detector_path, "detector")
        self._pose_snapshot = _capture_model(self._pose_path, "pose")
        self.detector_input_size = detector_input_size
        self.pose_input_size = pose_input_size
        self.sample_fps = sample_fps
        self.min_score = min_score
        self.decoder = decoder or OpenCvVideoDecoder()
        self.model_revision = (
            f"det-sha256:{self._detector_snapshot.sha256};"
            f"pose-sha256:{self._pose_snapshot.sha256}"
        )

    def _assert_models_unchanged(self) -> None:
        detector = _capture_model(self._detector_path, "detector")
        pose = _capture_model(self._pose_path, "pose")
        if detector != self._detector_snapshot or pose != self._pose_snapshot:
            raise TrackingContractError("RTMW model files changed after backend initialization")

    def inspect(self, source_path: os.PathLike[str] | str) -> MediaFacts:
        return self.decoder.inspect(source_path)

    def extract(self, source_path: os.PathLike[str] | str) -> Iterator[BackendFrame]:
        self._assert_models_unchanged()
        Wholebody = _load_rtmlib()
        facts = self.decoder.inspect(source_path)
        # Supplying existing local paths prevents RTMLib's missing-path/URL
        # checkpoint downloader from becoming part of this boundary.
        wholebody = Wholebody(
            det=str(self._detector_path),
            det_input_size=self.detector_input_size,
            pose=str(self._pose_path),
            pose_input_size=self.pose_input_size,
            to_openpose=False,
            backend="onnxruntime",
            device="cpu",
        )
        for timestamp_us, bgr in self.decoder.iter_bgr_frames(
            source_path,
            sample_fps=self.sample_fps,
        ):
            keypoints, scores = wholebody(bgr)
            yield rtmw_result_to_backend_frame(
                keypoints,
                scores,
                timestamp_us=timestamp_us,
                width=facts.width,
                height=facts.height,
                min_score=self.min_score,
            )
        # A successful result must remain bound to the exact model bytes that
        # were recorded in backend provenance.
        self._assert_models_unchanged()
