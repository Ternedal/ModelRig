#!/usr/bin/env python3
"""Dependency-free contract proof for BodyRig M2.3 personalized body motion."""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.body_motion_mixer import (  # noqa: E402
    BodyMotionMixer,
    BodyMotionMixerError,
)
from bodyrig.fingerprint import build_bodyprint  # noqa: E402
from bodyrig.runtime import BodyRigRuntime  # noqa: E402
from bodyrig.scheduler import EmbodimentScheduler, SchedulerError  # noqa: E402
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


def expect_error(fn, label: str, error_type=Exception) -> None:
    try:
        fn()
    except error_type:
        check(True, label)
    else:
        check(False, label)


def point(x: float, y: float, z: float = 0.0, confidence: float = 0.9) -> dict:
    return {"x": x, "y": y, "z": z, "confidence": confidence}


def tracking_fixture(
    name: str,
    *,
    energetic: bool,
    shoulder_lean: float,
    body_coverage: float = 1.0,
    body_mean_confidence: float = 0.9,
) -> dict:
    frames = []
    for index in range(10):
        timestamp = index * 100_000
        swing = 0.0 if not energetic else (0.22 if index % 2 == 0 else -0.22)
        head = 0.0 if not energetic else (0.030 if index % 2 == 0 else -0.030)
        body = {
            "nose": point(0.5 + shoulder_lean + head, 0.22),
            "left_shoulder": point(0.4 + shoulder_lean, 0.40),
            "right_shoulder": point(0.6 + shoulder_lean, 0.40),
            "left_elbow": point(0.36 + shoulder_lean + swing * 0.45, 0.54),
            "right_elbow": point(0.64 + shoulder_lean - swing * 0.45, 0.54),
            "left_wrist": point(0.34 + shoulder_lean + swing, 0.66),
            "right_wrist": point(0.66 + shoulder_lean - swing, 0.66),
            "left_hip": point(0.44, 0.64),
            "right_hip": point(0.56, 0.64),
            "left_knee": point(0.45, 0.80),
            "right_knee": point(0.55, 0.80),
            "left_ankle": point(0.45, 0.96),
            "right_ankle": point(0.55, 0.96),
        }
        frames.append(
            {
                "timestamp_us": timestamp,
                "body": body,
                "left_hand": None,
                "right_hand": None,
                "face": None,
                "expressions": None,
            }
        )

    observed = 10 if body_coverage > 0.0 else 0
    return {
        "schema": TRACKING_SCHEMA,
        "coordinate_space": COORDINATE_SPACE,
        "source": {
            "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
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
                "observed_frames": observed,
                "total_frames": 10,
                "coverage": body_coverage,
                "confidence_frames": observed,
                "mean_confidence": body_mean_confidence,
            },
            "hands": {
                "observed_frames": 0,
                "total_frames": 10,
                "coverage": 0.0,
                "confidence_frames": 0,
                "mean_confidence": 0.0,
            },
            "face": {
                "observed_frames": 0,
                "total_frames": 10,
                "coverage": 0.0,
                "confidence_frames": 0,
                "mean_confidence": 0.0,
            },
        },
        "recommendations": [],
        "production_activation": False,
    }


calm = build_bodyprint(
    tracking_fixture("m23-calm", energetic=False, shoulder_lean=-0.035)
)
active = build_bodyprint(
    tracking_fixture("m23-active", energetic=True, shoulder_lean=0.045)
)
low_confidence = build_bodyprint(
    tracking_fixture(
        "m23-low-confidence",
        energetic=True,
        shoulder_lean=0.08,
        body_coverage=0.1,
        body_mean_confidence=0.1,
    )
)

check(len(active["gestures"]) >= 1, "active M1.2 fixture yields extracted gesture evidence")
check(
    active["motion_profile"]["metrics"]["head_activity_per_second"]
    > calm["motion_profile"]["metrics"]["head_activity_per_second"],
    "fixture pair carries measurably different source head activity",
)


def snapshot_for(package: dict, *, session_id: str, gesture: str | None = "explain"):
    runtime = BodyRigRuntime(session_id=session_id, bodyprint_id=package["manifest"]["id"])
    return runtime.apply_expression_plan(
        sequence=0,
        plan={
            "state": "speaking",
            "gesture": None if gesture is None else {"intent": gesture, "intensity": 0.5},
            "gaze": {"target": "user", "intensity": 0.8},
            "emotion": {"name": "neutral", "intensity": 0.0},
            "energy": 0.5,
        },
    )


calm_snapshot = snapshot_for(calm, session_id="m23-calm")
active_snapshot = snapshot_for(active, session_id="m23-active")
calm_mixer = BodyMotionMixer(
    session_id="m23-calm",
    bodyprint_id=calm["manifest"]["id"],
    bodyprint_package=calm,
)
active_mixer = BodyMotionMixer(
    session_id="m23-active",
    bodyprint_id=active["manifest"]["id"],
    bodyprint_package=active,
)
calm_frame = calm_mixer.render(calm_snapshot, timestamp_ms=1200)
active_frame = active_mixer.render(active_snapshot, timestamp_ms=1200)

check(calm_frame.source == "profile" and active_frame.source == "profile", "usable M1.2 motion evidence activates profile mixing")
check(
    active_frame.head_motion_scale > calm_frame.head_motion_scale,
    "different source head activity produces different runtime head-motion gain",
)
check(
    active_frame.micro_motion_scale > calm_frame.micro_motion_scale,
    "different source movement produces different runtime micro-motion gain",
)
check(
    calm_frame.posture_source == "profile"
    and active_frame.posture_source == "profile"
    and calm_frame.posture_lean_x < active_frame.posture_lean_x,
    "source-relative posture lean remains a separate personalized hint",
)
check(
    active_frame.gesture_semantic == "explain"
    and active_frame.gesture_replay is not None
    and active_frame.gesture_replay.startswith("bodyprint:gesture-")
    and active_frame.gesture_source == "profile_replay",
    "semantic gesture resolves to one deterministic extracted source trajectory",
)
check(
    active_mixer.render(active_snapshot, timestamp_ms=1200) == active_frame,
    "same package/session/state/time is dataclass-equivalent and deterministic",
)

no_gesture_snapshot = snapshot_for(active, session_id="m23-no-gesture", gesture=None)
no_gesture_mixer = BodyMotionMixer(
    session_id="m23-no-gesture",
    bodyprint_id=active["manifest"]["id"],
    bodyprint_package=active,
)
no_gesture = no_gesture_mixer.render(no_gesture_snapshot, timestamp_ms=1200)
check(
    no_gesture.gesture_semantic is None
    and no_gesture.gesture_replay is None
    and no_gesture.gesture_source == "none",
    "M2.3 never invents a gesture when ModelRig requested none",
)

explicit = f"bodyprint:{active['gestures'][0]['id']}"
explicit_snapshot = snapshot_for(active, session_id="m23-explicit", gesture=explicit)
explicit_mixer = BodyMotionMixer(
    session_id="m23-explicit",
    bodyprint_id=active["manifest"]["id"],
    bodyprint_package=active,
)
explicit_frame = explicit_mixer.render(explicit_snapshot, timestamp_ms=900)
check(
    explicit_frame.gesture_semantic == explicit
    and explicit_frame.gesture_replay == explicit
    and explicit_frame.gesture_source == "explicit_profile",
    "valid explicit bodyprint gesture reference remains exact",
)

bad_explicit_snapshot = snapshot_for(
    active,
    session_id="m23-bad-explicit",
    gesture="bodyprint:gesture-does-not-exist",
)
bad_explicit_mixer = BodyMotionMixer(
    session_id="m23-bad-explicit",
    bodyprint_id=active["manifest"]["id"],
    bodyprint_package=active,
)
expect_error(
    lambda: bad_explicit_mixer.render(bad_explicit_snapshot, timestamp_ms=900),
    "unknown explicit bodyprint gesture fails closed",
    BodyMotionMixerError,
)

low_snapshot = snapshot_for(low_confidence, session_id="m23-low")
low_mixer = BodyMotionMixer(
    session_id="m23-low",
    bodyprint_id=low_confidence["manifest"]["id"],
    bodyprint_package=low_confidence,
)
low_frame = low_mixer.render(low_snapshot, timestamp_ms=1200)
check(
    low_frame.source == "generic"
    and low_frame.head_motion_scale == 1.0
    and low_frame.micro_motion_scale == 1.0
    and low_frame.posture_source == "generic",
    "low-confidence motion evidence uses explicit generic fallback",
)
check(
    low_frame.gesture_replay is None and low_frame.gesture_source == "semantic",
    "low-confidence motion cannot silently select an extracted trajectory",
)

# Whole-package identity must be checked before runtime use.
tampered = copy.deepcopy(active)
tampered["motion_profile"]["metrics"]["head_activity_per_second"] += 0.001
expect_error(
    lambda: BodyMotionMixer(
        session_id="m23-tampered",
        bodyprint_id=active["manifest"]["id"],
        bodyprint_package=tampered,
    ),
    "tampered content-addressed M1.2 package fails closed before runtime use",
    BodyMotionMixerError,
)

expect_error(
    lambda: BodyMotionMixer(
        session_id="m23-id-mismatch",
        bodyprint_id="bodyprint-wrong",
        bodyprint_package=active,
    ),
    "bodyprint package/runtime identity mismatch fails closed",
    BodyMotionMixerError,
)

# Backward compatibility: without a bodyprint package, the scheduler must keep
# the original generic procedural math exactly.
generic_session = "m23-generic"
generic_id = "bp-generic"
generic_runtime = BodyRigRuntime(session_id=generic_session, bodyprint_id=generic_id)
generic_snapshot = generic_runtime.apply_expression_plan(
    sequence=0,
    plan={
        "state": "thinking",
        "gesture": {"intent": "explain", "intensity": 0.5},
        "gaze": {"target": "user", "intensity": 0.8},
        "emotion": {"name": "thoughtful", "intensity": 0.3},
        "energy": 0.5,
    },
)
generic_scheduler = EmbodimentScheduler(session_id=generic_session, bodyprint_id=generic_id)
generic_timestamp = 1375
generic_frame = generic_scheduler.render(generic_snapshot, timestamp_ms=generic_timestamp)
digest = hashlib.sha256(f"{generic_session}:{generic_id}".encode("utf-8")).digest()
phase_a = int.from_bytes(digest[0:4], "big") / 2**32
phase_b = int.from_bytes(digest[4:8], "big") / 2**32
seconds = generic_timestamp / 1000.0
state_scale = 0.85
energy_scale = 0.55 + 0.9 * generic_snapshot.energy
expected_yaw = 0.05 * state_scale * energy_scale * math.sin(
    2.0 * math.pi * (seconds / 6.7 + phase_b)
)
expected_pitch = 0.035 * state_scale * energy_scale * math.sin(
    2.0 * math.pi * (seconds / 5.1 + phase_a * 0.7)
)
expected_breath = 0.5 + 0.5 * math.sin(2.0 * math.pi * (seconds / 4.2 + phase_a))
check(
    generic_frame.head_yaw_hint == expected_yaw
    and generic_frame.head_pitch_hint == expected_pitch
    and generic_frame.breath == expected_breath,
    "scheduler without M1.2 package preserves pre-M2.3 procedural math exactly",
)
check(
    generic_frame.body_motion_profile_id is None
    and generic_frame.body_motion_source == "generic"
    and generic_frame.head_motion_scale == 1.0
    and generic_frame.micro_motion_scale == 1.0
    and generic_frame.resolved_gesture is None,
    "scheduler without package exposes only explicit generic M2.3 defaults",
)

# Personalized scheduler: same generic machinery, scaled by validated source evidence.
personal_session = "m23-scheduler"
personal_snapshot = snapshot_for(active, session_id=personal_session)
personal_generic = EmbodimentScheduler(
    session_id=personal_session,
    bodyprint_id=active["manifest"]["id"],
).render(personal_snapshot, timestamp_ms=1375)
personalized = EmbodimentScheduler(
    session_id=personal_session,
    bodyprint_id=active["manifest"]["id"],
    bodyprint_package=active,
).render(personal_snapshot, timestamp_ms=1375)
check(
    personalized.body_motion_profile_id == active["manifest"]["id"]
    and personalized.body_motion_source == "profile",
    "scheduler binds personalized output to the validated M1.2 bodyprint id",
)
check(
    personalized.head_motion_scale != 1.0
    and personalized.head_yaw_hint == personal_generic.head_yaw_hint * personalized.head_motion_scale
    and personalized.head_pitch_hint == personal_generic.head_pitch_hint * personalized.head_motion_scale,
    "scheduler applies source-specific head-motion gain without changing semantic state",
)
check(
    personalized.gesture == "explain"
    and personalized.resolved_gesture is not None
    and personalized.gesture_resolution_source == "profile_replay",
    "scheduler keeps ModelRig semantic gesture while exposing source replay separately",
)
check(
    personalized.dominant_side_hint in {"left", "right", "balanced"}
    and personalized.gesture_frequency_per_minute is not None,
    "scheduler exposes source motion-style metadata as renderer-neutral hints",
)

renderer_specific = {"vrm", "blendshape", "morph", "bone", "clip", "animation"}
field_names = {name.lower() for name in personalized.__dataclass_fields__}
check(
    not any(token in field for field in field_names for token in renderer_specific),
    "M2.3 scheduler surface emits no renderer-specific bone/clip/morph identifiers",
)

foreign_runtime = BodyRigRuntime(session_id="foreign", bodyprint_id=active["manifest"]["id"])
foreign_snapshot = foreign_runtime.apply_state(sequence=0, state="idle")
expect_error(
    lambda: active_mixer.render(foreign_snapshot, timestamp_ms=100),
    "body motion mixer rejects cross-session snapshot injection",
    BodyMotionMixerError,
)

try:
    EmbodimentScheduler(
        session_id="m23-scheduler-tampered",
        bodyprint_id=active["manifest"]["id"],
        bodyprint_package=tampered,
    )
except SchedulerError:
    check(True, "scheduler rejects tampered M1.2 package before rendering")
else:
    check(False, "scheduler rejects tampered M1.2 package before rendering")

print(f"\n===== BODYRIG M2.3 BODY MOTION MIXER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
