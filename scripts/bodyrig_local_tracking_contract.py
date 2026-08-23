#!/usr/bin/env python3
"""Dependency-free contract for the optional BodyRig M1.1 local tracker."""
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

def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")

class Point:
    def __init__(self, *, confidence=None):
        self.x, self.y, self.z = 0.25, 0.5, -0.1
        self.visibility, self.presence = confidence, None

def points(n: int, confidence=None):
    return [Point(confidence=confidence) for _ in range(n)]

pose = lt._pose(SimpleNamespace(pose_landmarks=[points(33, 0.8)]), 0.5)
check(pose is not None and set(pose) == set(lt._POSE_INDEX), "pose maps only canonical ids")
check(lt._pose(SimpleNamespace(pose_landmarks=[]), 0.5) is None, "pose loss stays missing")

hands = SimpleNamespace(
    hand_landmarks=[points(21), points(21)],
    handedness=[[SimpleNamespace(category_name="Left", score=0.91)],
                [SimpleNamespace(category_name="Right", score=0.87)]],
)
left, right = lt._hands(hands, 0.5)
check(left is not None and right is not None, "left/right hands map independently")
check(left["wrist"].confidence == 0.91 and right["wrist"].confidence == 0.87,
      "hand classification score survives as confidence")
unknown = SimpleNamespace(
    hand_landmarks=[points(21)],
    handedness=[[SimpleNamespace(category_name="Unknown", score=1.0)]],
)
check(lt._hands(unknown, 0.5) == (None, None), "unknown handedness is not invented")

face = SimpleNamespace(
    face_landmarks=[points(478)],
    face_blendshapes=[[SimpleNamespace(category_name="eyeBlinkLeft", score=0.75),
                       SimpleNamespace(category_name="jawOpen", score=0.4),
                       SimpleNamespace(category_name="engineOnly", score=1.0)]],
)
face_points, expressions = lt._face(face, 0.55)
check(face_points is not None and set(face_points) == set(lt._FACE_INDEX), "face emits stable sparse subset")
check(expressions == {"blink_left": 0.75, "jaw_open": 0.4}, "engine-only expressions do not leak")

class FakeCodec:
    width, height, name = 640, 360, "h264"
class FakeStream:
    type = "video"
    codec_context = FakeCodec()
    average_rate = base_rate = Fraction(30, 1)
    duration, time_base, frames = 3, Fraction(1, 30), 3
class FakeFrame:
    time_base = Fraction(1, 30)
    def __init__(self, pts): self.pts = pts
    def to_ndarray(self, *, format):
        check(format == "rgb24", "decode normalizes frame to RGB24")
        return [[[self.pts + 1, 0, 0]]]
class FakeContainer:
    duration = 100_000
    def __init__(self): self.streams = [FakeStream()]
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def decode(self, stream): return iter([FakeFrame(0), FakeFrame(1), FakeFrame(2)])
class FakeAV:
    def open(self, path, mode="r"):
        check(mode == "r", "video source is opened read-only")
        return FakeContainer()
class Options:
    def __init__(self, **kwargs): self.kwargs = kwargs
class Detector:
    created = {"pose": 0, "hand": 0, "face": 0}
    def __init__(self, kind):
        self.kind = kind; Detector.created[kind] += 1
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def detect_for_video(self, image, timestamp_ms):
        if self.kind == "pose":
            return SimpleNamespace(pose_landmarks=[] if timestamp_ms == 33 else [points(33, 0.8)])
        if self.kind == "hand":
            return SimpleNamespace(hand_landmarks=[points(21)],
                                   handedness=[[SimpleNamespace(category_name="Left", score=0.9)]])
        return SimpleNamespace(face_landmarks=[points(478)],
                               face_blendshapes=[[SimpleNamespace(category_name="jawOpen", score=0.2)]])
class Factory:
    def __init__(self, kind): self.kind = kind
    def create_from_options(self, options): return Detector(self.kind)
class Delegate:
    CPU, GPU = "cpu", "gpu"
class BaseOptions:
    Delegate = Delegate
    def __init__(self, **kwargs): self.kwargs = kwargs
class FakeMP:
    class ImageFormat: SRGB = "srgb"
    class Image:
        def __init__(self, *, image_format, data): self.image_format, self.data = image_format, data
    class tasks:
        BaseOptions = BaseOptions
        class vision:
            class RunningMode: VIDEO = "video"
            PoseLandmarker, HandLandmarker, FaceLandmarker = Factory("pose"), Factory("hand"), Factory("face")
            PoseLandmarkerOptions = HandLandmarkerOptions = FaceLandmarkerOptions = Options

with tempfile.TemporaryDirectory() as td:
    root = Path(td).resolve()
    model_paths = []
    for name in ("pose.task", "hand.task", "face.task"):
        path = root / name; path.write_bytes(name.encode()); model_paths.append(path)
    source = root / "fixture.mp4"; source.write_bytes(b"fixture")
    config = lt.LocalTrackingConfig(*model_paths).validated()
    check(config.model_revision().startswith("sha256:"), "model assets have hash-bound revision")
    real = lt._require_runtime
    lt._require_runtime = lambda: (FakeAV(), FakeMP)  # type: ignore[assignment]
    try:
        backend = lt.MediaPipePyAVTrackingBackend(config)
        facts = backend.inspect(source)
        first = list(backend.extract(source)); second = list(backend.extract(source))
    finally:
        lt._require_runtime = real  # type: ignore[assignment]
    check((facts.codec, facts.width, facts.height, facts.duration_us, facts.nominal_fps) ==
          ("h264", 640, 360, 100_000, 30.0), "inspect preserves H.264 media facts")
    check([f.timestamp_us for f in first] == [0, 33333, 66667], "timestamps derive from PTS/time-base")
    check(first[1].body is None and first[1].left_hand is not None and first[1].face is not None,
          "detection loss degrades subsystems independently")
    check(first == second, "identical input produces deterministic backend frames")
    check(Detector.created == {"pose": 2, "hand": 2, "face": 2}, "detector state is fresh per job")

check("av" not in lt.__dict__ and "mediapipe" not in lt.__dict__, "optional runtime is lazy-imported")
print(f"\n===== BODYRIG LOCAL TRACKING: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
