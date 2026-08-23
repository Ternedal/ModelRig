#!/usr/bin/env python3
"""Dependency-free contract test for BodyRig M1.1 local tracking adapter."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig import local_tracking as lt  # noqa: E402

passed = failed = 0


def check(condition: bool, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def expect(kind: type, fn, label: str) -> None:
    try:
        fn()
    except kind:
        check(True, label)
    except BaseException as exc:  # noqa: BLE001
        check(False, f"{label} (wrong {type(exc).__name__})")
    else:
        check(False, label)


class Point:
    def __init__(self, x: float, y: float, z: float, *, visibility=None, presence=None):
        self.x, self.y, self.z = x, y, z
        self.visibility, self.presence = visibility, presence


def points(count: int, confidence: float | None = None):
    return [Point(0.25, 0.5, -0.1, visibility=confidence) for _ in range(count)]


# Native result mapping stays behind the adapter boundary.
pose = lt._pose(SimpleNamespace(pose_landmarks=[points(33, 0.8)]), 0.5)
check(pose is not None and set(pose) == set(lt._POSE_INDEX), "pose maps only canonical BodyRig ids")
check(pose["left_shoulder"].confidence == 0.8, "pose uses native visibility confidence")
check(lt._pose(SimpleNamespace(pose_landmarks=[]), 0.5) is None, "pose detection loss stays missing")

hand_points = points(21)
hand_result = SimpleNamespace(
    hand_landmarks=[hand_points, hand_points],
    handedness=[
        [SimpleNamespace(category_name="Left", score=0.91)],
        [SimpleNamespace(category_name="Right", score=0.87)],
    ],
)
left, right = lt._hands(hand_result, 0.5)
check(left is not None and right is not None, "left/right hands degrade independently")
check(left["wrist"].confidence == 0.91 and right["wrist"].confidence == 0.87,
      "hand-level confidence is retained without engine types")
unknown_left, unknown_right = lt._hands(
    SimpleNamespace(hand_landmarks=[hand_points], handedness=[[SimpleNamespace(category_name="Unknown", score=1.0)]]),
    0.5,
)
check(unknown_left is None and unknown_right is None, "unknown handedness is omitted rather than invented")

face_result = SimpleNamespace(
    face_landmarks=[points(478)],
    face_blendshapes=[[SimpleNamespace(category_name="eyeBlinkLeft", score=0.75),
                       SimpleNamespace(category_name="jawOpen", score=0.4),
                       SimpleNamespace(category_name="ignoredNativeShape", score=0.99)]],
)
face, expressions = lt._face(face_result, 0.55)
check(face is not None and set(face) == set(lt._FACE_INDEX), "face maps sparse canonical subset")
check(expressions == {"blink_left": 0.75, "jaw_open": 0.4}, "only canonical expression coefficients cross boundary")
empty_face, empty_expr = lt._face(SimpleNamespace(face_landmarks=[], face_blendshapes=[]), 0.5)
check(empty_face is None and empty_expr is None, "face detection loss stays missing")


class FakeCodecContext:
    width = 640
    height = 360
    name = "h264"


class FakeStream:
    type = "video"
    codec_context = FakeCodecContext()
    average_rate = Fraction(30, 1)
    base_rate = Fraction(30, 1)
    duration = 3
    time_base = Fraction(1, 30)
    frames = 3


class FakeFrame:
    time_base = Fraction(1, 30)

    def __init__(self, pts: int):
        self.pts = pts

    def to_ndarray(self, *, format: str):
        check(format == "rgb24", "decoder requests deterministic RGB24 frames")
        return [[[(self.pts + 1) % 255, 0, 0]]]


class FakeContainer:
    duration = 100_000

    def __init__(self):
        self.streams = [FakeStream()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def decode(self, stream):
        assert stream is self.streams[0]
        return iter([FakeFrame(0), FakeFrame(1), FakeFrame(2)])


class FakeAV:
    def open(self, path, mode="r"):
        check(mode == "r", "PyAV source is opened read-only")
        return FakeContainer()


class Options:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class Detector:
    created = {"pose": 0, "hand": 0, "face": 0}

    def __init__(self, kind: str):
        self.kind = kind
        Detector.created[kind] += 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def detect_for_video(self, image, timestamp_ms: int):
        check(timestamp_ms >= 0, f"{self.kind} receives monotonic video timestamp")
        if self.kind == "pose":
            # Deliberately lose detection at the middle frame.
            return SimpleNamespace(pose_landmarks=[] if timestamp_ms == 33 else [points(33, 0.8)])
        if self.kind == "hand":
            return SimpleNamespace(
                hand_landmarks=[hand_points],
                handedness=[[SimpleNamespace(category_name="Left", score=0.9)]],
            )
        return SimpleNamespace(
            face_landmarks=[points(478)],
            face_blendshapes=[[SimpleNamespace(category_name="jawOpen", score=0.2)]],
        )


class Factory:
    def __init__(self, kind: str):
        self.kind = kind

    def create_from_options(self, options):
        return Detector(self.kind)


class Delegate:
    CPU = "cpu"
    GPU = "gpu"


class BaseOptions:
    Delegate = Delegate

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeMP:
    class ImageFormat:
        SRGB = "srgb"

    class Image:
        def __init__(self, *, image_format, data):
            self.image_format, self.data = image_format, data

    class tasks:
        BaseOptions = BaseOptions

        class vision:
            class RunningMode:
                VIDEO = "video"

            PoseLandmarker = Factory("pose")
            HandLandmarker = Factory("hand")
            FaceLandmarker = Factory("face")
            PoseLandmarkerOptions = Options
            HandLandmarkerOptions = Options
            FaceLandmarkerOptions = Options


with tempfile.TemporaryDirectory() as td:
    root = Path(td).resolve()
    models = []
    for name, payload in (("pose.task", b"pose"), ("hand.task", b"hand"), ("face.task", b"face")):
        p = root / name
        p.write_bytes(payload)
        models.append(p)
    source = root / "source.mp4"
    source.write_bytes(b"synthetic-container-placeholder")

    config = lt.LocalTrackingConfig(
        pose_model=models[0], hand_model=models[1], face_model=models[2], delegate="cpu"
    ).validated()
    check(config.model_revision().startswith("sha256:"), "model assets have deterministic provenance digest")
    expect(
        lt.LocalTrackingRuntimeError,
        lambda: lt.LocalTrackingConfig(models[0], models[1], models[2], frame_stride=0).validated(),
        "invalid frame stride fails closed",
    )

    real_require = lt._require_runtime
    lt._require_runtime = lambda: (FakeAV(), FakeMP)  # type: ignore[assignment]
    try:
        backend = lt.MediaPipePyAVTrackingBackend(config)
        facts = backend.inspect(source)
        check(
            facts.codec == "h264" and facts.width == 640 and facts.height == 360
            and facts.duration_us == 100_000 and facts.nominal_fps == 30.0,
            "inspect preserves H.264 media facts",
        )
        first = list(backend.extract(source))
        second = list(backend.extract(source))
    finally:
        lt._require_runtime = real_require  # type: ignore[assignment]

    check([frame.timestamp_us for frame in first] == [0, 33333, 66667],
          "frame timestamps derive from PTS/time-base")
    check(first[1].body is None and first[1].left_hand is not None and first[1].face is not None,
          "subsystems degrade independently without hallucinating body frame")
    check(first == second, "same input/fake engine produces deterministic BackendFrames")
    check(Detector.created == {"pose": 2, "hand": 2, "face": 2},
          "each extract job owns fresh detector state; no cross-job tracker leakage")

# Optional runtime remains truly optional at module import time.
check("av" not in lt.__dict__ and "mediapipe" not in lt.__dict__,
      "adapter module has no import-time PyAV/MediaPipe dependency")

print(f"\n===== BODYRIG LOCAL TRACKING: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
