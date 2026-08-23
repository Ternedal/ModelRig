#!/usr/bin/env python3
"""Dependency-free contract proof for BodyRig M2.4 unified identity bundles."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.face_behavior import build_face_behavior, validate_face_behavior  # noqa: E402
from bodyrig.fingerprint import build_bodyprint, validate_bodyprint_package  # noqa: E402
from bodyrig.identity import (  # noqa: E402
    IdentityBundleError,
    build_identity_bundle,
    canonical_component_jsons,
    canonical_identity_json,
    compose_identity_bundle,
    validate_identity_bundle,
)
from bodyrig.shape import ShapeConfig, build_shape_profile, validate_shape_profile  # noqa: E402
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


def expect_error(fn, label: str) -> None:
    try:
        fn()
    except IdentityBundleError:
        check(True, label)
    else:
        check(False, label)


def point(x: float, y: float, z: float = 0.0, confidence: float = 0.9) -> dict:
    return {"x": x, "y": y, "z": z, "confidence": confidence}


def fixture(source_name: str, *, backend_id: str = "identity-fixture") -> dict:
    frames = []
    for index in range(8):
        ts = index * 100_000
        swing = 0.12 if index % 2 == 0 else -0.12
        head = 0.018 if index % 2 == 0 else -0.018
        blink = 0.85 if index in {2, 6} else 0.05
        smile = 0.12 + index * 0.04
        body = {
            "nose": point(0.5 + head, 0.20),
            "left_shoulder": point(0.40, 0.36),
            "right_shoulder": point(0.60, 0.36),
            "left_elbow": point(0.34 + swing * 0.25, 0.50),
            "right_elbow": point(0.66 - swing * 0.25, 0.50),
            "left_wrist": point(0.30 + swing, 0.62),
            "right_wrist": point(0.70 - swing, 0.62),
            "left_hip": point(0.44, 0.60),
            "right_hip": point(0.56, 0.60),
            "left_knee": point(0.44, 0.77),
            "right_knee": point(0.56, 0.77),
            "left_ankle": point(0.43, 0.94),
            "right_ankle": point(0.57, 0.94),
        }
        face = {
            "nose_tip": point(0.5 + head, 0.20, confidence=0.88),
            "left_eye_inner": point(0.485 + head, 0.185, confidence=0.86),
            "right_eye_inner": point(0.515 + head, 0.185, confidence=0.86),
            "mouth_left": point(0.475 + head, 0.235, confidence=0.84),
            "mouth_right": point(0.525 + head, 0.235, confidence=0.84),
        }
        expressions = {
            "blink_left": blink,
            "blink_right": max(0.0, blink - 0.03),
            "jaw_open": 0.10 + index * 0.02,
            "mouth_smile_left": smile,
            "mouth_smile_right": max(0.0, smile - 0.02),
            "mouth_frown_left": 0.03,
            "mouth_frown_right": 0.04,
            "brow_inner_up": 0.15 + index * 0.01,
            "brow_down_left": 0.05,
            "brow_down_right": 0.06,
        }
        frames.append(
            {
                "timestamp_us": ts,
                "body": body,
                "left_hand": {"wrist": point(0.30 + swing, 0.62, confidence=0.82)},
                "right_hand": {"wrist": point(0.70 - swing, 0.62, confidence=0.80)},
                "face": face,
                "expressions": expressions,
            }
        )

    source_sha = hashlib.sha256(source_name.encode("utf-8")).hexdigest()
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": source_sha,
            "bytes": 24680,
            "permission_assertion": "synthetic local fixture licensed for repository tests",
            "media": {
                "codec": "h264",
                "width": 1280,
                "height": 720,
                "duration_us": 800_000,
                "nominal_fps": 10.0,
            },
        },
        "backend": {
            "id": backend_id,
            "version": "1.0.0",
            "model_revision": "identity-fixture-r1",
        },
        "frames": frames,
        "coverage": {
            "body": {
                "observed_frames": 8,
                "total_frames": 8,
                "coverage": 1.0,
                "confidence_frames": 8,
                "mean_confidence": 0.9,
            },
            "hands": {
                "observed_frames": 8,
                "total_frames": 8,
                "coverage": 1.0,
                "confidence_frames": 8,
                "mean_confidence": 0.81,
            },
            "face": {
                "observed_frames": 8,
                "total_frames": 8,
                "coverage": 1.0,
                "confidence_frames": 8,
                "mean_confidence": 0.86,
            },
        },
        "recommendations": [],
        "production_activation": False,
    }


tracking = fixture("identity-source-a")
bundle = build_identity_bundle(tracking)
validate_identity_bundle(bundle)
serialized = canonical_identity_json(bundle)

check(bundle["schema"] == "bodyrig.identity_bundle/v0.1", "M2.4 schema is explicit")
check(bundle["id"].startswith("bodyid-"), "unified identity has a content-addressed bodyid")
check(bundle["production_activation"] is False, "unified identity cannot activate production")
check(
    bundle["runtime"]["source_video_required_at_runtime"] is False,
    "unified runtime explicitly requires no source video",
)

repeat = build_identity_bundle(copy.deepcopy(tracking))
check(
    canonical_identity_json(repeat) == serialized and repeat["id"] == bundle["id"],
    "same tracking receipt produces byte-equivalent deterministic identity",
)

motion = build_bodyprint(tracking)
shape = build_shape_profile(tracking)
face = build_face_behavior(tracking)
composed = compose_identity_bundle(motion=motion, shape=shape, face=face)
check(
    canonical_identity_json(composed) == serialized,
    "direct build and compose-from-components produce the same canonical identity",
)
check(
    bundle["component_ids"]
    == {
        "motion": motion["manifest"]["id"],
        "shape": shape["id"],
        "face": face["id"],
    },
    "all original component ids remain explicit in the unified identity",
)
validate_bodyprint_package(bundle["components"]["motion"])
validate_shape_profile(bundle["components"]["shape"])
validate_face_behavior(bundle["components"]["face"])
check(True, "all embedded components remain individually valid")
check(
    set(canonical_component_jsons(bundle)) == {"motion", "shape", "face"},
    "bundle can expose individually canonical component payloads for later package builders",
)

# A valid component built with a different extraction config but the same
# tracking receipt must produce a new whole identity rather than inheriting the
# old unified id.
shape_alt = build_shape_profile(
    tracking,
    config=ShapeConfig(min_point_confidence=0.40, min_samples=3),
)
validate_shape_profile(shape_alt)
alt_bundle = compose_identity_bundle(motion=motion, shape=shape_alt, face=face)
check(shape_alt["id"] != shape["id"], "valid shape config change produces a distinct component identity")
check(alt_bundle["id"] != bundle["id"], "valid component content change produces a distinct unified identity")

# Cross-source mixing must fail even though every component is individually valid.
tracking_other = fixture("identity-source-b")
face_other = build_face_behavior(tracking_other)
expect_error(
    lambda: compose_identity_bundle(motion=motion, shape=shape, face=face_other),
    "components from different source/tracking receipts cannot be composed",
)

# Same source SHA is not enough: a backend change changes the tracking receipt
# and must remain visible at the unified boundary.
tracking_backend_other = fixture("identity-source-a", backend_id="identity-fixture-other")
shape_backend_other = build_shape_profile(tracking_backend_other)
check(
    tracking_backend_other["source"]["sha256"] == tracking["source"]["sha256"]
    and tracking_backend_other["backend"]["id"] != tracking["backend"]["id"],
    "backend-mismatch fixture intentionally keeps identical source bytes identity",
)
expect_error(
    lambda: compose_identity_bundle(motion=motion, shape=shape_backend_other, face=face),
    "backend mismatch cannot hide behind matching source SHA",
)

# Component tampering must fail at the component validator before a new unified
# identity can be calculated.
tampered_face = copy.deepcopy(face)
tampered_face["expression_priors"]["smile"]["mean"] = 0.123456
expect_error(
    lambda: compose_identity_bundle(motion=motion, shape=shape, face=tampered_face),
    "tampered component fails closed before identity composition",
)

# Whole-bundle mutation with otherwise valid component data must invalidate the
# top-level content id.
tampered_bundle = copy.deepcopy(bundle)
tampered_bundle["builder"]["version"] = "0.1.1"
expect_error(
    lambda: validate_identity_bundle(tampered_bundle),
    "whole-bundle metadata mutation cannot retain the old content id",
)

bad = copy.deepcopy(bundle)
bad["production_activation"] = True
expect_error(
    lambda: validate_identity_bundle(bad),
    "unified identity cannot silently become production-active",
)

bad = copy.deepcopy(bundle)
bad["unexpected"] = True
expect_error(
    lambda: validate_identity_bundle(bad),
    "unsupported identity fields fail closed",
)

# Portable bundle contains only derived data/provenance, never source path/name
# or source byte-count metadata from the tracking input.
check("identity-source-a" not in serialized, "source name/path does not leak into unified identity")
check('"bytes"' not in serialized, "tracking source byte-count metadata is not embedded")
check(
    tracking["source"]["sha256"] == bundle["binding"]["source_sha256"],
    "portable identity retains only the source digest needed for provenance binding",
)

renderer_terms = ("humanbodybones", "blendshape", "morph_target", "animator_controller", "unity_clip")
check(
    not any(term in serialized.lower() for term in renderer_terms),
    "M2.4 identity introduces no renderer-specific control vocabulary",
)
check(json.loads(serialized) == bundle, "canonical unified identity JSON round-trips exactly")

print(f"\n===== BODYRIG M2.4 IDENTITY BUNDLE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
