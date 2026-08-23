#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bodyrig.face_behavior import (  # noqa: E402
    FaceBehaviorError,
    build_face_behavior,
    canonical_face_behavior_json,
    validate_face_behavior,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_error(fn, message: str) -> None:
    try:
        fn()
    except FaceBehaviorError:
        check(True, message)
    else:
        check(False, message)


def frame(ts: int, blink: float, smile: float, jaw: float, brow: float) -> dict:
    return {
        "timestamp_us": ts,
        "body": None,
        "left_hand": None,
        "right_hand": None,
        "face": {"nose_tip": {"x": 0.5, "y": 0.4, "z": 0.0, "confidence": 0.9}},
        "expressions": {
            "blink_left": blink,
            "blink_right": min(1.0, blink * 0.9),
            "jaw_open": jaw,
            "mouth_smile_left": smile,
            "mouth_smile_right": min(1.0, smile * 0.95),
            "mouth_frown_left": 0.02,
            "mouth_frown_right": 0.03,
            "brow_inner_up": brow,
            "brow_down_left": 0.04,
            "brow_down_right": 0.05,
        },
    }


tracking = {
    "schema": "bodyrig.tracking/v1",
    "coordinate_space": "image_normalized_right_down_depth_relative/v1",
    "source": {"sha256": "a" * 64},
    "backend": {"id": "synthetic", "version": "1", "model_revision": "fixture"},
    "frames": [
        frame(0, 0.05, 0.10, 0.05, 0.10),
        frame(250_000, 0.85, 0.15, 0.15, 0.12),
        frame(500_000, 0.10, 0.55, 0.30, 0.20),
        frame(750_000, 0.90, 0.70, 0.45, 0.35),
        frame(1_000_000, 0.08, 0.20, 0.10, 0.15),
    ],
    "coverage": {
        "body": {"coverage": 0.0, "mean_confidence": 0.0},
        "hands": {"coverage": 0.0, "mean_confidence": 0.0},
        "face": {"coverage": 1.0, "mean_confidence": 0.9},
    },
    "recommendations": [],
    "production_activation": False,
}

profile = build_face_behavior(tracking)
validate_face_behavior(profile)
check(profile["schema"] == "bodyrig.face_behavior/v0.1", "M2.1 schema is explicit")
check(profile["production_activation"] is False, "M2.1 cannot activate production")
check(profile["observation"]["expression_coverage"] == 1.0, "expression coverage is measured")
check(profile["blink"]["left_events"] == 2, "blink threshold crossings are counted")
check(profile["blink"]["left_per_minute"] > 0.0, "blink rate is derived from timestamps")
check(profile["expression_priors"]["smile"] > profile["expression_priors"]["frown"], "source expression priors remain distinguishable")
check(profile["expression_priors"]["jaw_open"] > 0.0, "jaw-open baseline is retained")
check(profile["blink"]["mean_asymmetry"] > 0.0, "left/right blink asymmetry is retained")

same = build_face_behavior(copy.deepcopy(tracking))
check(canonical_face_behavior_json(profile) == canonical_face_behavior_json(same), "identical input is byte-deterministic")

calmer = copy.deepcopy(tracking)
for item in calmer["frames"]:
    item["expressions"]["mouth_smile_left"] = 0.01
    item["expressions"]["mouth_smile_right"] = 0.01
calmer_profile = build_face_behavior(calmer)
check(calmer_profile["expression_priors"]["smile"] < profile["expression_priors"]["smile"], "different source behavior produces a different prior")

missing = copy.deepcopy(tracking)
for item in missing["frames"]:
    item["expressions"] = None
missing["coverage"]["face"]["coverage"] = 0.0
missing["coverage"]["face"]["mean_confidence"] = 0.0
missing_profile = build_face_behavior(missing)
check(missing_profile["observation"]["expression_coverage"] == 0.0, "missing expressions stay missing")
check(missing_profile["expression_priors"]["smile"] == 0.0, "missing evidence is not fabricated into a smile prior")
check(missing_profile["blink"]["mean_per_minute"] == 0.0, "missing evidence is not fabricated into a blink rate")

bad = copy.deepcopy(tracking)
bad["frames"][0]["expressions"]["blink_left"] = 1.2
expect_error(lambda: build_face_behavior(bad), "out-of-range source expressions fail closed")

bad = copy.deepcopy(profile)
bad["production_activation"] = True
expect_error(lambda: validate_face_behavior(bad), "face behavior cannot silently become production-active")

bad = copy.deepcopy(profile)
bad["expression_priors"]["smile"] = float("nan")
expect_error(lambda: canonical_face_behavior_json(bad), "non-finite priors fail closed")

serialized = canonical_face_behavior_json(profile)
check(json.loads(serialized) == profile, "canonical face behavior JSON round-trips")

print(f"\n===== BODYRIG M2.1 FACE BEHAVIOR: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
