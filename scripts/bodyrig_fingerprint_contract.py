#!/usr/bin/env python3
"""Dependency-free contract proof for BodyRig M1.2 motion fingerprints."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.fingerprint import (  # noqa: E402
    FEATURE_SPACE,
    FingerprintError,
    build_bodyprint,
    canonical_bodyprint_json,
    gesture_intent,
    validate_bodyprint_package,
)
from bodyrig.runtime import BodyRigRuntime  # noqa: E402
from bodyrig.scheduler import EmbodimentScheduler  # noqa: E402
from bodyrig.tracking import COORDINATE_SPACE, SCHEMA as TRACKING_SCHEMA  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def point(x: float, y: float, z: float = 0.0, confidence: float = 0.9) -> dict:
    return {"x": x, "y": y, "z": z, "confidence": confidence}


def fixture(name: str, *, energetic: bool, hand_coverage: float) -> dict:
    frames = []
    for index in range(10):
        timestamp = index * 100_000
        swing = 0.0 if not energetic else (0.22 if index % 2 == 0 else -0.22)
        head = 0.0 if not energetic else (0.025 if index % 2 == 0 else -0.025)
        body = {
            "nose": point(0.5 + head, 0.22),
            "left_shoulder": point(0.4, 0.40),
            "right_shoulder": point(0.6, 0.40),
            "left_elbow": point(0.36 + swing * 0.45, 0.54),
            "right_elbow": point(0.64 - swing * 0.45, 0.54),
            "left_wrist": point(0.34 + swing, 0.66),
            "right_wrist": point(0.66 - swing, 0.66),
            "left_hip": point(0.44, 0.64),
            "right_hip": point(0.56, 0.64),
            "left_knee": point(0.45, 0.80),
            "right_knee": point(0.55, 0.80),
            "left_ankle": point(0.45, 0.96),
            "right_ankle": point(0.55, 0.96),
        }
        face = {
            "nose_tip": point(0.5 + head, 0.22, confidence=0.8),
            "left_eye_inner": point(0.485 + head, 0.205, confidence=0.8),
            "right_eye_inner": point(0.515 + head, 0.205, confidence=0.8),
        }
        left_hand = None
        right_hand = None
        if hand_coverage > 0:
            left_hand = {"wrist": point(0.34 + swing, 0.66, confidence=hand_coverage)}
            right_hand = {"wrist": point(0.66 - swing, 0.66, confidence=hand_coverage)}
        frames.append(
            {
                "timestamp_us": timestamp,
                "body": body,
                "left_hand": left_hand,
                "right_hand": right_hand,
                "face": face,
                "expressions": {"jaw_open": 0.1 if energetic else 0.0},
            }
        )

    source_sha = hashlib.sha256(name.encode("utf-8")).hexdigest()
    hands_observed = 10 if hand_coverage > 0 else 0
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": source_sha,
            "bytes": 12345,
            "permission_assertion": "synthetic fixture licensed for repository tests",
            "media": {
                "codec": "h264",
                "width": 640,
                "height": 360,
                "duration_us": 1_000_000,
                "nominal_fps": 10.0,
            },
        },
        "backend": {
            "id": "synthetic-test",
            "version": "1.0.0",
            "model_revision": "fixture-v1",
        },
        "frames": frames,
        "coverage": {
            "body": {
                "observed_frames": 10,
                "total_frames": 10,
                "coverage": 1.0,
                "confidence_frames": 10,
                "mean_confidence": 0.9,
            },
            "hands": {
                "observed_frames": hands_observed,
                "total_frames": 10,
                "coverage": hand_coverage if hand_coverage > 0 else 0.0,
                "confidence_frames": hands_observed,
                "mean_confidence": hand_coverage if hand_coverage > 0 else 0.0,
            },
            "face": {
                "observed_frames": 10,
                "total_frames": 10,
                "coverage": 1.0,
                "confidence_frames": 10,
                "mean_confidence": 0.8,
            },
        },
        "recommendations": [] if hand_coverage else ["more_visible_hands"],
        "production_activation": False,
    }


calm_tracking = fixture("calm", energetic=False, hand_coverage=0.0)
active_tracking = fixture("active", energetic=True, hand_coverage=0.8)
calm = build_bodyprint(calm_tracking)
active = build_bodyprint(active_tracking)

check(calm["schema"] == "bodyrig.bodyprint.bundle/v0.1", "builder emits stable bodyprint bundle schema")
check(active["motion_profile"]["feature_space"] == FEATURE_SPACE, "style features are camera-translation/scale normalized")
check(
    active["motion_profile"]["metrics"]["hand_activity_per_second"]
    > calm["motion_profile"]["metrics"]["hand_activity_per_second"],
    "deliberately different motion fixtures produce different fingerprints",
)
check(
    active["motion_profile"]["metrics"]["head_activity_per_second"]
    > calm["motion_profile"]["metrics"]["head_activity_per_second"],
    "head activity remains an interpretable independent feature",
)
check(len(active["gestures"]) >= 1, "active motion yields at least one bounded gesture candidate")
check(
    all(candidate["trajectory_space"] == FEATURE_SPACE for candidate in active["gestures"]),
    "gesture candidates retain normalized replay trajectories without source video",
)
check(
    canonical_bodyprint_json(active) == canonical_bodyprint_json(build_bodyprint(active_tracking)),
    "identical normalized input produces byte-equivalent canonical bodyprint output",
)
check(
    active["manifest"]["id"] == build_bodyprint(active_tracking)["manifest"]["id"],
    "bodyprint identity is content-addressed and deterministic",
)
check(
    calm["manifest"]["confidence"]["hands"] == 0.0,
    "missing hand observations cannot become high-confidence hand style data",
)
check(
    calm["manifest"]["confidence"]["face_behavior"] > 0.0,
    "hand loss does not erase independently observed face behavior",
)
check(
    active["provenance"]["source_video_required_at_runtime"] is False,
    "runtime package explicitly requires no source video",
)
check(
    active["provenance"]["backend"]["id"] == "synthetic-test",
    "extraction backend identity is retained as provenance",
)

candidate = active["gestures"][0]
intent = gesture_intent(candidate)
runtime = BodyRigRuntime(session_id="m12-contract", bodyprint_id=active["manifest"]["id"])
snapshot = runtime.apply_expression_plan(
    sequence=0,
    plan={
        "state": "speaking",
        "gesture": {"intent": intent, "intensity": candidate["confidence"]},
        "gaze": {"target": "user", "intensity": 0.8},
        "emotion": {"name": "neutral", "intensity": 0.0},
        "energy": 0.5,
    },
)
rendered = EmbodimentScheduler(
    session_id="m12-contract", bodyprint_id=active["manifest"]["id"]
).render(snapshot, timestamp_ms=250)
check(rendered.gesture == intent, "extracted gesture reference replays through headless scheduler contract")

bad_metric = copy.deepcopy(active)
bad_metric["motion_profile"]["metrics"]["gesture_range"] = -1.0
try:
    validate_bodyprint_package(bad_metric)
except FingerprintError:
    check(True, "bodyprint validator rejects out-of-range generated style metrics")
else:
    check(False, "bodyprint validator rejects out-of-range generated style metrics")

bad_trajectory = copy.deepcopy(active)
bad_trajectory["gestures"][0]["trajectory"][0]["points"]["wrist"]["x"] = 999.0
try:
    validate_bodyprint_package(bad_trajectory)
except FingerprintError:
    check(True, "bodyprint validator rejects malformed replay trajectories")
else:
    check(False, "bodyprint validator rejects malformed replay trajectories")

bad_activation = copy.deepcopy(active)
bad_activation["production_activation"] = True
try:
    validate_bodyprint_package(bad_activation)
except FingerprintError:
    check(True, "M1.2 package remains fail-closed for production activation")
else:
    check(False, "M1.2 package remains fail-closed for production activation")

print(f"\n===== BODYRIG M1.2 FINGERPRINT: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
