#!/usr/bin/env python3
"""Dependency-free contract proof for BodyRig M1.3 source-relative shape profiles."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.shape import (  # noqa: E402
    ShapeProfileError,
    build_shape_profile,
    canonical_shape_json,
    validate_shape_profile,
)
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


def p(x: float, y: float, confidence: float = 0.92) -> dict:
    return {"x": round(x, 6), "y": round(y, 6), "z": 0.0, "confidence": confidence}


def transform(x: float, y: float, *, scale: float, dx: float, dy: float) -> tuple[float, float]:
    return 0.5 + (x - 0.5) * scale + dx, 0.5 + (y - 0.5) * scale + dy


def body(*, broad: bool, scale: float = 1.0, dx: float = 0.0, dy: float = 0.0, missing_right_wrist: bool = False) -> dict:
    shoulder_half = 0.16 if broad else 0.10
    hip_half = 0.10 if broad else 0.07
    left_elbow_x = 0.23 if broad else 0.30
    right_elbow_x = 0.77 if broad else 0.70
    left_wrist_x = 0.18 if broad else 0.27
    right_wrist_x = 0.80 if broad else 0.73  # deliberate right/left lower-arm asymmetry
    coords = {
        "nose": (0.50, 0.17),
        "left_shoulder": (0.50 - shoulder_half, 0.31),
        "right_shoulder": (0.50 + shoulder_half, 0.31),
        "left_elbow": (left_elbow_x, 0.46),
        "right_elbow": (right_elbow_x, 0.46),
        "left_wrist": (left_wrist_x, 0.60),
        "right_wrist": (right_wrist_x, 0.61),
        "left_hip": (0.50 - hip_half, 0.56),
        "right_hip": (0.50 + hip_half, 0.56),
        "left_knee": (0.43, 0.76),
        "right_knee": (0.57, 0.75),
        "left_ankle": (0.42, 0.95),
        "right_ankle": (0.58, 0.94),
    }
    if missing_right_wrist:
        coords.pop("right_wrist")
    result = {}
    for name, (x, y) in coords.items():
        tx, ty = transform(x, y, scale=scale, dx=dx, dy=dy)
        result[name] = p(tx, ty)
    return result


def fixture(name: str, *, broad: bool, scale: float = 1.0, dx: float = 0.0, dy: float = 0.0, missing_right_wrist: bool = False) -> dict:
    frames = [
        {
            "timestamp_us": index * 100_000,
            "body": body(broad=broad, scale=scale, dx=dx, dy=dy, missing_right_wrist=missing_right_wrist),
            "left_hand": None,
            "right_hand": None,
            "face": None,
            "expressions": None,
        }
        for index in range(8)
    ]
    source_sha = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": source_sha,
            "bytes": 1234,
            "permission_assertion": "synthetic licensed fixture",
            "media": {"codec": "h264", "width": 640, "height": 360, "duration_us": 1_000_000, "nominal_fps": 10.0},
        },
        "backend": {"id": "synthetic-shape", "version": "1.0.0", "model_revision": "fixture-v1"},
        "frames": frames,
        "coverage": {
            "body": {"observed_frames": 8, "total_frames": 8, "coverage": 1.0, "confidence_frames": 8, "mean_confidence": 0.92},
            "hands": {"observed_frames": 0, "total_frames": 8, "coverage": 0.0, "confidence_frames": 0, "mean_confidence": 0.0},
            "face": {"observed_frames": 0, "total_frames": 8, "coverage": 0.0, "confidence_frames": 0, "mean_confidence": 0.0},
        },
        "recommendations": ["more_visible_hands", "need_clearer_face"],
        "production_activation": False,
    }


narrow_tracking = fixture("narrow", broad=False)
broad_tracking = fixture("broad", broad=True)
narrow = build_shape_profile(narrow_tracking)
broad = build_shape_profile(broad_tracking)

check(narrow["schema"] == "bodyrig.shape_profile/v0.1", "builder emits stable M1.3 shape schema")
check(narrow["metric_units"] is False, "profile cannot claim metric anthropometry")
check("viewpoint_sensitive_2d_profile" in narrow["recommendations"], "2D viewpoint ambiguity is explicit")
check(
    broad["measurements"]["shoulder_width"]["ratio"] > narrow["measurements"]["shoulder_width"]["ratio"],
    "deliberately broader shoulders produce a measurably broader profile",
)
check(
    broad["measurements"]["hip_width"]["ratio"] > narrow["measurements"]["hip_width"]["ratio"],
    "deliberately broader hips remain independently measurable",
)

translated_scaled = build_shape_profile(fixture("narrow-xform", broad=False, scale=0.72, dx=0.04, dy=-0.02))
for key in ("shoulder_width", "hip_width", "left_upper_arm", "right_upper_leg", "visible_body_span"):
    check(
        translated_scaled["measurements"][key]["ratio"] == narrow["measurements"][key]["ratio"],
        f"{key} is invariant to uniform image scale and translation",
    )

check(
    canonical_shape_json(narrow) == canonical_shape_json(build_shape_profile(narrow_tracking)),
    "identical tracking input produces byte-equivalent canonical shape output",
)
check(
    narrow["id"] == build_shape_profile(narrow_tracking)["id"],
    "shape identity is deterministic and content-addressed",
)
check(
    "lower_arm" in narrow["asymmetry"] and narrow["asymmetry"]["lower_arm"]["signed_ratio"] != 0.0,
    "left/right asymmetry is preserved rather than averaged away",
)

missing = build_shape_profile(fixture("missing-wrist", broad=False, missing_right_wrist=True))
check("right_lower_arm" not in missing["measurements"], "missing right wrist cannot become a fabricated lower-arm measurement")
check("lower_arm" not in missing["asymmetry"], "asymmetry is omitted when one side lacks evidence")
check("need_more_full_body_views" in missing["recommendations"], "missing body evidence produces a capture recommendation")
check(missing["evidence"]["source_video_required_at_runtime"] is False, "runtime requires no source video")
check(missing["evidence"]["backend"]["id"] == "synthetic-shape", "extraction backend is provenance only")

mutated = copy.deepcopy(narrow)
mutated["measurements"]["shoulder_width"]["ratio"] += 0.001
try:
    validate_shape_profile(mutated)
except ShapeProfileError:
    check(True, "content mutation invalidates the shape profile id")
else:
    check(False, "content mutation invalidates the shape profile id")

bad_ratio = copy.deepcopy(narrow)
bad_ratio["measurements"]["shoulder_width"]["ratio"] = 999.0
try:
    validate_shape_profile(bad_ratio)
except ShapeProfileError:
    check(True, "validator rejects out-of-range source-relative ratios")
else:
    check(False, "validator rejects out-of-range source-relative ratios")

bad_metric = copy.deepcopy(narrow)
bad_metric["metric_units"] = True
try:
    validate_shape_profile(bad_metric)
except ShapeProfileError:
    check(True, "validator rejects false metric-body claims")
else:
    check(False, "validator rejects false metric-body claims")

bad_activation = copy.deepcopy(narrow)
bad_activation["production_activation"] = True
try:
    validate_shape_profile(bad_activation)
except ShapeProfileError:
    check(True, "M1.3 remains fail-closed for production activation")
else:
    check(False, "M1.3 remains fail-closed for production activation")

print(f"\n===== BODYRIG M1.3 SHAPE: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
