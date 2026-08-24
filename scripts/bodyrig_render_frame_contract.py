#!/usr/bin/env python3
"""Contract for the complete renderer-neutral BodyRig RenderFrame v0.1 wire."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig import (  # noqa: E402
    BodyState,
    RenderFrame,
    RenderFrameValidationError,
    TimingMode,
    render_frame_from_mapping,
    render_frame_to_mapping,
)

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def expect_error(payload: dict[str, object], label: str) -> None:
    try:
        render_frame_from_mapping(payload)
    except RenderFrameValidationError:
        check(True, label)
    except Exception as exc:  # pragma: no cover - diagnostics
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, label)
    else:
        check(False, label)


personalized = RenderFrame(
    timestamp_ms=3900,
    state=BodyState.SPEAKING,
    gesture="explain",
    gaze_target="user",
    gaze_strength=0.88,
    emotion="amused",
    emotion_intensity=0.4,
    energy=0.66,
    mouth_open=0.72,
    visemes=(("aa", 0.18), ("oh", 0.82)),
    speech_timing_mode=TimingMode.TIMED,
    blink=0.0,
    breath=0.58,
    head_yaw_hint=0.22,
    head_pitch_hint=-0.08,
    face_profile_id="face-demo",
    face_channels=(
        ("blink_left", 0.0),
        ("blink_right", 0.0),
        ("jaw_open", 0.72),
        ("smile", 0.28),
    ),
    face_channel_sources=(
        ("blink_left", "profile"),
        ("blink_right", "profile"),
        ("jaw_open", "speech"),
        ("smile", "profile_semantic"),
    ),
    body_motion_profile_id="motion-demo",
    body_motion_source="profile",
    head_motion_scale=1.12,
    micro_motion_scale=0.91,
    posture_lean_x=0.08,
    posture_source="profile",
    resolved_gesture="bodyprint:gesture-demo",
    gesture_resolution_source="profile_replay",
    dominant_side_hint="right",
    gesture_frequency_per_minute=12.0,
)
wire = render_frame_to_mapping(personalized)
check(render_frame_from_mapping(wire) == personalized, "complete personalized RenderFrame roundtrips exactly")
check(
    wire["face_profile_id"] == "face-demo"
    and wire["body_motion_profile_id"] == "motion-demo"
    and wire["resolved_gesture"] == "bodyprint:gesture-demo",
    "profile identities and resolved source gesture survive the wire",
)
check(
    wire["gesture_frequency_per_minute"] == {"present": True, "value": 12.0},
    "observed gesture frequency is explicitly present",
)

generic = RenderFrame(
    timestamp_ms=0,
    state=BodyState.IDLE,
    gesture=None,
    gaze_target="user",
    gaze_strength=0.5,
    emotion="neutral",
    emotion_intensity=0.0,
    energy=0.2,
    mouth_open=0.0,
    visemes=(),
    speech_timing_mode=None,
    blink=0.0,
    breath=0.4,
    head_yaw_hint=0.0,
    head_pitch_hint=0.0,
)
generic_wire = render_frame_to_mapping(generic)
check(render_frame_from_mapping(generic_wire) == generic, "generic RenderFrame remains roundtrip-stable")
check(
    generic_wire["gesture_frequency_per_minute"] == {"present": False, "value": 0.0},
    "missing gesture-frequency evidence stays distinct from observed numeric zero",
)

bad = json.loads(json.dumps(wire))
bad["HumanBodyBones.Head"] = 1
expect_error(bad, "renderer-specific extra control fails closed")

bad = json.loads(json.dumps(wire))
bad["face_channel_sources"][0]["id"] = "wrong_channel"
expect_error(bad, "face channel/source mismatch fails closed")

bad = json.loads(json.dumps(generic_wire))
bad["gesture_frequency_per_minute"] = {"present": False, "value": 1.0}
expect_error(bad, "absent optional frequency cannot smuggle a numeric value")

bad = json.loads(json.dumps(wire))
bad["head_motion_scale"] = 2.01
expect_error(bad, "out-of-range motion gain fails closed")

bad = json.loads(json.dumps(wire))
bad["posture_lean_x"] = float("nan")
expect_error(bad, "non-finite posture hint fails closed")

schema = json.loads((ROOT / "docs" / "bodyrig" / "schemas" / "render-frame.schema.json").read_text(encoding="utf-8"))
check(schema.get("additionalProperties") is False, "wire schema rejects unknown top-level fields")
check(
    {"face_channels", "body_motion_source", "resolved_gesture", "gesture_frequency_per_minute"}.issubset(set(schema["required"])),
    "wire schema requires current personalization surfaces",
)

core_sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "bodyrig").glob("*.py"))
check(
    "HumanBodyBones" not in core_sources and "ExpressionPreset" not in core_sources,
    "renderer-neutral BodyRig core contains no Unity/VRM control vocabulary",
)

print(f"\n===== BODYRIG M2.8 RENDER FRAME: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
