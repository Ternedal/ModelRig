#!/usr/bin/env python3
"""BodyRig M1.1 tracking-contract regression suite.

Uses tiny synthetic source bytes and a deterministic fake backend. No ML model,
network access, video download or heavyweight dependency is allowed in CI for
this contract slice.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile

from bodyrig.tracking import (
    BackendFrame,
    Landmark,
    MediaFacts,
    TrackingContractError,
    build_tracking_timeline,
    canonical_tracking_json,
)

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def expect(kind: type[BaseException], fn, label: str) -> BaseException | None:
    try:
        fn()
    except kind as exc:
        check(True, f"{label} ({type(exc).__name__})")
        return exc
    except BaseException as exc:  # noqa: BLE001
        check(False, f"{label} -- wrong exception {type(exc).__name__}: {exc}")
        return exc
    check(False, f"{label} -- no exception")
    return None


def lm(x: float, y: float, confidence: float = 0.9, z: float = 0.0) -> Landmark:
    return Landmark(x=x, y=y, z=z, confidence=confidence)


class FakeBackend:
    backend_id = "fixture-tracker"
    backend_version = "1.0"
    model_revision = "fixture-r1"

    def __init__(self, frames: list[BackendFrame]) -> None:
        self.frames = tuple(frames)
        self.inspect_calls: list[str] = []
        self.extract_calls: list[str] = []

    def inspect(self, source_path) -> MediaFacts:
        self.inspect_calls.append(pathlib.Path(source_path).name)
        return MediaFacts(
            codec="h264",
            width=1920,
            height=1080,
            duration_us=1_000_000,
            nominal_fps=30.0,
        )

    def extract(self, source_path):
        self.extract_calls.append(pathlib.Path(source_path).name)
        return iter(self.frames)


FULL = BackendFrame(
    timestamp_us=0,
    body={
        "left_shoulder": lm(0.4, 0.3, 0.94),
        "right_shoulder": lm(0.6, 0.3, 0.92),
        "left_hip": lm(0.45, 0.65, 0.91),
        "right_hip": lm(0.55, 0.65, 0.90),
    },
    left_hand={"wrist": lm(0.35, 0.55, 0.82), "index_tip": lm(0.31, 0.48, 0.78)},
    right_hand={"wrist": lm(0.65, 0.55, 0.84), "index_tip": lm(0.69, 0.48, 0.80)},
    face={"nose_tip": lm(0.5, 0.18, 0.96), "mouth_left": lm(0.47, 0.23, 0.93)},
    expressions={"jaw_open": 0.2, "blink_left": 0.0, "blink_right": 0.0},
)
BODY_ONLY = BackendFrame(
    timestamp_us=33333,
    body={"left_shoulder": lm(0.41, 0.3, 0.88), "right_shoulder": lm(0.61, 0.3, 0.87)},
)
LOSS = BackendFrame(timestamp_us=66666)
EXPRESSIONS_ONLY = BackendFrame(
    timestamp_us=99999,
    expressions={"jaw_open": 0.6, "blink_left": 0.1},
)


with tempfile.TemporaryDirectory(prefix="bodyrig-m11-") as td:
    root = pathlib.Path(td)
    first = root / "subject-a.mp4"
    second = root / "subject-b.mp4"
    first.write_bytes(b"synthetic-mp4-h264-a")
    second.write_bytes(b"synthetic-mp4-h264-b")

    backend = FakeBackend([FULL, BODY_ONLY, LOSS, EXPRESSIONS_ONLY])
    timeline = build_tracking_timeline(
        first,
        backend=backend,
        permission_assertion="user-supplied local source with permission",
    )

    check(timeline["schema"] == "bodyrig.tracking/v1", "stable tracking schema id")
    check(timeline["coordinate_space"].startswith("image_normalized_"),
          "renderer-independent normalized coordinate space")
    check(timeline["source"]["media"]["codec"] == "h264", "media facts preserve codec")
    check(timeline["source"]["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest(),
          "source provenance uses exact content hash")
    check(timeline["source"]["bytes"] == len(first.read_bytes()), "source byte count is exact")
    check("source_path" not in timeline["source"] and "filename" not in timeline["source"],
          "serialized provenance contains no source path/name field")
    serialized = canonical_tracking_json(timeline)
    check(str(first) not in serialized and first.name not in serialized,
          "canonical timeline does not leak source path or filename")
    check(timeline["backend"] == {
        "id": "fixture-tracker", "version": "1.0", "model_revision": "fixture-r1"
    }, "backend identity is provenance only")
    check(timeline["production_activation"] is False, "tracking slice cannot activate production")

    # LOSS is attempted but deliberately absent from output: no zero-filled or
    # interpolated fake person appears at timestamp 66666.
    timestamps = [frame["timestamp_us"] for frame in timeline["frames"]]
    check(timestamps == [0, 33333, 99999], "detection loss produces a truthful timestamp gap")
    check(all(frame["timestamp_us"] != 66666 for frame in timeline["frames"]),
          "no hallucinated landmark frame during total detection loss")

    body_cov = timeline["coverage"]["body"]
    hand_cov = timeline["coverage"]["hands"]
    face_cov = timeline["coverage"]["face"]
    check(body_cov["total_frames"] == 4 and body_cov["observed_frames"] == 2
          and body_cov["coverage"] == 0.5,
          "body coverage counts attempted detection-loss frame")
    check(hand_cov["observed_frames"] == 1 and hand_cov["coverage"] == 0.25,
          "hands degrade independently")
    check(face_cov["observed_frames"] == 2 and face_cov["coverage"] == 0.5,
          "face landmarks and expression-only observations count independently")
    check(face_cov["confidence_frames"] == 1,
          "expression intensity is not fabricated into detector confidence")
    check("more_visible_hands" in timeline["recommendations"],
          "low hand coverage creates actionable recommendation")

    # Ordering/canonicalization is deterministic even if the backend's maps are
    # inserted in a different order.
    reordered = BackendFrame(
        timestamp_us=0,
        body={
            "right_hip": lm(0.55, 0.65, 0.90),
            "left_hip": lm(0.45, 0.65, 0.91),
            "right_shoulder": lm(0.6, 0.3, 0.92),
            "left_shoulder": lm(0.4, 0.3, 0.94),
        },
        right_hand={"index_tip": lm(0.69, 0.48, 0.80), "wrist": lm(0.65, 0.55, 0.84)},
        left_hand={"index_tip": lm(0.31, 0.48, 0.78), "wrist": lm(0.35, 0.55, 0.82)},
        face={"mouth_left": lm(0.47, 0.23, 0.93), "nose_tip": lm(0.5, 0.18, 0.96)},
        expressions={"blink_right": 0.0, "blink_left": 0.0, "jaw_open": 0.2},
    )
    one_a = build_tracking_timeline(first, backend=FakeBackend([FULL]), permission_assertion="ok")
    one_b = build_tracking_timeline(first, backend=FakeBackend([reordered]), permission_assertion="ok")
    check(canonical_tracking_json(one_a) == canonical_tracking_json(one_b),
          "same normalized observation is byte-deterministic")

    # Separate source jobs retain no prior source identity. The backend object is
    # deliberately reused to make accidental module/job globals visible.
    second_timeline = build_tracking_timeline(second, backend=backend, permission_assertion="ok")
    check(second_timeline["source"]["sha256"] != timeline["source"]["sha256"],
          "second job gets its own source identity")
    check(timeline["source"]["sha256"] not in canonical_tracking_json(second_timeline),
          "second job contains no first-job source identity")
    check(backend.inspect_calls[-2:] == [first.name, second.name]
          and backend.extract_calls[-2:] == [first.name, second.name],
          "backend is called independently for each source job")

    # Fail-closed contract cases.
    expect(
        TrackingContractError,
        lambda: build_tracking_timeline(
            first,
            backend=FakeBackend([
                BackendFrame(timestamp_us=0, body={"engine_joint_42": lm(0.5, 0.5)})
            ]),
            permission_assertion="ok",
        ),
        "extractor-native landmark ids cannot leak into stable schema",
    )
    expect(
        TrackingContractError,
        lambda: build_tracking_timeline(
            first,
            backend=FakeBackend([
                BackendFrame(timestamp_us=100, body={"nose": lm(0.5, 0.5)}),
                BackendFrame(timestamp_us=99, body={"nose": lm(0.5, 0.5)}),
            ]),
            permission_assertion="ok",
        ),
        "timestamps must be strictly monotonic",
    )
    expect(
        TrackingContractError,
        lambda: build_tracking_timeline(
            first,
            backend=FakeBackend([BackendFrame(timestamp_us=0, body={})]),
            permission_assertion="ok",
        ),
        "empty observation cannot masquerade as detected body",
    )
    expect(
        TrackingContractError,
        lambda: build_tracking_timeline(
            first,
            backend=FakeBackend([BackendFrame(timestamp_us=0, body={"nose": lm(1.1, 0.5)})]),
            permission_assertion="ok",
        ),
        "out-of-range normalized coordinate fails closed",
    )
    expect(
        TrackingContractError,
        lambda: build_tracking_timeline(first, backend=backend, permission_assertion=""),
        "permission/provenance assertion is mandatory",
    )

schema_path = pathlib.Path("docs/bodyrig/schemas/tracking.schema.json")
schema = json.loads(schema_path.read_text(encoding="utf-8"))
check(schema["properties"]["schema"]["const"] == "bodyrig.tracking/v1",
      "JSON schema pins tracking v1")
check(schema["properties"]["production_activation"]["const"] is False,
      "JSON schema pins production activation false")
check("confidence_frames" in schema["$defs"]["coverage"]["required"],
      "schema distinguishes observation coverage from confidence availability")

print(f"\n===== BODYRIG M1.1 TRACKING CONTRACT: {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
