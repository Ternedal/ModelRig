#!/usr/bin/env python3
"""Dependency-free contract proof for BodyRig M2.1 facial behavior profiles."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.face_behavior import (  # noqa: E402
    FaceBehaviorError,
    build_face_behavior,
    canonical_face_behavior_json,
    validate_face_behavior,
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


def point(confidence: float = 0.9) -> dict:
    return {"x": 0.5, "y": 0.4, "z": 0.0, "confidence": confidence}


def frame(ts: int, blink: float, smile: float, jaw: float, brow: float) -> dict:
    return {
        "timestamp_us": ts,
        "body": None,
        "left_hand": None,
        "right_hand": None,
        "face": {"nose_tip": point()},
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


def fixture(name: str) -> dict:
    frames = [
        frame(0, 0.05, 0.10, 0.05, 0.10),
        frame(250_000, 0.85, 0.15, 0.15, 0.12),
        frame(500_000, 0.10, 0.55, 0.30, 0.20),
        frame(750_000, 0.90, 0.70, 0.45, 0.35),
        frame(1_000_000, 0.08, 0.20, 0.10, 0.15),
    ]
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
            "bytes": 4321,
            "permission_assertion": "synthetic licensed fixture",
            "media": {
                "codec": "h264",
                "width": 640,
                "height": 360,
                "duration_us": 1_000_000,
                "nominal_fps": 5.0,
            },
        },
        "backend": {
            "id": "synthetic-face",
            "version": "1.0.0",
            "model_revision": "fixture-v1",
        },
        "frames": frames,
        "coverage": {
            "body": {
                "observed_frames": 0,
                "total_frames": 5,
                "coverage": 0.0,
                "confidence_frames": 0,
                "mean_confidence": 0.0,
            },
            "hands": {
                "observed_frames": 0,
                "total_frames": 5,
                "coverage": 0.0,
                "confidence_frames": 0,
                "mean_confidence": 0.0,
            },
            "face": {
                "observed_frames": 5,
                "total_frames": 5,
                "coverage": 1.0,
                "confidence_frames": 5,
                "mean_confidence": 0.9,
            },
        },
        "recommendations": ["need_more_full_body", "more_visible_hands"],
        "production_activation": False,
    }


tracking = fixture("expressive")
profile = build_face_behavior(tracking)
check(profile["schema"] == "bodyrig.face_behavior/v0.1", "M2.1 schema is explicit")
check(profile["production_activation"] is False, "M2.1 cannot activate production")
check(profile["observation"]["expression_coverage"] == 1.0, "expression coverage is measured")
check(profile["blink"]["left"]["events"] == 2, "blink threshold crossings are counted")
check(profile["blink"]["left"]["per_minute"] > 0.0, "blink rate is derived from timestamps")
check(
    profile["expression_priors"]["smile"]["mean"]
    > profile["expression_priors"]["frown"]["mean"],
    "source expression priors remain distinguishable",
)
check(profile["expression_priors"]["jaw_open"]["mean"] > 0.0, "jaw-open baseline is retained")
check(profile["blink"]["paired_asymmetry"]["mean"] > 0.0, "left/right blink asymmetry is retained")
check(profile["provenance"]["source_video_required_at_runtime"] is False, "runtime requires no source video")
check(profile["provenance"]["backend"]["id"] == "synthetic-face", "extractor identity is provenance only")

same = build_face_behavior(copy.deepcopy(tracking))
check(canonical_face_behavior_json(profile) == canonical_face_behavior_json(same), "identical input is byte-deterministic")
check(profile["id"] == same["id"], "face behavior identity is deterministic and content-addressed")

calmer = copy.deepcopy(tracking)
calmer["source"]["sha256"] = hashlib.sha256(b"calmer").hexdigest()
for item in calmer["frames"]:
    item["expressions"]["mouth_smile_left"] = 0.01
    item["expressions"]["mouth_smile_right"] = 0.01
calmer_profile = build_face_behavior(calmer)
check(
    calmer_profile["expression_priors"]["smile"]["mean"]
    < profile["expression_priors"]["smile"]["mean"],
    "different source behavior produces a different prior",
)

missing = copy.deepcopy(tracking)
missing["source"]["sha256"] = hashlib.sha256(b"missing").hexdigest()
for item in missing["frames"]:
    item["expressions"] = None
missing_profile = build_face_behavior(missing)
check(missing_profile["observation"]["expression_coverage"] == 0.0, "missing expressions stay missing")
check(missing_profile["expression_priors"]["smile"]["mean"] is None, "missing smile evidence remains null")
check(missing_profile["expression_priors"]["smile"]["samples"] == 0, "missing smile evidence has zero samples")
check(missing_profile["blink"]["mean_per_minute"] is None, "missing blink evidence remains null rather than neutral zero")

expression_only = copy.deepcopy(tracking)
expression_only["source"]["sha256"] = hashlib.sha256(b"expression-only").hexdigest()
for item in expression_only["frames"]:
    item["face"] = None
expression_only["coverage"]["face"]["confidence_frames"] = 0
expression_only["coverage"]["face"]["mean_confidence"] = 0.0
expression_only_profile = build_face_behavior(expression_only)
check(expression_only_profile["expression_priors"]["smile"]["samples"] == 5, "expression-only evidence remains usable")
check(expression_only_profile["observation"]["face_landmark_confidence"] == 0.0, "expression evidence does not invent landmark confidence")

mutated = copy.deepcopy(profile)
mutated["expression_priors"]["smile"]["mean"] += 0.001
try:
    validate_face_behavior(mutated)
except FaceBehaviorError:
    check(True, "content mutation invalidates facial-behavior id")
else:
    check(False, "content mutation invalidates facial-behavior id")

bad = copy.deepcopy(tracking)
bad["frames"][0]["expressions"]["blink_left"] = 1.2
try:
    build_face_behavior(bad)
except FaceBehaviorError:
    check(True, "out-of-range source expressions fail closed")
else:
    check(False, "out-of-range source expressions fail closed")

bad = copy.deepcopy(profile)
bad["production_activation"] = True
try:
    validate_face_behavior(bad)
except FaceBehaviorError:
    check(True, "facial behavior cannot silently become production-active")
else:
    check(False, "facial behavior cannot silently become production-active")

bad = copy.deepcopy(profile)
bad["expression_priors"]["smile"]["mean"] = float("nan")
try:
    canonical_face_behavior_json(bad)
except FaceBehaviorError:
    check(True, "non-finite priors fail closed")
else:
    check(False, "non-finite priors fail closed")

print(f"\n===== BODYRIG M2.1 FACE BEHAVIOR: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
